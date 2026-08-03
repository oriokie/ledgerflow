from django.apps import AppConfig


class IncomeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.income"
    label = "income"
    verbose_name = "Income"
