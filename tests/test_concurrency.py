"""Concurrency: race the locks instead of grepping for them.

The D-4 and D-5 fixes are currently verified by asserting that
`select_for_update` appears in the source. That proves the fix is *present*,
not that it *works* — and locking is the category where the earlier audits
found the most real defects, so proving presence is not enough.

These tests run genuine parallel transactions on separate database connections
and assert the outcome. Notes on the mechanics, because they are easy to get
subtly wrong and end up testing nothing:

* **`transaction=True` is mandatory.** pytest-django's default wraps each test
  in a transaction that never commits, so a second connection would see none of
  the setup and every "race" would trivially pass.
* **Each thread must close its connection.** Django opens one per thread; left
  open, they exhaust the pool and the teardown flush blocks.
* **A barrier synchronises the start.** Without it the threads run sequentially
  by luck and the test passes whether or not a lock exists.

The control test at the end deliberately removes the lock and shows the lost
update appearing — otherwise these would be assertions nobody has seen fail.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from django.db import connections, transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]

THREADS = 8


def _in_parallel(work, count=THREADS):
    """Run `work(index)` on `count` threads, released together.

    Returns whatever each call produced, plus any exception it raised — a race
    that fails by raising is as interesting as one that fails by miscounting.
    """
    barrier = threading.Barrier(count)
    results: list = [None] * count
    errors: list = [None] * count

    def runner(i):
        try:
            barrier.wait(timeout=10)
            results[i] = work(i)
        except Exception as exc:  # noqa: BLE001 — reported, not swallowed
            errors[i] = exc
        finally:
            # Django opens a connection per thread; leaving them open exhausts
            # the pool and hangs the post-test flush.
            connections.close_all()

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results, [e for e in errors if e]


# ==================================================== D-4: the learning store
def test_concurrent_categorisation_does_not_lose_updates():
    """Eight threads teach the same merchant at once.

    Before the lock this was read-modify-write on both a counter and a JSON
    dict, so concurrent writers lost increments — and, worse, lost whole
    category keys, because the dict was read into Python and written back
    entire.
    """
    from apps.intelligence import automation_services
    from apps.intelligence.models import MerchantProfile
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    tenant_id = membership.tenant_id

    from apps.finance import services as finance_services
    from apps.finance.models import Transaction

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            account = finance_services.create_financial_account(
                name="Current", account_type="checking", currency="USD"
            )
            category = finance_services.create_category(name="Groceries", kind="expense", currency="USD")
            txn_ids = [
                finance_services.record_expense(
                    financial_account=account,
                    category=category,
                    amount_minor=500,
                    occurred_at="2026-03-01T12:00:00Z",
                    memo="TESCO STORES 4471",
                ).id
                for _ in range(THREADS)
            ]

    def learn(i):
        with transaction.atomic():
            bind_db_tenant(tenant_id)
            with use_tenant(tenant_id, actor_id=membership.user_id):
                txn = Transaction.objects.get(id=txn_ids[i])
                automation_services.learn_from_transaction(txn)
        return True

    _, errors = _in_parallel(learn)
    assert not errors, errors

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            profile = MerchantProfile.objects.get()
            counts = profile.category_counts

    assert profile.transaction_count == THREADS, (
        f"{THREADS} concurrent writers produced a count of "
        f"{profile.transaction_count} — increments were lost."
    )
    assert sum(counts.values()) == THREADS, (
        f"category votes total {sum(counts.values())}, expected {THREADS} — "
        "the JSON dict lost writes."
    )


# ======================================================= D-5: plan seat limits
def test_concurrent_invitations_cannot_exceed_the_seat_limit():
    """The check was count-then-decide with no lock, so two requests could both
    read the pre-change count and both pass a limit with room for one."""
    from apps.billing.models import BillingInterval, Plan, PlanTier, Subscription, SubscriptionStatus
    from apps.tenancy import services as tenancy
    from apps.tenancy.models import Invitation, InvitationStatus, Role
    from tests.factories import MembershipFactory

    owner = MembershipFactory(role=Role.OWNER)
    plan = Plan.objects.create(
        tier=PlanTier.PLUS, name="Plus", price_minor=900, currency="USD",
        interval=BillingInterval.MONTHLY, max_members=3,
    )
    Subscription.objects.create(
        tenant_id=owner.tenant_id, plan=plan, status=SubscriptionStatus.ACTIVE
    )

    def invite(i):
        with transaction.atomic():
            bind_db_tenant(owner.tenant_id)
            with use_tenant(owner.tenant_id, actor_id=owner.user_id):
                tenancy.create_invitation(
                    tenant=owner.tenant,
                    invited_by_membership=owner,
                    email=f"seat{i}@example.test",
                    role=Role.MEMBER,
                )
        return "created"

    results, _ = _in_parallel(invite)
    created = sum(1 for r in results if r == "created")

    pending = Invitation.objects.filter(
        tenant=owner.tenant, status=InvitationStatus.PENDING
    ).count()
    seats_committed = 1 + pending  # the owner plus everyone invited

    assert seats_committed <= plan.max_members, (
        f"{THREADS} concurrent invitations committed {seats_committed} seats on a "
        f"{plan.max_members}-seat plan — the limit check raced."
    )
    assert created >= 1, "every request failed; the lock is serialising into deadlock"


# ================================================= the ledger's own guarantee
def test_concurrent_postings_to_one_account_keep_the_balance_correct():
    """`post_entry` locks accounts before touching balances. Eight concurrent
    postings must sum exactly — a lost update here is money vanishing."""
    from apps.finance import services as finance
    from apps.finance.models import Category, FinancialAccount
    from apps.ledger.models import AccountBalance
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    tenant_id = membership.tenant_id

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            account = finance.create_financial_account(
                name="Current", account_type="checking", currency="USD"
            )
            category = finance.create_category(name="Living", kind="expense", currency="USD")
            account_id, category_id = account.id, category.id
            ledger_account_id = account.ledger_account_id

    def spend(i):
        with transaction.atomic():
            bind_db_tenant(tenant_id)
            with use_tenant(tenant_id, actor_id=membership.user_id):
                finance.record_expense(
                    financial_account=FinancialAccount.objects.get(id=account_id),
                    category=Category.objects.get(id=category_id),
                    amount_minor=100,
                    occurred_at="2026-03-01T12:00:00Z",
                    memo=f"concurrent {i}",
                )
        return True

    _, errors = _in_parallel(spend)
    assert not errors, errors

    # `.unscoped` bypasses the app manager but not the database policy, so the
    # tenant still has to be bound or RLS returns nothing and the assertion
    # below would compare against zero.
    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            balance = AccountBalance.objects.get(account_id=ledger_account_id)
    assert balance.balance_minor == -100 * THREADS, (
        f"balance is {balance.balance_minor}, expected {-100 * THREADS} — "
        "concurrent postings lost an update."
    )


# ============================================ idempotency under real contention
def test_the_same_idempotency_key_posted_concurrently_produces_one_entry():
    """`post_entry` catches the unique-constraint violation and returns the
    winner. That path is only reachable under genuine contention, so it has
    never actually executed in a test until now."""
    from apps.ledger import services as ledger
    from apps.ledger.models import Account, AccountKind, Direction, JournalEntry
    from apps.ledger.services import LineInput
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    tenant_id = membership.tenant_id
    key = f"race-{uuid.uuid4().hex[:12]}"

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            debit = Account.objects.create(name="Cash", kind=AccountKind.ASSET, currency="USD")
            credit = Account.objects.create(name="Food", kind=AccountKind.EXPENSE, currency="USD")
            debit_id, credit_id = str(debit.id), str(credit.id)

    def post(i):
        with transaction.atomic():
            bind_db_tenant(tenant_id)
            with use_tenant(tenant_id, actor_id=membership.user_id):
                entry = ledger.post_journal_entry(
                    occurred_at="2026-03-01T12:00:00Z",
                    lines=[
                        LineInput(account_id=credit_id, direction=Direction.DEBIT, amount_minor=500),
                        LineInput(account_id=debit_id, direction=Direction.CREDIT, amount_minor=500),
                    ],
                    idempotency_key=key,
                    memo="concurrent idempotent post",
                )
                return str(entry.id)

    results, errors = _in_parallel(post)
    assert not errors, errors

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            entries = JournalEntry.objects.filter(idempotency_key=key).count()
    assert entries == 1, f"{THREADS} concurrent posts created {entries} entries"
    # And every caller got the same entry back, rather than an error.
    assert len(set(r for r in results if r)) == 1, set(results)


# ================================================================= the control
def test_an_unlocked_read_modify_write_does_lose_updates():
    """A control, so the assertions above are known to be capable of failing.

    Performs the same eight-way race against a counter *without* a lock. If
    this passes — if the unlocked version is also correct — then the test
    harness is not producing real concurrency and every result above is
    meaningless.
    """
    from apps.intelligence.models import MerchantProfile
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    tenant_id = membership.tenant_id

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            profile_id = MerchantProfile.objects.create(
                key="control-merchant", display_name="Control"
            ).id

    def increment_without_a_lock(i):
        with transaction.atomic():
            bind_db_tenant(tenant_id)
            with use_tenant(tenant_id, actor_id=membership.user_id):
                # Deliberately no select_for_update and no F() expression.
                profile = MerchantProfile.objects.get(id=profile_id)
                profile.transaction_count += 1
                profile.save(update_fields=["transaction_count"])
        return True

    _in_parallel(increment_without_a_lock)

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=membership.user_id):
            final = MerchantProfile.objects.get(id=profile_id).transaction_count

    assert final < THREADS, (
        f"the unlocked counter reached {final}/{THREADS} — the threads are not "
        "actually racing, so the locking assertions above prove nothing."
    )
