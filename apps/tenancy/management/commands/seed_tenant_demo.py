"""Seed one tenant workspace with a year-to-date financial history.

Purpose
-------
`seed_platform_demo` fills the *platform* console — tenants, plans, invoices,
dunning. It deliberately leaves the tenant workspaces empty, so logging in as a
demo customer lands on a dashboard where every chart reads zero and there is no
way to tell a working app from a broken one. This command fills the other side:
accounts, categories, budgets, goals and a month-by-month transaction history
from January 1st of the current year through today, so trends, budget burn-down
and net-worth charts all have something real to draw.

Safety
------
Refuses to run when `DEBUG` is off unless `--i-know-this-is-not-production` is
passed: these are invented transactions, and they would corrupt every figure a
real user reads.

Idempotent: every posting carries a deterministic idempotency key derived from
the tenant and the slot it fills, so re-running tops up what is missing instead
of doubling the history. Re-run it on any day and it extends the ledger to that
day.

Usage
-----
    python manage.py seed_tenant_demo
    python manage.py seed_tenant_demo --email yuki@example.test
    python manage.py seed_tenant_demo --from 2026-01-01
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.budgeting import services as budget_services
from apps.budgeting.models import Budget
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.finance import services as finance_services
from apps.finance.models import (
    AccountType,
    Category,
    CategoryKind,
    FinancialAccount,
    Payee,
    Transaction,
    TransactionStatus,
)
from apps.goals import services as goal_services
from apps.goals.models import GoalKind, SavingsGoal
from apps.income import services as income_services
from apps.income.models import (
    DeductionKind,
    IncomeFrequency,
    IncomeKind,
    IncomeReceipt,
    IncomeSource,
    Reliability,
)
from apps.ledger.models import JournalEntry
from apps.tenancy.models import Membership, Tenant
from apps.users.models import User

DEFAULT_EMAIL = "amina@example.test"

#: (name, account_type, opening balance in *major* units, include in net worth)
ACCOUNTS = [
    ("Everyday Checking", AccountType.CHECKING, 4_200, True),
    ("Emergency Savings", AccountType.SAVINGS, 11_500, True),
    ("Rewards Credit Card", AccountType.CREDIT_CARD, 820, True),
    ("Cash Wallet", AccountType.CASH, 180, True),
]

INCOME_CATEGORIES = ["Salary", "Freelance"]

#: (category, monthly budget in major units, typical charge, charges per month)
EXPENSE_PLAN = [
    ("Rent", 1_200, (1_200, 1_200), 1),
    ("Groceries", 620, (38, 145), 6),
    ("Utilities", 180, (45, 95), 2),
    ("Transport", 160, (12, 48), 5),
    ("Dining", 240, (18, 72), 5),
    ("Health", 130, (25, 110), 1),
    ("Entertainment", 110, (9, 45), 3),
    ("Shopping", 300, (25, 190), 3),
]

PAYEES_BY_CATEGORY = {
    "Rent": ["Riverside Property Mgmt"],
    "Groceries": ["Naivas", "Carrefour", "Corner Market"],
    "Utilities": ["City Power", "Metro Water", "Fibrelink"],
    "Transport": ["Uber", "Shell", "Metro Transit"],
    "Dining": ["Java House", "Ramen Bar", "Cafe Nord"],
    "Health": ["Wellness Pharmacy", "Dr. Achieng"],
    "Entertainment": ["Netflix", "Spotify", "Cineplex"],
    "Shopping": ["Amazon", "Zara", "Home Centre"],
}

#: (name, kind, target in major units, planned monthly in major units)
GOALS = [
    ("Emergency Fund", GoalKind.EMERGENCY_FUND, 18_000, 400),
    ("Japan Trip", GoalKind.CUSTOM, 6_000, 250),
]


class Command(BaseCommand):
    help = "Seed a tenant workspace with year-to-date accounts, budgets, goals and transactions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default=DEFAULT_EMAIL,
            help="Owner email of the tenant to seed (default: %(default)s).",
        )
        parser.add_argument(
            "--from",
            dest="start",
            default="",
            help="ISO date to start the history from. Defaults to January 1st of the current year.",
        )
        parser.add_argument(
            "--i-know-this-is-not-production",
            action="store_true",
            dest="force",
            help="Required to run with DEBUG off.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG is off. Seeding invented transactions would corrupt every "
                "figure this workspace reports. Re-run with "
                "--i-know-this-is-not-production if this is a throwaway environment."
            )

        user, tenant = self._resolve_tenant(options["email"])
        today = timezone.localdate()
        start = self._resolve_start(options["start"], today)
        if start > today:
            raise CommandError(f"--from {start} is in the future; nothing to seed.")

        # A fixed seed keeps re-runs stable: the same slot always produces the
        # same amount, so idempotency keys line up with identical postings.
        self.rng = random.Random(f"{tenant.id}:{start}")

        # One transaction for the whole run: `SET LOCAL app.current_tenant` is
        # transaction-scoped, and a half-seeded workspace is worse than none.
        with use_tenant(tenant.id, actor_id=user.id), db_transaction.atomic():
            bind_db_tenant(tenant.id)
            accounts = self._ensure_accounts(tenant, start)
            income_cats, expense_cats = self._ensure_categories(tenant)
            payees = self._ensure_payees(expense_cats)
            self._ensure_budget(tenant, expense_cats, start)
            goals = self._ensure_goals(tenant, accounts)
            posted = self._post_history(accounts, income_cats, expense_cats, payees, goals, start, today)
            self._ensure_income_sources(accounts, income_cats, start, today)
            self._report(user, tenant, start, today, posted)

    # ----------------------------------------------------------------- lookups

    def _resolve_tenant(self, email: str) -> tuple[User, Tenant]:
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(
                f"No user with email {email}. Run `manage.py seed_platform_demo` first."
            ) from None
        membership = Membership.objects.filter(user=user).select_related("tenant").first()
        if membership is None:
            raise CommandError(f"{email} has no tenant membership to seed.")
        return user, membership.tenant

    def _resolve_start(self, raw: str, today: date) -> date:
        if not raw:
            return date(today.year, 1, 1)
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise CommandError(f"--from must be an ISO date (YYYY-MM-DD), got {raw!r}.") from None

    def _at(self, day: date, hour: int = 12) -> datetime:
        return timezone.make_aware(datetime.combine(day, time(hour=hour, minute=0)))

    # ------------------------------------------------------------- scaffolding

    def _ensure_accounts(self, tenant: Tenant, start: date) -> dict[str, FinancialAccount]:
        currency = tenant.base_currency
        # Opening balances land the day before the history so the first month's
        # activity reads as change, not as the account springing into existence.
        opened_at = self._at(start - timedelta(days=1), hour=9)
        accounts: dict[str, FinancialAccount] = {}
        for name, account_type, opening_major, in_net_worth in ACCOUNTS:
            existing = FinancialAccount.objects.filter(name=name).first()
            if existing is not None:
                accounts[name] = existing
                continue
            accounts[name] = finance_services.create_financial_account(
                name=name,
                account_type=account_type,
                currency=currency,
                include_in_net_worth=in_net_worth,
                opening_balance_minor=opening_major * 100,
                opening_balance_at=opened_at,
            )
        return accounts

    def _ensure_categories(self, tenant: Tenant) -> tuple[list[Category], dict[str, Category]]:
        currency = tenant.base_currency
        income: list[Category] = []
        for name in INCOME_CATEGORIES:
            cat = Category.objects.filter(name=name, kind=CategoryKind.INCOME).first()
            if cat is None:
                cat = finance_services.create_category(name=name, kind=CategoryKind.INCOME, currency=currency)
            income.append(cat)

        expense: dict[str, Category] = {}
        for name, *_ in EXPENSE_PLAN:
            cat = Category.objects.filter(name=name, kind=CategoryKind.EXPENSE).first()
            if cat is None:
                cat = finance_services.create_category(
                    name=name, kind=CategoryKind.EXPENSE, currency=currency
                )
            expense[name] = cat
        return income, expense

    def _ensure_payees(self, expense_cats: dict[str, Category]) -> dict[str, list[Payee]]:
        payees: dict[str, list[Payee]] = {}
        for category_name, names in PAYEES_BY_CATEGORY.items():
            bucket = []
            for name in names:
                payee, _ = Payee.objects.get_or_create(
                    normalized_name=name.strip().lower(),
                    defaults={
                        "name": name,
                        "default_category": expense_cats.get(category_name),
                    },
                )
                bucket.append(payee)
            payees[category_name] = bucket
        return payees

    def _ensure_budget(self, tenant: Tenant, expense_cats: dict[str, Category], start: date) -> None:
        budget = Budget.objects.filter(name="Monthly Plan").first()
        if budget is None:
            budget = budget_services.create_budget(
                name="Monthly Plan",
                currency=tenant.base_currency,
                starts_on=start,
            )
        for name, limit_major, *_ in EXPENSE_PLAN:
            category = expense_cats[name]
            if budget.lines.filter(category=category).exists():
                continue
            budget_services.add_budget_line(budget=budget, category=category, limit_minor=limit_major * 100)

    def _ensure_goals(self, tenant: Tenant, accounts: dict[str, FinancialAccount]) -> list[SavingsGoal]:
        goals: list[SavingsGoal] = []
        for name, kind, target_major, monthly_major in GOALS:
            goal = SavingsGoal.objects.filter(name=name).first()
            if goal is None:
                goal = goal_services.create_goal(
                    name=name,
                    currency=tenant.base_currency,
                    target_minor=target_major * 100,
                    kind=kind,
                    planned_monthly_minor=monthly_major * 100,
                    target_date=date(timezone.localdate().year + 1, 6, 30),
                )
            goals.append(goal)
        return goals

    # ---------------------------------------------------------------- postings

    def _post_history(
        self,
        accounts: dict[str, FinancialAccount],
        income_cats: list[Category],
        expense_cats: dict[str, Category],
        payees: dict[str, list[Payee]],
        goals: list[SavingsGoal],
        start: date,
        today: date,
    ) -> int:
        checking = accounts["Everyday Checking"]
        savings = accounts["Emergency Savings"]
        card = accounts["Rewards Credit Card"]
        cash = accounts["Cash Wallet"]
        salary, freelance = income_cats[0], income_cats[1]

        posted = 0
        for year, month in self._months(start, today):
            month_start = date(year, month, 1)
            tag = f"{year}-{month:02d}"

            # --- income: salary on the 25th, freelance mid-month in some months
            pay_day = self._clamp(month_start, 25, today)
            if pay_day is not None:
                posted += self._income(
                    checking, salary, 5_400_00, pay_day, f"Monthly salary — {tag}", f"salary:{tag}"
                )
            if self.rng.random() < 0.6:
                gig_day = self._clamp(month_start, 14, today)
                if gig_day is not None:
                    amount = self.rng.randrange(350, 1_400) * 100
                    posted += self._income(
                        checking,
                        freelance,
                        amount,
                        gig_day,
                        f"Freelance project — {tag}",
                        f"freelance:{tag}",
                    )

            # --- expenses
            for name, _limit, (low, high), per_month in EXPENSE_PLAN:
                category = expense_cats[name]
                for n in range(per_month):
                    day = self._clamp(month_start, self.rng.randrange(1, 28), today)
                    if day is None:
                        continue
                    amount = self.rng.randrange(low * 100, high * 100 + 1)
                    payee = self.rng.choice(payees.get(name, [None]) or [None])
                    # Card for retail-ish spend, cash for small day-to-day, the
                    # rest straight off checking — so every account has a story.
                    if name in {"Shopping", "Entertainment", "Dining"}:
                        account = card
                    elif name == "Transport" and amount < 25_00:
                        account = cash
                    else:
                        account = checking
                    posted += self._expense(
                        account,
                        category,
                        amount,
                        day,
                        payee,
                        f"{payee.name if payee else name}",
                        f"{name.lower()}:{tag}:{n}",
                    )

            # --- savings transfer on the 26th, right after payday
            move_day = self._clamp(month_start, 26, today)
            if move_day is not None:
                posted += self._transfer(checking, savings, 400_00, move_day, f"savings:{tag}")
                for goal in goals:
                    if goal.tracking != "manual":
                        continue
                    if goal.contributions.filter(occurred_on=move_day).exists():
                        continue
                    goal_services.add_contribution(
                        goal=goal,
                        amount_minor=(goal.planned_monthly_minor or 200_00),
                        occurred_on=move_day,
                        memo=f"Monthly contribution — {tag}",
                    )

            # --- pay down the card on the 5th of the following month
            card_day = self._clamp(month_start + timedelta(days=35), 5, today)
            if card_day is not None:
                posted += self._transfer(checking, card, 300_00, card_day, f"card:{tag}")

        self._mark_recent_pending()
        return posted

    def _mark_recent_pending(self, count: int = 2) -> None:
        """Leave the newest couple of card charges uncleared.

        A workspace where every row is reconciled cannot demonstrate the one
        thing the ledger's certainty treatment exists for — and a reviewer
        looking at seeded data would reasonably conclude the feature does not
        work. Two pending rows is enough to show the state without making the
        demo look like a broken import.
        """
        newest = list(
            Transaction.objects.filter(transfer_group__isnull=True, amount_minor__lt=0)
            .order_by("-occurred_at")
            .values_list("id", flat=True)[:count]
        )
        if newest:
            Transaction.objects.filter(id__in=newest).update(status=TransactionStatus.PENDING)

    def _months(self, start: date, today: date):
        year, month = start.year, start.month
        while (year, month) <= (today.year, today.month):
            yield year, month
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    def _clamp(self, month_start: date, day: int, today: date) -> date | None:
        """Day-of-month within the month, or None if it hasn't happened yet."""
        try:
            when = month_start.replace(day=day)
        except ValueError:
            return None
        return None if when > today else when

    def _ensure_income_sources(self, accounts, income_cats, start: date, today: date) -> None:
        """Describe the income this seed has been posting all along.

        Derived from the history rather than invented alongside it: every
        receipt below is a real posted transaction, so the observed mean the
        freelance source projects from is a measurement of this workspace's own
        ledger. Seeding a source whose figures disagreed with its transactions
        would put the exact defect this model exists to prevent into the demo.

        Two sources on purpose. The salary exercises the fixed path — stated
        amount, gross and deductions, a real take-home rate. The freelance work
        exercises the variable path, where the expected figure comes from what
        actually arrived rather than from a number somebody typed.
        """
        checking = accounts["Everyday Checking"]
        salary_cat, freelance_cat = income_cats[0], income_cats[1]

        salary = IncomeSource.objects.filter(name="Monthly salary").first()
        if salary is None:
            salary = income_services.create_source(
                name="Monthly salary",
                payer="Meridian Logistics",
                kind=IncomeKind.EMPLOYMENT,
                currency=checking.currency,
                # Gross and net differ by the deductions added below, so the
                # take-home rate on the screen is arithmetic, not decoration.
                net_minor=5_400_00,
                gross_minor=7_200_00,
                reliability=Reliability.FIXED,
                frequency=IncomeFrequency.MONTHLY,
                pay_day=25,
                starts_on=start,
                deposit_account=checking,
            )
            income_services.add_deduction(
                source=salary, kind=DeductionKind.TAX, label="PAYE", percent_bp=2000
            )
            income_services.add_deduction(
                source=salary, kind=DeductionKind.PENSION, label="Pension", percent_bp=500
            )

        freelance = IncomeSource.objects.filter(name="Freelance work").first()
        if freelance is None:
            freelance = income_services.create_source(
                name="Freelance work",
                kind=IncomeKind.SELF_EMPLOYMENT,
                currency=checking.currency,
                # Deliberately a round guess. The receipts below are what the
                # projection will actually use, and the gap between the two is
                # the feature.
                net_minor=800_00,
                reliability=Reliability.VARIABLE,
                frequency=IncomeFrequency.MONTHLY,
                starts_on=start,
                deposit_account=checking,
            )

        # Receipts from the posted history, so nothing here is invented.
        for source, category in ((salary, salary_cat), (freelance, freelance_cat)):
            existing = set(IncomeReceipt.objects.filter(source=source).values_list("occurred_on", flat=True))
            transactions = Transaction.objects.filter(category=category, amount_minor__gt=0).order_by(
                "occurred_at"
            )
            for txn in transactions:
                occurred_on = timezone.localtime(txn.occurred_at).date()
                if occurred_on in existing or occurred_on > today:
                    continue
                income_services.record_receipt(
                    source=source,
                    occurred_on=occurred_on,
                    net_minor=txn.amount_minor,
                    transaction_ref=txn,
                    memo=txn.memo or "",
                )
                existing.add(occurred_on)

    def _income(self, account, category, amount, day, memo, key) -> int:
        marker = f"seed:{key}"
        if Transaction.objects.filter(metadata__seed=marker).exists():
            return 0
        with db_transaction.atomic():
            finance_services.record_income(
                financial_account=account,
                category=category,
                amount_minor=amount,
                occurred_at=self._at(day),
                memo=memo,
                idempotency_key=marker,
                tenant_metadata={"seed": marker},
            )
        return 1

    def _expense(self, account, category, amount, day, payee, memo, key) -> int:
        marker = f"seed:{key}"
        if Transaction.objects.filter(metadata__seed=marker).exists():
            return 0
        with db_transaction.atomic():
            finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=amount,
                occurred_at=self._at(day),
                memo=memo,
                payee=payee,
                idempotency_key=marker,
                tenant_metadata={"seed": marker},
            )
        return 1

    def _transfer(self, from_account, to_account, amount, day, key) -> int:
        # Transfers carry no metadata hook, so idempotency rides on the journal
        # entry key — the same guarantee, just checked one level down.
        marker = f"seed:transfer:{key}"
        if JournalEntry.objects.filter(idempotency_key=marker).exists():
            return 0
        with db_transaction.atomic():
            finance_services.record_transfer(
                from_account=from_account,
                to_account=to_account,
                amount_minor=amount,
                occurred_at=self._at(day, hour=10),
                memo="Scheduled transfer",
                idempotency_key=marker,
            )
        return 2

    # ------------------------------------------------------------------ report

    def _report(self, user, tenant, start, today, posted) -> None:
        out = self.stdout
        out.write(self.style.SUCCESS("\nTenant workspace seeded\n"))
        out.write(f"  Workspace  {tenant.name} ({tenant.base_currency})")
        out.write(f"  Log in as  {user.email}")
        out.write(f"  Range      {start} → {today}")
        out.write(f"  Posted     {posted} new transactions this run")
        out.write(
            f"  Totals     {Transaction.objects.count()} transactions, "
            f"{FinancialAccount.objects.count()} accounts, "
            f"{SavingsGoal.objects.count()} goals"
        )
        out.write("\n  Re-run any time — it tops up to today rather than duplicating.\n")
