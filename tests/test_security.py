from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from core.models import AuditLog

from .helpers import BankTestCase, make_customer

CONSOLE = "/" + settings.ADMIN_URL


class AdminSeparationTests(BankTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.customer = make_customer()
        self.staff = User.objects.create_superuser("ops@bank.example", self.password, first_name="Ops", last_name="Lead")

    def test_customer_cannot_sign_in_to_staff_console(self):
        resp = self.client.post(CONSOLE + "login/", {"username": self.user.email, "password": self.password})
        self.assertEqual(resp.status_code, 200)  # form re-rendered with an error
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_customer_session_gets_404_on_console(self):
        self.client.login(username=self.user.email, password=self.password)
        for path in (CONSOLE, CONSOLE + "accounts/user/", CONSOLE + "login/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertTrue(AuditLog.objects.filter(event="admin.blocked", user=self.user).exists())

    def test_customer_cannot_be_made_staff(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff or self.user.is_superuser)

    def test_database_constraint_blocks_staff_customer(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.user.pk).update(is_staff=True)

    def test_staff_cannot_sign_in_to_customer_portal(self):
        resp = self.client.post(reverse("accounts:login"), {"username": self.staff.email, "password": self.password})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_can_use_console_and_is_redirected_from_portal(self):
        self.client.login(username=self.staff.email, password=self.password)
        self.assertEqual(self.client.get(CONSOLE).status_code, 200)
        resp = self.client.get(reverse("banking:dashboard"))
        self.assertRedirects(resp, reverse("admin:index"), fetch_redirect_response=False)

    def test_staff_cannot_set_customer_password(self):
        self.client.login(username=self.staff.email, password=self.password)
        resp = self.client.get(f"{CONSOLE}accounts/user/{self.user.pk}/password/")
        self.assertEqual(resp.status_code, 404)

    def test_default_admin_path_is_not_exposed(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_password_reset_ignores_staff_accounts(self):
        from django.core import mail
        self.client.post(reverse("accounts:password_reset"), {"email": self.staff.email})
        self.assertEqual(len(mail.outbox), 0)
        self.client.post(reverse("accounts:password_reset"), {"email": self.user.email})
        self.assertEqual(len(mail.outbox), 1)


class HealthAndHeadersTests(BankTestCase):
    @override_settings(ALLOWED_HOSTS=["bank.example"])
    def test_health_checks_skip_host_validation(self):
        self.assertEqual(self.client.get("/healthz", HTTP_HOST="10.0.3.7").status_code, 200)
        self.assertEqual(self.client.get("/readyz", HTTP_HOST="10.0.3.7").status_code, 200)

    def test_security_headers_and_no_store(self):
        user, _ = make_customer()
        self.client.login(username=user.email, password=self.password)
        resp = self.client.get(reverse("banking:dashboard"))
        self.assertIn("default-src 'self'", resp["Content-Security-Policy"])
        self.assertIn("no-store", resp["Cache-Control"])
        self.assertEqual(resp["X-Frame-Options"], "DENY")

    def test_customer_pages_require_login(self):
        for name in ("banking:dashboard", "banking:transfer", "banking:beneficiaries", "accounts:profile"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302)
            self.assertIn(reverse("accounts:login"), resp["Location"])
