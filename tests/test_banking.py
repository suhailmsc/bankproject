import csv
import io
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from banking import services
from banking.models import Account, Beneficiary, LedgerEntry, Transaction
from banking.utils import csv_safe, is_valid_account_number, new_account_number

from .helpers import BankTestCase, make_account, make_customer


class AccountTests(BankTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.customer = make_customer()
        self.client.login(username=self.user.email, password=self.password)

    def test_open_account_with_demo_deposit(self):
        resp = self.client.post(reverse("banking:open_account"),
                                {"account_type": "savings", "nickname": "Rainy day", "initial_deposit": "2500.50"})
        account = Account.objects.get(customer=self.customer)
        self.assertRedirects(resp, reverse("banking:account_detail", args=[account.pk]))
        self.assertEqual(account.balance, Decimal("2500.50"))
        self.assertTrue(is_valid_account_number(account.account_number))
        self.assertEqual(LedgerEntry.objects.filter(account=account).count(), 1)

    @override_settings(MAX_ACCOUNTS_PER_CUSTOMER=2)
    def test_account_limit(self):
        make_account(self.customer)
        make_account(self.customer)
        resp = self.client.post(reverse("banking:open_account"), {"account_type": "current", "nickname": "", "initial_deposit": ""})
        self.assertContains(resp, "at most 2 accounts")

    def test_cannot_view_someone_elses_account(self):
        other_user, other = make_customer(email="other@example.com")
        theirs = make_account(other, "500")
        for name in ("banking:account_detail", "banking:fund_account"):
            self.assertEqual(self.client.get(reverse(name, args=[theirs.pk])).status_code, 404)

    @override_settings(DEMO_MODE=False)
    def test_demo_funding_disabled_outside_demo_mode(self):
        account = make_account(self.customer)
        self.assertEqual(self.client.get(reverse("banking:fund_account", args=[account.pk])).status_code, 404)

    def test_demo_funding_cap(self):
        account = make_account(self.customer)
        resp = self.client.post(reverse("banking:fund_account", args=[account.pk]), {"amount": "50001"})
        self.assertEqual(resp.status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.balance, 0)

    def test_negative_balance_blocked_by_database(self):
        from django.db import IntegrityError, transaction
        account = make_account(self.customer, "10")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.filter(pk=account.pk).update(balance=Decimal("-1"))

    def test_ledger_is_immutable(self):
        account = make_account(self.customer, "10")
        entry = LedgerEntry.objects.get(account=account)
        entry.description = "tampered"
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()

    def test_statement_csv_neutralises_formulas(self):
        account = make_account(self.customer, "100")
        services.deposit(account.pk, 5, "=HYPERLINK(\"http://evil\")", initiated_by=self.user)
        resp = self.client.get(reverse("banking:account_detail", args=[account.pk]) + "?export=csv")
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        self.assertTrue(any(r[2].startswith("'=") for r in rows))
        self.assertEqual(csv_safe("+1"), "'+1")


class TransferTests(BankTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.customer = make_customer()
        self.bob_user, self.bob = make_customer(email="bob@example.com", first="Bob", last="Iyer")
        self.mine = make_account(self.customer, "50000")
        self.mine2 = make_account(self.customer, "0", account_type="current")
        self.bobs = make_account(self.bob, "100")
        self.client.login(username=self.user.email, password=self.password)

    def _add_bob(self):
        return services.add_beneficiary(self.customer, self.bobs.account_number, "Bob")

    def _post_transfer(self, recipient, amount="1000", remarks="Rent"):
        return self.client.post(reverse("banking:transfer"), {
            "from_account": self.mine.pk, "recipient": recipient, "amount": amount, "remarks": remarks})

    def test_full_flow_review_confirm_receipt(self):
        ben = self._add_bob()
        self.assertRedirects(self._post_transfer(f"ben:{ben.pk}"), reverse("banking:transfer_review"))
        review = self.client.get(reverse("banking:transfer_review"))
        self.assertContains(review, "Bob Iyer")
        resp = self.client.post(reverse("banking:transfer_review"), {"password": self.password})
        txn = Transaction.objects.get(kind="transfer")
        self.assertRedirects(resp, reverse("banking:receipt", args=[txn.reference]))
        self.mine.refresh_from_db(); self.bobs.refresh_from_db()
        self.assertEqual(self.mine.balance, Decimal("49000.00"))
        self.assertEqual(self.bobs.balance, Decimal("1100.00"))
        self.assertEqual(txn.entries.count(), 2)
        self.assertEqual(self.client.get(reverse("banking:receipt", args=[txn.reference])).status_code, 200)

    def test_wrong_password_three_times_cancels(self):
        ben = self._add_bob()
        self._post_transfer(f"ben:{ben.pk}")
        for _ in range(3):
            self.client.post(reverse("banking:transfer_review"), {"password": "nope"})
        self.assertFalse(Transaction.objects.filter(kind="transfer").exists())
        self.assertRedirects(self.client.get(reverse("banking:transfer_review")), reverse("banking:transfer"))

    def test_double_submit_is_idempotent(self):
        txn1, created1 = services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="500",
                                                   remarks="", initiated_by=self.user, idempotency_key="abc")
        txn2, created2 = services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="500",
                                                   remarks="", initiated_by=self.user, idempotency_key="abc")
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(txn1.pk, txn2.pk)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.balance, Decimal("49500.00"))

    def test_insufficient_funds_rejected_everywhere(self):
        ben = self._add_bob()
        self.assertContains(self._post_transfer(f"ben:{ben.pk}", "60000"), "Insufficient balance")
        with self.assertRaises(services.BankingError):
            services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="60000",
                                      remarks="", initiated_by=self.user)

    def test_daily_limit_applies_to_other_people_but_not_own_accounts(self):
        self.customer.refresh_from_db()
        services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="20000", remarks="", initiated_by=self.user)
        with self.assertRaisesMessage(services.BankingError, "daily transfer limit"):
            services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="6000", remarks="", initiated_by=self.user)
        services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.mine2.pk, amount="6000", remarks="", initiated_by=self.user)

    def test_kyc_verified_gets_higher_limit(self):
        self.customer.kyc_status = "verified"
        self.customer.save()
        services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="30000", remarks="", initiated_by=self.user)

    def test_cannot_spend_from_someone_elses_account(self):
        with self.assertRaises(services.BankingError):
            services.execute_transfer(sender_id=self.bobs.pk, receiver_id=self.mine.pk, amount="10", remarks="", initiated_by=self.user)

    def test_frozen_accounts_cannot_send_or_receive(self):
        self.bobs.status = "frozen"; self.bobs.save()
        with self.assertRaises(services.BankingError):
            services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="10", remarks="", initiated_by=self.user)

    def test_beneficiary_validation_and_no_enumeration(self):
        with self.assertRaisesMessage(services.BankingError, "could not verify"):
            services.add_beneficiary(self.customer, new_account_number(), "Ghost")
        with self.assertRaisesMessage(services.BankingError, "own accounts"):
            services.add_beneficiary(self.customer, self.mine.account_number, "Me")
        self._add_bob()
        with self.assertRaisesMessage(services.BankingError, "already saved"):
            self._add_bob()

    @override_settings(BENEFICIARY_COOLING_MINUTES=30)
    def test_new_beneficiary_has_cooling_period(self):
        ben = self._add_bob()
        self.assertFalse(ben.is_usable)
        resp = self._post_transfer(f"ben:{ben.pk}")
        self.assertEqual(resp.status_code, 200)  # recipient not offered yet -> form error

    def test_remarks_reject_markup(self):
        ben = self._add_bob()
        self.assertEqual(self._post_transfer(f"ben:{ben.pk}", remarks="<script>").status_code, 200)

    def test_receipt_hidden_from_strangers(self):
        txn, _ = services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="10", remarks="", initiated_by=self.user)
        self.client.logout()
        stranger, _ = make_customer(email="eve@example.com")
        self.client.login(username=stranger.email, password=self.password)
        self.assertEqual(self.client.get(reverse("banking:receipt", args=[txn.reference])).status_code, 404)

    def test_money_is_conserved(self):
        before = sum(a.balance for a in Account.objects.all())
        services.execute_transfer(sender_id=self.mine.pk, receiver_id=self.bobs.pk, amount="123.45", remarks="", initiated_by=self.user)
        after = sum(a.balance for a in Account.objects.all())
        self.assertEqual(before, after)
