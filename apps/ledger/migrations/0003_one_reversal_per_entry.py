from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_financial_integrity"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("reverses__isnull", False)),
                fields=("reverses",),
                name="uniq_entry_reverses",
            ),
        ),
    ]
