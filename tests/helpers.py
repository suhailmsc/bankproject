from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from accounts.models import Customer, User
from banking import services
from banking.models import Account


def make_customer(email="asha@example.com", first="Asha", last="Nair", verified=True, kyc=False, password="Str0ng!Passw0rd"):
    user = User.objects.create_user(email=email, password=password, first_name=first, last_name=last)
    if verified:
        from django.utils import timezone
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
    customer = Customer.objects.create(
        user=user, phone="9876543210", date_of_birth=date(1990, 1, 1), address_line="1 MG Road",
        city="Kochi", state="Kerala", postal_code="682001",
        kyc_status=Customer.KYC.VERIFIED if kyc else Customer.KYC.PENDING,
    )
    return user, customer


def make_account(customer, balance="0", **kw):
    account = Account.objects.create(customer=customer, **kw)
    if Decimal(balance) > 0:
        services.deposit(account.pk, Decimal(balance), "Seed funds", initiated_by=customer.user)
        account.refresh_from_db()
    return account


@override_settings(REQUIRE_EMAIL_VERIFICATION=False, DEMO_MODE=True, SECURE_SSL_REDIRECT=False,
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class BankTestCase(TestCase):
    password = "Str0ng!Passw0rd"

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
