from django.db import migrations, models

# Intentionally not applied as database DDL.
#
# `FORCE ROW LEVEL SECURITY` is on `ledger_journalentry`. During migrate there
# is no `app.current_tenant`, so an ORM duplicate-check sees zero rows. The
# unique index then scans the real table, hits leftover double-void reversals,
# raises, and (even if Python catches it) Postgres aborts the transaction —
# Django cannot record the migration, entrypoint.sh never starts gunicorn, and
# the site 502s. Application code in `reverse_journal_entry` already refuses a
# second reverse. The constraint stays in Django state so `makemigrations`
# does not try to recreate it.


CONSTRAINT = models.UniqueConstraint(
    condition=models.Q(("reverses__isnull", False)),
    fields=("reverses",),
    name="uniq_entry_reverses",
)


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_financial_integrity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddConstraint(
                    model_name="journalentry",
                    constraint=CONSTRAINT,
                ),
            ],
        ),
    ]
