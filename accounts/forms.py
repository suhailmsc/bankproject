import re
from datetime import date

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Customer, User, phone_validator, pin_validator

INDIAN_STATES = [
    "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra",
    "Odisha", "Punjab", "Rajasthan", "Tamil Nadu", "Telangana", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Other",
]


class CustomerLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.kind != User.Kind.CUSTOMER:
            # Staff credentials do not work on the customer portal.
            raise ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
                params={"username": self.username_field.verbose_name},
            )


class RegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=60, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=60, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(
        label="Mobile number", max_length=15, help_text="10-digit Indian mobile number.",
        widget=forms.TextInput(attrs={"autocomplete": "tel-national", "inputmode": "numeric"}),
    )
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "autocomplete": "bday"}),
        help_text=f"You must be at least {settings.MIN_CUSTOMER_AGE}.",
    )
    address_line = forms.CharField(label="Address", max_length=160, widget=forms.TextInput(attrs={"autocomplete": "street-address"}))
    city = forms.CharField(max_length=80, widget=forms.TextInput(attrs={"autocomplete": "address-level2"}))
    state = forms.ChoiceField(choices=[("", "Select state")] + [(s, s) for s in INDIAN_STATES])
    postal_code = forms.CharField(
        label="PIN code", max_length=6,
        widget=forms.TextInput(attrs={"autocomplete": "postal-code", "inputmode": "numeric"}),
    )
    password1 = forms.CharField(
        label="Password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    accept_terms = forms.BooleanField(
        label="I understand this is a demo bank with fictional money and I accept the terms of use."
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("We could not use this email. If you already registered, sign in or reset your password.")
        return email

    def clean_phone(self):
        digits = re.sub(r"[\s-]", "", self.cleaned_data["phone"])
        digits = re.sub(r"^(\+91|91|0)(?=\d{10}$)", "", digits)
        phone_validator(digits)
        return digits

    def clean_postal_code(self):
        value = self.cleaned_data["postal_code"].strip()
        pin_validator(value)
        return value

    def clean_date_of_birth(self):
        dob = self.cleaned_data["date_of_birth"]
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < settings.MIN_CUSTOMER_AGE:
            raise ValidationError(f"You must be at least {settings.MIN_CUSTOMER_AGE} years old to open an account.")
        if age > 110:
            raise ValidationError("Please enter a valid date of birth.")
        return dob

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            candidate = User(email=cleaned.get("email", ""), first_name=cleaned.get("first_name", ""),
                             last_name=cleaned.get("last_name", ""))
            try:
                password_validation.validate_password(p1, candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        user = User.objects.create_user(
            email=d["email"], password=d["password1"], first_name=d["first_name"].strip(), last_name=d["last_name"].strip()
        )
        Customer.objects.create(
            user=user, phone=d["phone"], date_of_birth=d["date_of_birth"], address_line=d["address_line"].strip(),
            city=d["city"].strip(), state=d["state"], postal_code=d["postal_code"],
        )
        return user


class CustomerPasswordResetForm(PasswordResetForm):
    """Password reset on the customer portal only ever applies to customers."""

    def get_users(self, email):
        return (u for u in super().get_users(email) if u.kind == User.Kind.CUSTOMER)
