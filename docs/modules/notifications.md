# `notifications` — Notifications & Alerts

Durable, per-user (or workspace-wide) alerts generated from signals the engine
already computes — budget status, anomalies, goal achievement, bills. Mostly
delivery plumbing, not new analysis.

## Domain model

| Model | Purpose | Key fields |
|---|---|---|
| `Notification` | One alert | `user` (null = workspace-wide), `type` (`NotificationType`), `severity`, `title`/`body`, `subject_type`/`subject_id` (soft reference, survives referent deletion), `dedupe_key` (unique per tenant), `read_at`, `delivered_channels` |
| `NotificationPreference` | Per-user opt-outs and thresholds | `muted_types`, `budget_threshold`, `low_balance_minor`, `large_transaction_minor` |

`NotificationType` is the closed vocabulary: budget threshold/exceeded, low
balance, large transaction, anomaly, bill due/overdue, goal achieved/milestone.
Both models are RLS-protected.

The model is delivery-agnostic: rows are produced by the service layer and read
back for an in-app inbox; an email/push channel can consume the same rows later
(`delivered_channels` tracks fan-out) without changing producers.

## Service layer (`services.py`)

`raise_notification` is the single producer entry point — **idempotent on
`dedupe_key`** (raising the same alert twice refreshes the existing row instead
of spamming), and it enforces preference mutes so no producer can bypass them.
Higher-level producers translate an engine signal into notification(s):
`notify_large_transaction`, `evaluate_budget_alerts` (reads
`budgeting.selectors.budget_status`), `notify_goal_achieved`, `notify_anomalies`,
`evaluate_bill_alerts` (reads `finance.bills.upcoming_bills`). `mark_read` /
`mark_all_read` for the inbox.

## Background sweep (`tasks.py`)

`dispatch_alert_sweep` (daily beat, 07:00) fans out per-tenant exactly like the
recurring dispatcher — streams active tenants, hands off bounded batches to
`dispatch_alert_batch` → `run_alert_sweep_for_tenant`, each binding its own RLS
context. Per tenant it marks bills overdue, then raises bill-due and
budget-threshold alerts. Idempotent producers make retries safe. See
[`../DEPLOYMENT.md`](../DEPLOYMENT.md#celery-beat-schedule).

## Selectors & API

`inbox` (a user's notices plus workspace-wide, newest first, via the inbox
partial indexes), `unread_count`.

Base path `/api/v1/notifications/`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Cursor-paginated inbox (`?unread=true`); response includes `unread_count` |
| `POST` | `/read-all/` | Mark all read |
| `POST` | `/<id>/read/` | Mark one read |

All `required_role = VIEWER` — reading your own notices isn't a finance write.

## How other modules raise notifications

Producers are called from where the signal originates: the large-transaction
alert fires in the intelligence post-create pipeline
(`apps/intelligence/signals.py`), goal-achieved fires in `goals.services`, and
budget/bill alerts run in the daily sweep. Each call is wrapped so a
notification failure never breaks the underlying financial action.

## Testing

`tests/test_new_features.py` (budget-alert raising, dedupe, alert-sweep task
under `transaction=True`) and `tests/test_new_features_api.py` (inbox endpoint).
