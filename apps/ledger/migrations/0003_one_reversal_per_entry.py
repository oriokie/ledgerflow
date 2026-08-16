from django.db import migrations, models
from django.db.models import Count
from django.db.utils import IntegrityError, OperationalError, ProgrammingError

CONSTRAINT = models.UniqueConstraint(
    condition=models.Q(("reverses__isnull", False)),
    fields=("reverses",),
    name="uniq_entry_reverses",
)


def apply_constraint(apps, schema_editor):
    """Add one-reversal-per-original, unless this ledger already has two.

    The double-void bug posted a second reversing entry for the same original.
    Those rows cannot be deleted (ledger is append-only), and adding the
    unique constraint on top of them aborts migrate — which, in entrypoint.sh,
    means gunicorn never starts and the site 502s. Application code already
    refuses a second reverse; skip the constraint when history is dirty.
    """
    JournalEntry = apps.get_model("ledger", "JournalEntry")
    has_duplicates = (
        JournalEntry.objects.filter(reverses__isnull=False)
        .values("reverses")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .exists()
    )
    if has_duplicates:
        return
    try:
        schema_editor.add_constraint(JournalEntry, CONSTRAINT)
    except (IntegrityError, OperationalError, ProgrammingError):
        return


def drop_constraint(apps, schema_editor):
    JournalEntry = apps.get_model("ledger", "JournalEntry")
    try:
        schema_editor.remove_constraint(JournalEntry, CONSTRAINT)
    except (IntegrityError, OperationalError, ProgrammingError):
        return


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_financial_integrity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(apply_constraint, drop_constraint),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="journalentry",
                    constraint=CONSTRAINT,
                ),
            ],
        ),
    ]
