import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.models import Customer

from .utils import new_account_number


def generate_account_number():
    while True:
        number = new_account_number()
        if not Account.objects.filter(account_number=number).exists():
            return number


def generate_reference():
    return "NSB" + timezone.now().strftime("%y%m%d") + secrets.token_hex(4).upper()


class Account(models.Model):
    class Type(models.TextChoices):
        SAVINGS = "savings", "Savings account"
        CURRENT = "current", "Current account"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FROZEN = "frozen", "Frozen"
        CLOSED = "closed", "Closed"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="accounts")
    account_number = models.CharField(max_length=12, unique=True, default=generate_account_number, editable=False)
    account_type = models.CharField(max_length=10, choices=Type.choices, default=Type.SAVINGS)
    nickname = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=3, default="INR", editable=False)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["opened_at", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="account_balance_not_negative"),
        ]

    def __str__(self):
        return f"{self.account_number} ({self.get_account_type_display()})"

    @property
    def masked_number(self):
        return "\u2022\u2022\u2022\u2022 " + self.account_number[-4:]

    @property
    def display_name(self):
        return self.nickname or self.get_account_type_display()

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


class Transaction(models.Model):
    class Kind(models.TextChoices):
        TRANSFER = "transfer", "Transfer"
        DEPOSIT = "deposit", "Deposit"
        ADJUSTMENT = "adjustment", "Staff adjustment"

    class Status(models.TextChoices):
        POSTED = "posted", "Completed"
        REVERSED = "reversed", "Reversed"

    reference = models.CharField(max_length=20, unique=True, default=generate_reference, editable=False)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.POSTED)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    source_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="outgoing")
    destination_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming")
    remarks = models.CharField(max_length=100, blank=True)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    idempotency_key = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="transaction_amount_positive")]

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency}"


class LedgerEntry(models.Model):
    """One line on one account's statement. Immutable once written."""

    class Direction(models.TextChoices):
        DEBIT = "DR", "Debit"
        CREDIT = "CR", "Credit"

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    direction = models.CharField(max_length=2, choices=Direction.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=160)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name_plural = "ledger entries"
        indexes = [models.Index(fields=["account", "-created_at"])]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="ledger_amount_positive")]

    def __str__(self):
        return f"{self.direction} {self.amount} on {self.account.account_number}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Ledger entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Ledger entries cannot be deleted.")

    @property
    def signed_amount(self):
        return self.amount if self.direction == self.Direction.CREDIT else -self.amount


class Beneficiary(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="beneficiaries")
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="+")
    nickname = models.CharField(max_length=40)
    added_at = models.DateTimeField(default=timezone.now)
    active_from = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["nickname"]
        verbose_name_plural = "beneficiaries"
        constraints = [models.UniqueConstraint(fields=["customer", "account"], name="unique_beneficiary_per_customer")]

    def __str__(self):
        return f"{self.nickname} -> {self.account.account_number}"

    @property
    def is_usable(self):
        return self.active_from <= timezone.now() and self.account.is_active
