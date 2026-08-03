from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.intelligence"
    label = "intelligence"
    verbose_name = "AI & Automation"

    def ready(self):
        from . import signals  # noqa: F401  (registers the auto-categorization pipeline)
