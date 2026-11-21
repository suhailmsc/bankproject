import secrets
from datetime import date

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        """Creates a *customer*. Customers can never be staff."""
        extra["kind"] = "customer"
        extra["is_staff"] = False
        extra["is_superuser"] = False
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(kind="staff", is_staff=True, is_superuser=True)
        return self._create(email, password, **extra)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractBaseUser, PermissionsMixin):
    """
    One identity table, two strictly separated populations.

    * kind=customer: bank customers. Portal only. is_staff/is_superuser are
      forced to False in save() AND enforced by a database CHECK constraint.
    * kind=staff: bank employees. Staff console only (never the customer portal).
    """

    class Kind(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STAFF = "staff", "Staff"

    email = models.EmailField("email address", unique=True)
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CUSTOMER, db_index=True)
    is_active = models.BooleanField(default=True, help_text="Untick to block sign-in without deleting data.")
    is_staff = models.BooleanField(default=False, help_text="Can sign in to the staff console (staff kind only).")
    email_verified_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="staff") | Q(is_staff=False, is_superuser=False),
                name="customers_are_never_staff",
            )
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if self.kind != self.Kind.STAFF:
            self.is_staff = False
            self.is_superuser = False
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name

    @property
    def is_customer(self):
        return self.kind == self.Kind.CUSTOMER

    @property
    def email_verified(self):
        return self.email_verified_at is not None


def generate_customer_id():
    while True:
        value = str(secrets.randbelow(9 * 10**9) + 10**9)  # 10 digits, no leading zero
        if not Customer.objects.filter(customer_id=value).exists():
            return value


phone_validator = RegexValidator(r"^[6-9]\d{9}$", "Enter a 10-digit Indian mobile number.")
pin_validator = RegexValidator(r"^[1-9]\d{5}$", "Enter a valid 6-digit PIN code.")


class Customer(models.Model):
    class KYC(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer")
    customer_id = models.CharField(max_length=10, unique=True, default=generate_customer_id, editable=False)
    phone = models.CharField(max_length=10, validators=[phone_validator])
    date_of_birth = models.DateField()
    address_line = models.CharField(max_length=160)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    postal_code = models.CharField(max_length=6, validators=[pin_validator])
    kyc_status = models.CharField(max_length=10, choices=KYC.choices, default=KYC.PENDING, db_index=True)
    kyc_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.full_name} ({self.customer_id})"

    @property
    def is_kyc_verified(self):
        return self.kyc_status == self.KYC.VERIFIED

    @property
    def daily_transfer_limit(self):
        return settings.DAILY_LIMIT_KYC_VERIFIED if self.is_kyc_verified else settings.DAILY_LIMIT_KYC_PENDING

    @property
    def age(self):
        today = date.today()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
