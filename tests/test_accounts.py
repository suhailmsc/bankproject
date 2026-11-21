from datetime import date

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from accounts.models import Customer, User
from accounts.tokens import make_verification_token

from .helpers import BankTestCase, make_customer

VALID = {
    "first_name": "Ravi", "last_name": "Menon", "email": "Ravi@Example.com", "phone": "+91 98765 43210",
    "date_of_birth": "1992-04-12", "address_line": "12 Beach Road", "city": "Kozhikode", "state": "Kerala",
    "postal_code": "673001", "password1": "Tr1cky!Harbour#9", "password2": "Tr1cky!Harbour#9", "accept_terms": "on",
}


class RegistrationTests(BankTestCase):
    def test_register_creates_customer_not_staff_and_sends_verification(self):
        resp = self.client.post(reverse("accounts:register"), VALID)
        self.assertRedirects(resp, reverse("banking:dashboard"))
        user = User.objects.get(email="ravi@example.com")
        self.assertEqual(user.kind, "customer")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.password.startswith("argon2"))
        self.assertEqual(user.customer.phone, "9876543210")
        self.assertEqual(len(user.customer.customer_id), 10)
        self.assertEqual(len(mail.outbox), 1)

    def test_rejects_minor_weak_password_and_duplicate_email(self):
        too_young = dict(VALID, date_of_birth=str(date.today().replace(year=date.today().year - 10)))
        self.assertContains(self.client.post(reverse("accounts:register"), too_young), "at least 18")
        weak = dict(VALID, password1="password1234", password2="password1234")
        self.assertEqual(self.client.post(reverse("accounts:register"), weak).status_code, 200)
        self.assertFalse(User.objects.filter(email="ravi@example.com").exists())
        make_customer(email="ravi@example.com")
        self.assertContains(self.client.post(reverse("accounts:register"), VALID), "could not use this email")

    def test_email_verification_link(self):
        user, _ = make_customer(verified=False)
        self.client.get(reverse("accounts:verify_email", args=[make_verification_token(user)]))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.client.get(reverse("accounts:verify_email", args=["garbage"]))

    def test_login_is_case_insensitive_and_logout_is_post_only(self):
        make_customer(email="asha@example.com")
        resp = self.client.post(reverse("accounts:login"), {"username": "ASHA@Example.com", "password": self.password})
        self.assertRedirects(resp, reverse("banking:dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_registration_is_rate_limited(self):
        for _ in range(10):
            self.client.post(reverse("accounts:register"), dict(VALID, email="x"))
        self.assertEqual(self.client.post(reverse("accounts:register"), VALID).status_code, 429)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_unverified_customer_cannot_open_account_or_transfer(self):
        user, _ = make_customer(verified=False)
        self.client.login(username=user.email, password=self.password)
        for name in ("banking:open_account", "banking:transfer"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("accounts:profile"), fetch_redirect_response=False)
