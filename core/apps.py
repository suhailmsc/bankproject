from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class StaffAdminConfig(admin_apps.AdminConfig):
    """Swap Django's default admin site for the staff-only console."""

    default_site = "core.admin_site.StaffAdminSite"
    default = False


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import signals  # noqa: F401
