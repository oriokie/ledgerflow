from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    label = "billing"

    def ready(self):
        # register signal handlers / provider adapters on startup
        from . import providers  # noqa: F401
