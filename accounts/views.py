from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_event
from core.ratelimit import ratelimit

from .decorators import customer_required
from .forms import CustomerLoginForm, CustomerPasswordResetForm, RegistrationForm
from .models import User
from .tokens import make_verification_token, read_verification_token


def send_verification_email(user):
    link = settings.SITE_URL + reverse("accounts:verify_email", args=[make_verification_token(user)])
    body = render_to_string("accounts/email/verify_email.txt", {"user": user, "link": link})
    send_mail(f"Verify your {settings.BANK_NAME} email address", body, settings.DEFAULT_FROM_EMAIL, [user.email])


@ratelimit("register", limit=10, period=3600)
def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_event("register", request, user=user)
        send_verification_email(user)
        login(request, user, backend="accounts.backends.EmailBackend")
        messages.success(request, "Welcome to Northstar Bank. Check your inbox to verify your email address.")
        return redirect("banking:dashboard")
    return render(request, "accounts/register.html", {"form": form})


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = CustomerLoginForm
    redirect_authenticated_user = True


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        response = super().form_valid(form)  # keeps this session alive, invalidates others
        log_event("password.changed", self.request)
        messages.success(self.request, "Your password has been changed.")
        return response


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/email/password_reset_email.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    form_class = CustomerPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")

    @classmethod
    def as_view(cls, **initkwargs):
        return ratelimit("pwreset", limit=5, period=3600)(super().as_view(**initkwargs))


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_event("password.reset", self.request, user=form.user)
        return response


def verify_email(request, token):
    payload = read_verification_token(token)
    user = User.objects.filter(pk=payload["uid"], email=payload["email"]).first() if payload else None
    if user is None:
        messages.error(request, "This verification link is invalid or has expired.")
        return redirect("home")
    if not user.email_verified:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        log_event("email.verified", request, user=user)
    messages.success(request, "Your email address is verified.")
    return redirect("banking:dashboard" if request.user.is_authenticated else "accounts:login")


@customer_required
@require_POST
@ratelimit("resend-verify", limit=5, period=3600)
def resend_verification(request):
    if not request.user.email_verified:
        send_verification_email(request.user)
        messages.info(request, "We sent you a new verification link.")
    return redirect("accounts:profile")


@customer_required
def profile(request):
    return render(request, "accounts/profile.html", {"customer": request.user.customer})
