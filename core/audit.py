import logging

from django.conf import settings

logger = logging.getLogger("banking.audit")


def client_ip(request):
    """Client IP, honouring X-Forwarded-For only when we know how many proxies we sit behind."""
    if request is None:
        return None
    remote = request.META.get("REMOTE_ADDR")
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if proxies and forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= proxies:
            return hops[-proxies]
    return remote


def log_event(event, request=None, user=None, email="", **metadata):
    from .models import AuditLog

    if user is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            user = request.user
    entry = AuditLog.objects.create(
        user=user if (user is not None and user.pk) else None,
        actor_email=(email or (user.email if user is not None else ""))[:254],
        event=event,
        ip_address=client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request is not None else ""),
        metadata=metadata,
    )
    logger.info("event=%s user=%s ip=%s meta=%s", event, entry.actor_email, entry.ip_address, metadata)
    return entry
