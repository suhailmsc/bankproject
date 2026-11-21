from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError


def is_staff_user(user):
    return bool(
        user.is_authenticated and user.is_active and user.is_staff and getattr(user, "kind", None) == "staff"
    )


class StaffAuthenticationForm(AdminAuthenticationForm):
    """Console login: bank customers are rejected even with a correct password."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if getattr(user, "kind", None) != "staff":
            raise ValidationError(self.error_messages["invalid_login"], code="invalid_login",
                                  params={"username": self.username_field.verbose_name})


class StaffAdminSite(AdminSite):
    site_header = "Northstar Bank - Staff Console"
    site_title = "Northstar Staff Console"
    index_title = "Operations"
    login_form = StaffAuthenticationForm

    def has_permission(self, request):
        return is_staff_user(request.user)
