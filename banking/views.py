import csv
import uuid
from datetime import datetime, time

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import customer_required, verified_required
from core.audit import log_event
from core.models import AuditLog
from core.ratelimit import ratelimit

from . import services
from .forms import BeneficiaryForm, ConfirmTransferForm, FundForm, OpenAccountForm, TransferForm
from .models import Account, Beneficiary, LedgerEntry, Transaction
from .notifications import send_transfer_alerts
from .utils import csv_safe

PENDING_KEY = "pending_transfer"
MAX_REAUTH_ATTEMPTS = 3


def _own_account_or_404(request, pk):
    return get_object_or_404(Account, pk=pk, customer=request.user.customer)


@customer_required
def dashboard(request):
    customer = request.user.customer
    accounts = list(customer.accounts.exclude(status=Account.Status.CLOSED))
    total = sum((a.balance for a in accounts), start=0)
    recent = LedgerEntry.objects.filter(account__customer=customer).select_related("account")[:8]
    previous = list(AuditLog.objects.filter(user=request.user, event="login.success")[1:2])
    return render(request, "banking/dashboard.html", {
        "customer": customer, "accounts": accounts, "total": total, "recent": recent,
        "previous_login": previous[0] if previous else None,
        "daily_remaining": services.daily_remaining(customer),
    })


@verified_required
def open_account(request):
    customer = request.user.customer
    form = OpenAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            account = services.open_account(
                customer, form.cleaned_data["account_type"], form.cleaned_data["nickname"],
                form.cleaned_data.get("initial_deposit") or 0,
            )
        except services.BankingError as exc:
            form.add_error(None, str(exc))
        else:
            log_event("account.opened", request, account=account.masked_number, type=account.account_type)
            messages.success(request, f"Your new account {account.masked_number} is open.")
            return redirect("banking:account_detail", pk=account.pk)
    return render(request, "banking/open_account.html", {"form": form})


def _filtered_entries(request, account):
    entries = LedgerEntry.objects.filter(account=account).select_related("transaction")
    start, end = request.GET.get("start", ""), request.GET.get("end", "")
    direction = request.GET.get("type", "")
    tz = timezone.get_current_timezone()
    try:
        if start:
            entries = entries.filter(created_at__gte=datetime.combine(datetime.strptime(start, "%Y-%m-%d").date(), time.min, tz))
        if end:
            entries = entries.filter(created_at__lte=datetime.combine(datetime.strptime(end, "%Y-%m-%d").date(), time.max, tz))
    except ValueError:
        start = end = ""
    if direction in ("DR", "CR"):
        entries = entries.filter(direction=direction)
    else:
        direction = ""
    return entries, {"start": start, "end": end, "type": direction}


@customer_required
def account_detail(request, pk):
    account = _own_account_or_404(request, pk)
    entries, filters = _filtered_entries(request, account)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="statement-{account.account_number[-4:]}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Reference", "Description", "Debit", "Credit", "Balance"])
        for e in entries.order_by("created_at", "pk"):
            writer.writerow([
                timezone.localtime(e.created_at).strftime("%Y-%m-%d %H:%M"), e.transaction.reference,
                csv_safe(e.description), e.amount if e.direction == "DR" else "",
                e.amount if e.direction == "CR" else "", e.balance_after,
            ])
        log_event("statement.exported", request, account=account.masked_number)
        return response
    page = Paginator(entries, 20).get_page(request.GET.get("page"))
    query = "&".join(f"{k}={v}" for k, v in filters.items() if v)
    return render(request, "banking/account_detail.html", {
        "account": account, "page": page, "filters": filters, "query": query,
    })


@verified_required
def fund_account(request, pk):
    if not settings.DEMO_MODE:
        raise Http404
    account = _own_account_or_404(request, pk)
    form = FundForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.deposit(
                account.pk, form.cleaned_data["amount"], "Demo funds added", initiated_by=request.user, demo_limit=True
            )
        except services.BankingError as exc:
            form.add_error("amount", str(exc))
        else:
            log_event("account.funded", request, account=account.masked_number, amount=str(form.cleaned_data["amount"]))
            messages.success(request, "Demo funds added.")
            return redirect("banking:account_detail", pk=account.pk)
    return render(request, "banking/fund.html", {"form": form, "account": account, "max_funding": settings.DEMO_MAX_FUNDING})


# ----------------------------- transfers ------------------------------------ #
@verified_required
def transfer(request):
    customer = request.user.customer
    form = TransferForm(customer, request.POST or None, initial={"from_account": request.GET.get("from")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        request.session[PENDING_KEY] = {
            "from": d["from_account"].pk, "to": d["target_account"].pk, "amount": str(d["amount"]),
            "remarks": d["remarks"], "key": uuid.uuid4().hex, "created": timezone.now().timestamp(), "attempts": 0,
        }
        return redirect("banking:transfer_review")
    return render(request, "banking/transfer.html", {
        "form": form, "remaining": services.daily_remaining(customer), "customer": customer,
        "has_accounts": customer.accounts.filter(status=Account.Status.ACTIVE).exists(),
    })


def _load_pending(request):
    pending = request.session.get(PENDING_KEY)
    if not pending:
        return None
    if timezone.now().timestamp() - pending["created"] > settings.TRANSFER_REVIEW_TTL_SECONDS:
        request.session.pop(PENDING_KEY, None)
        return None
    return pending


@verified_required
def transfer_review(request):
    pending = _load_pending(request)
    if pending is None:
        messages.info(request, "That transfer request expired. Please start again.")
        return redirect("banking:transfer")
    customer = request.user.customer
    source = Account.objects.select_related("customer__user").filter(pk=pending["from"], customer=customer).first()
    target = Account.objects.select_related("customer__user").filter(pk=pending["to"]).first()
    if source is None or target is None:
        request.session.pop(PENDING_KEY, None)
        return redirect("banking:transfer")

    form = ConfirmTransferForm(request.POST or None)
    if request.method == "POST":
        if "cancel" in request.POST:
            request.session.pop(PENDING_KEY, None)
            messages.info(request, "Transfer cancelled.")
            return redirect("banking:dashboard")
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data["password"]):
                pending["attempts"] += 1
                request.session[PENDING_KEY] = pending
                log_event("transfer.reauth_failed", request)
                if pending["attempts"] >= MAX_REAUTH_ATTEMPTS:
                    request.session.pop(PENDING_KEY, None)
                    messages.error(request, "Too many incorrect passwords. The transfer was cancelled.")
                    return redirect("banking:transfer")
                form.add_error("password", "Incorrect password.")
            else:
                try:
                    txn, created = services.execute_transfer(
                        sender_id=source.pk, receiver_id=target.pk, amount=pending["amount"],
                        remarks=pending["remarks"], initiated_by=request.user, idempotency_key=pending["key"],
                    )
                except services.BankingError as exc:
                    request.session.pop(PENDING_KEY, None)
                    messages.error(request, str(exc))
                    return redirect("banking:transfer")
                request.session.pop(PENDING_KEY, None)
                if created:
                    log_event("transfer.posted", request, reference=txn.reference, amount=str(txn.amount))
                    send_transfer_alerts(txn)
                return redirect("banking:receipt", reference=txn.reference)
    return render(request, "banking/transfer_review.html", {
        "form": form, "pending": pending, "source": source, "target": target,
        "amount": pending["amount"], "same_owner": target.customer_id == customer.pk,
    })


@customer_required
def receipt(request, reference):
    customer = request.user.customer
    txn = get_object_or_404(
        Transaction.objects.select_related(
            "source_account__customer__user", "destination_account__customer__user"
        ).filter(Q(source_account__customer=customer) | Q(destination_account__customer=customer)),
        reference=reference,
    )
    return render(request, "banking/receipt.html", {
        "txn": txn, "is_sender": txn.source_account is not None and txn.source_account.customer_id == customer.pk,
    })


# ----------------------------- beneficiaries -------------------------------- #
@customer_required
def beneficiaries(request):
    items = request.user.customer.beneficiaries.select_related("account__customer__user")
    return render(request, "banking/beneficiaries.html", {"items": items})


@verified_required
@ratelimit("beneficiary", limit=20, period=3600)
def beneficiary_add(request):
    customer = request.user.customer
    form = BeneficiaryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            ben = services.add_beneficiary(customer, form.cleaned_data["account_number"], form.cleaned_data["nickname"])
        except services.BankingError as exc:
            form.add_error("account_number", str(exc))
        else:
            log_event("beneficiary.added", request, account=ben.account.masked_number)
            messages.success(request, f"{ben.nickname} was added as a beneficiary.")
            return redirect("banking:beneficiaries")
    return render(request, "banking/beneficiary_form.html", {"form": form})


@customer_required
@require_POST
def beneficiary_delete(request, pk):
    ben = get_object_or_404(Beneficiary, pk=pk, customer=request.user.customer)
    log_event("beneficiary.removed", request, account=ben.account.masked_number)
    ben.delete()
    messages.info(request, "Beneficiary removed.")
    return redirect("banking:beneficiaries")


@customer_required
def activity(request):
    events = AuditLog.objects.filter(user=request.user).exclude(event="admin.blocked")[:50]
    return render(request, "banking/activity.html", {"events": events})
