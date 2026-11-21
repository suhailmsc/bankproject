from django import forms
from django.contrib import admin, messages
from django.contrib.auth import password_validation
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.http import Http404
from django.utils import timezone

from core.audit import log_event

from .models import Customer, User


class StaffCreationForm(forms.ModelForm):
    """Console can only create staff. Customers register themselves on the portal."""

    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")

    def clean_password2(self):
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("The two passwords do not match.")
        password_validation.validate_password(p2, User(email=self.cleaned_data.get("email", "")))
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.kind = User.Kind.STAFF
        user.is_staff = True
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class StaffChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = StaffChangeForm
    add_form = StaffCreationForm
    ordering = ("email",)
    list_display = ("email", "full_name", "kind", "is_active", "last_login")
    list_filter = ("kind", "is_active")
    search_fields = ("email", "first_name", "last_name")
    filter_horizontal = ("groups", "user_permissions")

    staff_fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Access", {"fields": ("kind", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    customer_fieldsets = (
        (None, {"fields": ("email",)}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Access", {"fields": ("kind", "is_active", "email_verified_at")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "first_name", "last_name", "password1", "password2")}),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return self.customer_fieldsets if obj.kind == User.Kind.CUSTOMER else self.staff_fieldsets

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        if obj.kind == User.Kind.CUSTOMER:
            # Support staff may block a customer but never edit identity or credentials.
            return ("email", "first_name", "last_name", "kind", "email_verified_at", "last_login", "date_joined")
        return ("kind", "last_login", "date_joined")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and (obj is None or obj.kind == User.Kind.STAFF)

    def user_change_password(self, request, id, form_url=""):
        target = self.get_object(request, id)
        if target is not None and target.kind == User.Kind.CUSTOMER:
            raise Http404  # staff can never set a customer's password
        return super().user_change_password(request, id, form_url)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log_event("admin.action", request, user=request.user, action="user.saved", target=obj.email, change=change)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_id", "user", "phone", "city", "kyc_status", "created_at")
    list_filter = ("kyc_status", "state")
    search_fields = ("customer_id", "user__email", "user__first_name", "user__last_name", "phone")
    readonly_fields = ("user", "customer_id", "phone", "date_of_birth", "address_line", "city", "state",
                       "postal_code", "created_at", "kyc_verified_at")
    fields = readonly_fields[:1] + ("customer_id", "kyc_status", "kyc_verified_at", "phone", "date_of_birth",
                                    "address_line", "city", "state", "postal_code", "created_at")
    actions = ["mark_verified", "mark_rejected"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Mark selected customers KYC verified")
    def mark_verified(self, request, queryset):
        count = 0
        for customer in queryset:
            customer.kyc_status = Customer.KYC.VERIFIED
            customer.kyc_verified_at = timezone.now()
            customer.save(update_fields=["kyc_status", "kyc_verified_at"])
            log_event("admin.action", request, user=request.user, action="kyc.verified", target=customer.customer_id)
            count += 1
        self.message_user(request, f"{count} customer(s) marked KYC verified.", messages.SUCCESS)

    @admin.action(description="Mark selected customers KYC rejected")
    def mark_rejected(self, request, queryset):
        for customer in queryset:
            customer.kyc_status = Customer.KYC.REJECTED
            customer.kyc_verified_at = None
            customer.save(update_fields=["kyc_status", "kyc_verified_at"])
            log_event("admin.action", request, user=request.user, action="kyc.rejected", target=customer.customer_id)
        self.message_user(request, "Selected customers marked KYC rejected.", messages.WARNING)
