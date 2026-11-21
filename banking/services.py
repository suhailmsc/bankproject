"""
Money-moving business logic. Views never touch balances directly.

Concurrency model: every posting runs in one DB transaction that
  1. locks the paying customer row (serialises daily-limit checks), then
  2. locks the account rows in primary-key order (no deadlocks),
and re-validates everything *after* the locks are held.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Customer

from .models import Account, Beneficiary, LedgerEntry, Transaction
from .utils import is_valid_account_number, money


class BankingError(Exception):
    """Raised with a message that is safe to show to the customer."""


def start_of_today():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def daily_transferred(customer):
    """Amount already sent to *other* customers today."""
    total = (
        Transaction.objects.filter(
            kind=Transaction.Kind.TRANSFER, source_account__customer=customer, created_at__gte=start_of_today()
        )
        .exclude(destination_account__customer=customer)
        .aggregate(total=Sum("amount"))["total"]
    )
    return total or Decimal("0.00")


def daily_remaining(customer):
    return max(customer.daily_transfer_limit - daily_transferred(customer), Decimal("0.00"))


@transaction.atomic
def open_account(customer, account_type, nickname="", initial_deposit=Decimal("0")):
    Customer.objects.select_for_update().get(pk=customer.pk)
    open_count = customer.accounts.exclude(status=Account.Status.CLOSED).count()
    if open_count >= settings.MAX_ACCOUNTS_PER_CUSTOMER:
        raise BankingError(f"You can hold at most {settings.MAX_ACCOUNTS_PER_CUSTOMER} accounts.")
    account = Account.objects.create(customer=customer, account_type=account_type, nickname=nickname.strip())
    initial_deposit = money(initial_deposit or 0)
    if initial_deposit > 0:
        deposit(account.pk, initial_deposit, "Opening deposit (demo funds)", initiated_by=customer.user)
        account.refresh_from_db()
    return account


@transaction.atomic
def deposit(account_id, amount, description, initiated_by=None, kind=Transaction.Kind.DEPOSIT, demo_limit=False):
    amount = money(amount)
    if amount <= 0:
        raise BankingError("Amount must be greater than zero.")
    if demo_limit and amount > settings.DEMO_MAX_FUNDING:
        raise BankingError(f"Demo funding is limited to {settings.DEMO_MAX_FUNDING:,.0f} per request.")
    account = Account.objects.select_for_update().get(pk=account_id)
    if account.status != Account.Status.ACTIVE:
        raise BankingError("This account is not active.")
    account.balance += amount
    account.save(update_fields=["balance"])
    txn = Transaction.objects.create(
        kind=kind, amount=amount, currency=account.currency, destination_account=account,
        remarks=description[:100], initiated_by=initiated_by,
    )
    LedgerEntry.objects.create(
        transaction=txn, account=account, direction=LedgerEntry.Direction.CREDIT, amount=amount,
        balance_after=account.balance, description=description[:160],
    )
    return txn


@transaction.atomic
def execute_transfer(*, sender_id, receiver_id, amount, remarks, initiated_by, idempotency_key=None):
    amount = money(amount)
    if sender_id == receiver_id:
        raise BankingError("Choose two different accounts.")
    if amount < settings.TRANSFER_MIN:
        raise BankingError(f"The minimum transfer is {settings.TRANSFER_MIN:,.0f}.")
    if amount > settings.TRANSFER_MAX_PER_TXN:
        raise BankingError(f"The maximum per transfer is {settings.TRANSFER_MAX_PER_TXN:,.0f}.")

    # Lock order: paying customer, then both accounts by pk.
    sender_customer_id = Account.objects.values_list("customer_id", flat=True).get(pk=sender_id)
    customer = Customer.objects.select_for_update().get(pk=sender_customer_id)
    if idempotency_key:  # checked under the customer lock, so a double-submit cannot race
        existing = Transaction.objects.filter(idempotency_key=idempotency_key, initiated_by=initiated_by).first()
        if existing:
            return existing, False
    locked = {
        a.pk: a
        for a in Account.objects.select_for_update(of=("self",))
        .select_related("customer__user")
        .filter(pk__in=[sender_id, receiver_id])
        .order_by("pk")
    }
    if len(locked) != 2:
        raise BankingError("One of the accounts could not be found.")
    sender, receiver = locked[sender_id], locked[receiver_id]

    if sender.customer.user_id != initiated_by.pk:
        raise BankingError("You cannot transfer from this account.")
    if sender.status != Account.Status.ACTIVE:
        raise BankingError("The account you are paying from is not active.")
    if receiver.status != Account.Status.ACTIVE or receiver.currency != sender.currency:
        raise BankingError("The recipient account cannot accept this transfer.")
    if sender.balance < amount:
        raise BankingError("Insufficient balance for this transfer.")
    if receiver.customer_id != sender.customer_id:
        remaining = daily_remaining(customer)
        if amount > remaining:
            raise BankingError(
                f"This would exceed your daily transfer limit. You can still send {remaining:,.2f} today."
            )

    sender.balance -= amount
    receiver.balance += amount
    sender.save(update_fields=["balance"])
    receiver.save(update_fields=["balance"])
    txn = Transaction.objects.create(
        kind=Transaction.Kind.TRANSFER, amount=amount, currency=sender.currency, source_account=sender,
        destination_account=receiver, remarks=remarks[:100], initiated_by=initiated_by,
        idempotency_key=idempotency_key,
    )
    note = f" - {remarks}" if remarks else ""
    LedgerEntry.objects.create(
        transaction=txn, account=sender, direction=LedgerEntry.Direction.DEBIT, amount=amount,
        balance_after=sender.balance,
        description=f"Transfer to {receiver.customer.user.full_name} {receiver.masked_number}{note}"[:160],
    )
    LedgerEntry.objects.create(
        transaction=txn, account=receiver, direction=LedgerEntry.Direction.CREDIT, amount=amount,
        balance_after=receiver.balance,
        description=f"Transfer from {sender.customer.user.full_name} {sender.masked_number}{note}"[:160],
    )
    return txn, True


@transaction.atomic
def add_beneficiary(customer, account_number, nickname):
    if not is_valid_account_number(account_number):
        raise BankingError("That is not a valid account number.")
    target = Account.objects.select_related("customer__user").filter(
        account_number=account_number, status=Account.Status.ACTIVE
    ).first()
    if target is None:  # same message for unknown and inactive: no account enumeration
        raise BankingError("We could not verify this account number.")
    if target.customer_id == customer.pk:
        raise BankingError("That is one of your own accounts - you can transfer to it without adding it.")
    if Beneficiary.objects.filter(customer=customer, account=target).exists():
        raise BankingError("This beneficiary is already saved.")
    cooling = timedelta(minutes=settings.BENEFICIARY_COOLING_MINUTES)
    return Beneficiary.objects.create(
        customer=customer, account=target, nickname=nickname.strip(), active_from=timezone.now() + cooling
    )
