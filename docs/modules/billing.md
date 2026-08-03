# Billing & Subscriptions

LedgerFlow's SaaS billing subsystem: plans, subscriptions, payment methods,
charges, and provider webhooks. Lives in `apps/billing`.

## Model

- **Plan** — the global platform catalog (Free / Plus / Family / Business, each
  in monthly + yearly). Not tenant-scoped; every workspace picks from the same
  menu. Seed/refresh with `python manage.py seed_plans` (idempotent).
- **Subscription** — one per tenant (DB-enforced). Tracks status, current
  period, and provider linkage.
- **PaymentMethod** — a saved card or M-PESA number. **Only safe display fields
  are stored** (brand, last4, masked phone) plus the provider's token — never a
  raw PAN. PCI scope stays with the provider.
- **Payment** — the immutable charge audit trail.
- **WebhookEvent** — inbound-webhook idempotency + audit (dedupe by
  provider + event id).

## Payment providers

Providers implement the `PaymentProvider` interface
(`apps/billing/providers/base.py`). Two ship today:

- **Stripe** (`stripe_provider.py`) — PaymentIntents. Cards are tokenized
  client-side with Stripe.js, so card data never reaches our server.
- **M-PESA** (`mpesa_provider.py`) — Safaricom Daraja STK push. Inherently
  async: `charge()` returns `requires_action=True` / `pending`, and the
  subscription only activates when the callback (webhook) confirms.

Adding a provider = one new adapter class + registry entry. No service or model
change.

### Sandbox vs live

Every adapter runs in **sandbox mode** when its credentials are absent: the
same code path returns deterministic simulated results, so the full
subscribe → charge → webhook lifecycle is exercisable in dev and CI without any
provider account. Going live is **credentials-only**:

```
# Stripe
STRIPE_SECRET_KEY=sk_live_…
STRIPE_PUBLISHABLE_KEY=pk_live_…
STRIPE_WEBHOOK_SECRET=whsec_…

# M-PESA (Daraja)
MPESA_CONSUMER_KEY=…
MPESA_CONSUMER_SECRET=…
MPESA_SHORTCODE=…
MPESA_PASSKEY=…
MPESA_API_BASE=https://api.safaricom.co.ke      # production base
MPESA_CALLBACK_URL=https://yourdomain.com/api/v1/billing/webhooks/mpesa/
```

Install the Stripe SDK for live card processing: `pip install stripe`.

## API

| Method & path | Purpose |
|---|---|
| `GET /billing/plans/` | Public plan catalog |
| `GET /billing/subscription/` | Current workspace subscription |
| `POST /billing/subscription/` | Subscribe / change plan (owner/admin) |
| `POST /billing/subscription/cancel/` | Cancel (owner/admin) |
| `GET/POST /billing/payment-methods/` | List / add a card or M-PESA |
| `DELETE /billing/payment-methods/{id}/` | Remove (owner/admin) |
| `GET /billing/payments/` | Payment history |
| `POST /billing/webhooks/{provider}/` | Inbound provider webhook (public, signature-verified) |

## Webhooks

Point each provider's webhook at `/api/v1/billing/webhooks/{provider}/`.
Delivery is verified by the provider's own signature check inside
`parse_webhook`, and every event id is recorded so at-least-once delivery never
double-applies (a re-delivered event returns `"duplicate"`).

## Entitlements

`Plan` carries `max_members`, `max_accounts`, and `ai_insights`. These are the
hooks for enforcement; wire checks at the relevant service boundaries as the
product grows (kept explicit rather than a generic feature-flag layer so the
limits that exist are greppable).
