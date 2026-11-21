from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone

from core.audit import log_event

from . import services
from .models import Account, Beneficiary, LedgerEntry, Transaction


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("account_number", "customer", "account_type", "status", "balance", "opened_at")
    list_filter = ("status", "account_type")
    search_fields = ("account_number", "customer__customer_id", "customer__user__email", "nickname")
    # Balances change only through the ledger - never by editing a field here.
    readonly_fields = ("customer", "account_number", "account_type", "currency", "balance", "opened_at", "closed_at")
    fields = ("customer", "account_number", "account_type", "nickname", "currency", "balance", "status", "opened_at", "closed_at")
    actions = ["freeze", "unfreeze", "close_zero_balance", "credit_demo_funds"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _audit(self, request, action, account):
        log_event("admin.action", request, user=request.user, action=action, target=account.account_number)

    @admin.action(description="Freeze selected accounts")
    def freeze(self, request, queryset):
        for account in queryset.filter(status=Account.Status.ACTIVE):
            account.status = Account.Status.FROZEN
            account.save(update_fields=["status"])
            self._audit(request, "account.frozen", account)
        self.message_user(request, "Selected active accounts frozen.", messages.WARNING)

    @admin.action(description="Unfreeze selected accounts")
    def unfreeze(self, request, queryset):
        for account in queryset.filter(status=Account.Status.FROZEN):
            account.status = Account.Status.ACTIVE
            account.save(update_fields=["status"])
            self._audit(request, "account.unfrozen", account)
        self.message_user(request, "Selected frozen accounts reactivated.", messages.SUCCESS)

    @admin.action(description="Close selected accounts (only if balance is zero)")
    def close_zero_balance(self, request, queryset):
        closed = 0
        for account in queryset.exclude(status=Account.Status.CLOSED).filter(balance=0):
            account.status = Account.Status.CLOSED
            account.closed_at = timezone.now()
            account.save(update_fields=["status", "closed_at"])
            self._audit(request, "account.closed", account)
            closed += 1
        self.message_user(request, f"{closed} account(s) closed. Accounts with a balance were skipped.")

    @admin.action(description="Credit 10,000 demo funds (superusers, demo mode only)")
    def credit_demo_funds(self, request, queryset):
        if not (settings.DEMO_MODE and request.user.is_superuser):
            self.message_user(request, "Only superusers can do this, and only in demo mode.", messages.ERROR)
            return
        for account in queryset.filter(status=Account.Status.ACTIVE):
            services.deposit(account.pk, 10000, "Staff demo credit", initiated_by=request.user,
                             kind=Transaction.Kind.ADJUSTMENT)
            self._audit(request, "account.demo_credit", account)
        self.message_user(request, "Demo funds credited through the ledger.", messages.SUCCESS)


class LedgerInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False
    readonly_fields = ("account", "direction", "amount", "balance_after", "description", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Transaction)
class TransactionAdmin(ReadOnlyAdmin):
    list_display = ("reference", "kind", "amount", "source_account", "destination_account", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("reference", "source_account__account_number", "destination_account__account_number")
    date_hierarchy = "created_at"
    inlines = [LedgerInline]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "account", "direction", "amount", "balance_after", "description")
    list_filter = ("direction",)
    search_fields = ("account__account_number", "transaction__reference")
    date_hierarchy = "created_at"


@admin.register(Beneficiary)
class BeneficiaryAdmin(ReadOnlyAdmin):
    list_display = ("nickname", "customer", "account", "added_at")
    search_fields = ("nickname", "customer__customer_id", "account__account_number")
