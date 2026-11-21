import logging

from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse

from .audit import log_event

security_logger = logging.getLogger("django.security")


class HealthCheckMiddleware:
    """
    /healthz (liveness) and /readyz (DB reachable) for load balancers.

    Runs before host validation and the HTTPS redirect, because ALB/ECS health
    checks hit the container IP over plain HTTP.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            return HttpResponse("ok", content_type="text/plain")
        if request.path == "/readyz":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except Exception:  # noqa: BLE001
                return HttpResponse("database unavailable", status=503, content_type="text/plain")
            return HttpResponse("ready", content_type="text/plain")
        return self.get_response(request)


class AdminIsolationMiddleware:
    """
    Customers must never reach the staff console, even by guessing the URL.

    A signed-in *customer* hitting the console prefix gets a plain 404 (the
    console's existence is not confirmed) and the attempt is audited.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = "/" + settings.ADMIN_URL

    def __call__(self, request):
        if request.path.startswith(self.prefix):
            user = request.user
            if user.is_authenticated and getattr(user, "kind", None) != "staff":
                log_event("admin.blocked", request, user=user, path=request.path)
                security_logger.warning("Customer %s tried to reach staff console", user.pk)
                raise Http404
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """CSP, permissions policy and no-store caching for authenticated pages."""

    CSP = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = "/" + settings.ADMIN_URL

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        if not request.path.startswith(self.prefix):
            response.setdefault("Content-Security-Policy", self.CSP)
        if request.user.is_authenticated or request.method == "POST":
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"
        return response
