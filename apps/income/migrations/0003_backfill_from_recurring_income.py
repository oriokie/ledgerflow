"""Give every existing income schedule a real IncomeSource.

Before this app, the only record that money came in was a
``RecurringTransaction`` with ``txn_type='income'``, and the cash-flow calendar
decided which of those was a *salary* by searching its memo for the English
words "salary", "payroll", "wage" and "paycheck".

Replacing that heuristic with a model is only an improvement if existing users
come with it. Without this backfill, everyone who already had a recurring
salary would lose their payday marker the moment the new code shipped —
trading a heuristic that is wrong for some users for a blank that is wrong for
all of them.

So each existing income template gets a source, linked one-to-one, and the
label guess is used **once, here, at migration time** to seed the kind. That is
the right place for it: a one-off, reviewable, correctable guess about existing
data, rather than a rule that silently re-runs on every projection forever.
Anything the guess does not recognise becomes `OTHER`, which is honest — it
says "we do not know what this is" instead of asserting it is a wage.
"""

from __future__ import annotations

from django.db import migrations

#: The retired heuristic, preserved here and nowhere else. It runs once per
#: existing row and never again.
SALARY_WORDS = ("salary", "payroll", "wage", "paycheck")

#: `finance.Frequency` -> `income.IncomeFrequency`. The finance enum has four
#: members and every one of them maps cleanly; anything unrecognised becomes
#: AD_HOC rather than being rounded to a cadence the user never agreed to.
FREQUENCY_MAP = {
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "yearly": "annual",
}


def backfill(apps, schema_editor):
    RecurringTransaction = apps.get_model("finance", "RecurringTransaction")
    IncomeSource = apps.get_model("income", "IncomeSource")

    templates = RecurringTransaction.objects.filter(txn_type="income", deleted_at__isnull=True)
    for template in templates.iterator():
        label = f"{template.memo or ''}".lower()
        looks_like_pay = any(word in label for word in SALARY_WORDS)

        frequency = FREQUENCY_MAP.get(template.frequency, "ad_hoc")
        # Only a day-of-month cadence has a pay day, and only up to the 28th —
        # the model's own constraint, respected here so the migration cannot
        # write a row the application would reject.
        pay_day = None
        if frequency in ("monthly", "semi_monthly", "quarterly", "annual"):
            day = template.starts_on.day
            pay_day = day if day <= 28 else None

        IncomeSource.objects.create(
            tenant_id=template.tenant_id,
            name=template.memo or "Income",
            kind="employment" if looks_like_pay else "other",
            payer="",
            currency=template.currency,
            net_minor=template.amount_minor,
            gross_minor=None,
            # A schedule that already auto-posts a fixed amount is, by
            # construction, fixed. Reliability the user disagrees with is one
            # edit away; a source that refuses to project is a broken screen.
            reliability="fixed" if looks_like_pay else "variable",
            frequency=frequency,
            pay_day=pay_day,
            starts_on=template.starts_on,
            ends_on=template.ends_on,
            deposit_account_id=template.financial_account_id,
            recurring_transaction_id=template.id,
            is_active=template.is_active,
            notes="Created automatically from an existing recurring income schedule.",
        )


def unbackfill(apps, schema_editor):
    """Remove only the rows this migration created.

    Keyed on the one-to-one link rather than on the note, so a user who edited
    the note does not lose their source, and a source they created by hand is
    never deleted by a rollback.
    """
    IncomeSource = apps.get_model("income", "IncomeSource")
    IncomeSource.objects.filter(recurring_transaction_id__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("income", "0002_rls_income_tables"),
        ("finance", "0001_initial"),
    ]
    operations = [migrations.RunPython(backfill, unbackfill)]
