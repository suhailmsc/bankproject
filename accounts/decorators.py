from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def customer_required(view):
    """Signed-in *customer* only. Staff are sent to the staff console instead."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.kind != "customer":
            return redirect("admin:index")
        return view(request, *args, **kwargs)

    return wrapper


def verified_required(view):
    """Customer with a verified email (when the setting is on) - for money-moving actions."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.REQUIRE_EMAIL_VERIFICATION and not request.user.email_verified:
            messages.warning(request, "Please verify your email address before using this feature.")
            return redirect("accounts:profile")
        return view(request, *args, **kwargs)

    return customer_required(wrapper)
