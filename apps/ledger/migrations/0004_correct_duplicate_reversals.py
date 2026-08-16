"""Restore balances after leftover double-void reversals.

`0003` keeps `uniq_entry_reverses` out of the database so migrate can finish.
That does not move money. Extra reversing journals are append-only, so the
repair posts a reverse of each extra (keeping the first reversal of the
original). Application `reverse_journal_entry` is what stops this happening
again; this data migration is the one-time undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.ledger.services import correct_duplicate_reversals

    correct_duplicate_reversals()


def backwards(apps, schema_editor):
    # Corrections are themselves journal entries. They cannot be deleted.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0003_one_reversal_per_entry"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
