from django.test import override_settings
from django.urls import reverse

from banking.templatetags.money import inr

from .helpers import BankTestCase, make_account, make_customer


class SmokeTests(BankTestCase):
    def test_indian_grouping(self):
        self.assertEqual(inr(1234567.5), "\u20b912,34,567.50")
        self.assertEqual(inr(999), "\u20b9999.00")
        self.assertEqual(inr(100000), "\u20b91,00,000.00")

    def test_public_pages(self):
        for name in ("home", "accounts:login", "accounts:register", "accounts:password_reset"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_customer_pages_render(self):
        user, customer = make_customer()
        acct = make_account(customer, "1000")
        self.client.login(username=user.email, password=self.password)
        urls = [reverse(n) for n in ("banking:dashboard", "banking:open_account", "banking:transfer", "banking:beneficiaries",
                                      "banking:beneficiary_add", "banking:activity", "accounts:profile", "accounts:password_change")]
        urls += [reverse("banking:account_detail", args=[acct.pk]), reverse("banking:fund_account", args=[acct.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_error_pages(self):
        self.assertEqual(self.client.get("/nope/").status_code, 404)
