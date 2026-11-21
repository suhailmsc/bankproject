import re
from decimal import Decimal

from django import forms
from django.conf import settings

from .models import Account, Beneficiary
from .utils import is_valid_account_number, money

REMARKS_RE = re.compile(r"^[\w\s.,/&()@#'\-]*$")


class OpenAccountForm(forms.Form):
    account_type = forms.ChoiceField(choices=Account.Type.choices, label="Account type")
    nickname = forms.CharField(
        max_length=40, required=False, help_text="Optional, e.g. Rainy day fund.",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    initial_deposit = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=12, decimal_places=2, label="Opening balance (demo funds)",
        help_text="Fictional money to start with.",
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not settings.DEMO_MODE:
            del self.fields["initial_deposit"]

    def clean_nickname(self):
        return self.cleaned_data["nickname"].strip()

    def clean_initial_deposit(self):
        value = self.cleaned_data.get("initial_deposit") or Decimal("0")
        if value > settings.DEMO_MAX_FUNDING:
            raise forms.ValidationError(f"Demo funding is limited to {settings.DEMO_MAX_FUNDING:,.0f}.")
        return money(value)


class FundForm(forms.Form):
    amount = forms.DecimalField(
        min_value=Decimal("1"), max_digits=12, decimal_places=2, label="Amount (INR)",
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )


class TransferForm(forms.Form):
    from_account = forms.ModelChoiceField(queryset=Account.objects.none(), label="Pay from", empty_label=None)
    recipient = forms.ChoiceField(label="Pay to")
    amount = forms.DecimalField(
        min_value=Decimal("1"), max_digits=12, decimal_places=2, label="Amount (INR)",
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal", "autocomplete": "off"}),
    )
    remarks = forms.CharField(
        max_length=60, required=False, label="Remarks", help_text="Optional. Shown on both statements.",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def __init__(self, customer, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        accounts = customer.accounts.filter(status=Account.Status.ACTIVE)
        self.fields["from_account"].queryset = accounts
        self.fields["from_account"].label_from_instance = lambda a: f"{a.display_name} {a.masked_number}"
        own = [(f"own:{a.pk}", f"{a.display_name} {a.masked_number}") for a in accounts]
        bens = [
            (f"ben:{b.pk}", f"{b.nickname} {b.account.masked_number}")
            for b in customer.beneficiaries.select_related("account").all() if b.is_usable
        ]
        groups = []
        if own:
            groups.append(("My accounts", own))
        if bens:
            groups.append(("Beneficiaries", bens))
        self.fields["recipient"].choices = [("", "Select recipient")] + groups
        self._own = {f"own:{a.pk}": a for a in accounts}
        self._bens = {f"ben:{b.pk}": b for b in customer.beneficiaries.select_related("account").all() if b.is_usable}

    def clean_remarks(self):
        value = self.cleaned_data["remarks"].strip()
        if not REMARKS_RE.match(value):
            raise forms.ValidationError("Remarks can contain letters, numbers and basic punctuation only.")
        return value

    def clean_amount(self):
        value = money(self.cleaned_data["amount"])
        if value < settings.TRANSFER_MIN:
            raise forms.ValidationError(f"The minimum transfer is {settings.TRANSFER_MIN:,.0f}.")
        if value > settings.TRANSFER_MAX_PER_TXN:
            raise forms.ValidationError(f"The maximum per transfer is {settings.TRANSFER_MAX_PER_TXN:,.0f}.")
        return value

    def clean(self):
        cleaned = super().clean()
        key, source = cleaned.get("recipient"), cleaned.get("from_account")
        if not key or source is None:
            return cleaned
        if key in self._own:
            target = self._own[key]
        elif key in self._bens:
            target = self._bens[key].account
        else:
            self.add_error("recipient", "Choose a valid recipient.")
            return cleaned
        if target.pk == source.pk:
            self.add_error("recipient", "Choose a different account to pay.")
        cleaned["target_account"] = target
        amount = cleaned.get("amount")
        if amount is not None and amount > source.balance:
            self.add_error("amount", "Insufficient balance in the selected account.")
        return cleaned


class ConfirmTransferForm(forms.Form):
    password = forms.CharField(
        label="Confirm with your password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "autofocus": True}),
    )


class BeneficiaryForm(forms.Form):
    nickname = forms.CharField(max_length=40, widget=forms.TextInput(attrs={"autocomplete": "off"}))
    account_number = forms.CharField(
        max_length=12, min_length=12, label="Account number",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )
    confirm_account_number = forms.CharField(
        max_length=12, min_length=12, label="Re-enter account number",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )

    def clean_account_number(self):
        value = self.cleaned_data["account_number"].strip()
        if not is_valid_account_number(value):
            raise forms.ValidationError("That is not a valid account number.")
        return value

    def clean(self):
        cleaned = super().clean()
        a, b = cleaned.get("account_number"), cleaned.get("confirm_account_number")
        if a and b and a != b:
            self.add_error("confirm_account_number", "Account numbers do not match.")
        return cleaned
