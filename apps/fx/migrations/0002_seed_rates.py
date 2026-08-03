from django.db import migrations
from django.utils import timezone
from decimal import Decimal

# Approximate USD-based reference rates so multi-currency conversion works out
# of the box. Replaced by live ingestion (services.refresh_rates) in production.
SEED = {
    "EUR": "0.92", "GBP": "0.79", "JPY": "157.0", "CHF": "0.89", "CAD": "1.37",
    "AUD": "1.51", "NZD": "1.64", "CNY": "7.24", "HKD": "7.81", "SGD": "1.35",
    "INR": "83.4", "KES": "129.0", "NGN": "1600.0", "ZAR": "18.4", "GHS": "15.3",
    "UGX": "3700.0", "TZS": "2600.0", "EGP": "48.5", "AED": "3.67", "SAR": "3.75",
    "BRL": "5.44", "MXN": "18.6", "ARS": "930.0", "SEK": "10.6", "NOK": "10.8",
    "DKK": "6.87", "PLN": "3.95", "CZK": "23.3", "TRY": "33.0", "KRW": "1380.0",
    "THB": "36.5", "IDR": "16200.0", "MYR": "4.68", "PHP": "58.4",
    "KWD": "0.307", "BHD": "0.377",
}


def seed(apps, schema_editor):
    ExchangeRate = apps.get_model("fx", "ExchangeRate")
    now = timezone.now()
    for quote, rate in SEED.items():
        ExchangeRate.objects.get_or_create(
            base_currency="USD", quote_currency=quote, as_of=now, source="seed",
            defaults={"rate": Decimal(rate)},
        )


def unseed(apps, schema_editor):
    apps.get_model("fx", "ExchangeRate").objects.filter(source="seed").delete()


class Migration(migrations.Migration):
    dependencies = [("fx", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
