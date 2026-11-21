from axes.signals import user_locked_out
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .audit import log_event


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log_event("login.success", request, user=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    attempted = (credentials or {}).get("username") or (credentials or {}).get("email") or ""
    log_event("login.failed", request, email=str(attempted)[:254])


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log_event("logout", request, user=user)


@receiver(user_locked_out)
def on_locked_out(sender, request=None, username=None, **kwargs):
    log_event("login.locked", request, email=str(username or "")[:254])
