from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only security/business audit trail."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    actor_email = models.CharField(max_length=254, blank=True)
    event = models.CharField(max_length=60, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["user", "event", "-created_at"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.event} {self.actor_email}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit log entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries cannot be deleted.")

    @property
    def label(self):
        return EVENT_LABELS.get(self.event, self.event)


EVENT_LABELS = {
    "login.success": "Signed in",
    "login.failed": "Failed sign-in attempt",
    "login.locked": "Sign-in locked after repeated failures",
    "logout": "Signed out",
    "register": "Customer registered",
    "email.verified": "Email verified",
    "password.changed": "Password changed",
    "password.reset": "Password reset",
    "account.opened": "Account opened",
    "account.funded": "Demo funds added",
    "transfer.posted": "Transfer completed",
    "transfer.reauth_failed": "Transfer confirmation failed",
    "beneficiary.added": "Beneficiary added",
    "beneficiary.removed": "Beneficiary removed",
    "admin.blocked": "Blocked attempt to reach staff console",
    "admin.action": "Staff action",
}
