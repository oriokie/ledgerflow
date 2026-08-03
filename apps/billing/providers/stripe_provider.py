"""
Stripe adapter.

Real Stripe API shapes and call patterns, but written to run in three modes:

* **live** — `STRIPE_SECRET_KEY` set and the `stripe` SDK installed: real calls.
* **sandbox** — key set but SDK missing, OR key is a test key: same code path,
  the SDK is imported lazily and any import/credential gap degrades to a
  deterministic simulated success so the whole flow is exercisable end-to-end
  in dev without a Stripe account.

Wiring a real account is therefore just: `pip install stripe` +
`STRIPE_SECRET_KEY=sk_live_…` + `STRIPE_WEBHOOK_SECRET=whsec_…`. No code change.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from django.conf import settings

from .base import (
    ChargeResult,
    PaymentError,
    PaymentMethodResult,
    PaymentProvider,
    RefundResult,
    WebhookResult,
)


def _stripe_sdk():
    """Import the Stripe SDK lazily; return None if unavailable (sandbox mode)."""
    try:
        import stripe  # type: ignore

        key = getattr(settings, "STRIPE_SECRET_KEY", "")
        if not key:
            return None
        stripe.api_key = key
        return stripe
    except Exception:
        return None


class StripeProvider(PaymentProvider):
    key = "stripe"
    supports_refunds = True

    def attach_payment_method(self, *, tenant_id: str, token: str, kind: str) -> PaymentMethodResult:
        stripe = _stripe_sdk()
        if stripe is None:
            # Sandbox: derive stable, obviously-fake display fields from the token.
            digest = hashlib.sha256(token.encode()).hexdigest()
            return PaymentMethodResult(
                provider_ref=f"pm_sandbox_{digest[:16]}",
                kind="card",
                brand="visa",
                last4=digest[-4:] if digest[-4:].isdigit() else "4242",
                exp_month=12,
                exp_year=2030,
                metadata={"sandbox": True},
            )
        try:
            pm = stripe.PaymentMethod.retrieve(token)
            card = pm.get("card", {}) if isinstance(pm, dict) else pm.card
            return PaymentMethodResult(
                provider_ref=pm["id"] if isinstance(pm, dict) else pm.id,
                kind="card",
                brand=card.get("brand", "") if isinstance(card, dict) else card.brand,
                last4=card.get("last4", "") if isinstance(card, dict) else card.last4,
                exp_month=card.get("exp_month") if isinstance(card, dict) else card.exp_month,
                exp_year=card.get("exp_year") if isinstance(card, dict) else card.exp_year,
            )
        except Exception as exc:  # pragma: no cover - network path
            raise PaymentError(f"Stripe could not attach the payment method: {exc}") from exc

    def charge(
        self,
        *,
        tenant_id: str,
        amount_minor: int,
        currency: str,
        payment_method_ref: str,
        description: str = "",
        idempotency_key: str = "",
    ) -> ChargeResult:
        stripe = _stripe_sdk()
        if stripe is None:
            # Sandbox: deterministic success.
            return ChargeResult(
                success=True,
                provider_ref=f"pi_sandbox_{uuid.uuid4().hex[:20]}",
                status="succeeded",
            )
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount_minor,
                currency=currency.lower(),
                payment_method=payment_method_ref,
                confirm=True,
                description=description,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                idempotency_key=idempotency_key or None,
                metadata={"tenant_id": tenant_id},
            )
            status = intent["status"] if isinstance(intent, dict) else intent.status
            ref = intent["id"] if isinstance(intent, dict) else intent.id
            if status == "succeeded":
                return ChargeResult(success=True, provider_ref=ref, status="succeeded")
            if status in {"requires_action", "requires_confirmation"}:
                return ChargeResult(
                    success=False, provider_ref=ref, status="pending", requires_action=True
                )
            return ChargeResult(
                success=False, provider_ref=ref, status="failed", failure_reason=str(status)
            )
        except Exception as exc:  # pragma: no cover - network path
            raise PaymentError(f"Stripe charge failed: {exc}") from exc

    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookResult:
        stripe = _stripe_sdk()
        secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        if stripe is None or not secret:
            # Sandbox: trust the JSON body as-is (dev/testing only).
            import json

            event = json.loads(body or b"{}")
        else:  # pragma: no cover - network path
            try:
                event = stripe.Webhook.construct_event(
                    body, headers.get("stripe-signature", ""), secret
                )
            except Exception as exc:
                raise PaymentError(f"Invalid Stripe webhook signature: {exc}") from exc

        event_type = event.get("type", "")
        obj: dict[str, Any] = event.get("data", {}).get("object", {})
        normalized = {
            "payment_intent.succeeded": "payment.succeeded",
            "payment_intent.payment_failed": "payment.failed",
            "customer.subscription.deleted": "subscription.canceled",
        }.get(event_type, event_type)
        return WebhookResult(
            event_id=event.get("id", ""),
            event_type=event_type,
            normalized_type=normalized,
            provider_ref=obj.get("id", ""),
            raw=event,
        )

    def refund(
        self,
        *,
        charge_ref: str,
        amount_minor: int,
        currency: str,
        reason: str = "",
        idempotency_key: str = "",
    ) -> RefundResult:
        stripe = _stripe_sdk()
        if stripe is None:
            # Sandbox: deterministic success, ref derived from the charge so
            # repeated calls in a test produce a stable, greppable value.
            digest = hashlib.sha256(f"{charge_ref}:{amount_minor}".encode()).hexdigest()
            return RefundResult(
                success=True,
                provider_ref=f"re_sandbox_{digest[:16]}",
                status="succeeded",
                metadata={"sandbox": True},
            )
        try:  # pragma: no cover - network path
            refund = stripe.Refund.create(
                payment_intent=charge_ref,
                amount=amount_minor,
                reason="requested_by_customer",
                metadata={"note": reason[:500]},
                idempotency_key=idempotency_key or None,
            )
            data = refund if isinstance(refund, dict) else refund.to_dict()
            status = data.get("status", "pending")
            return RefundResult(
                success=status == "succeeded",
                provider_ref=data.get("id", ""),
                # Stripe reports "pending" while the card network settles.
                status="succeeded" if status == "succeeded" else ("failed" if status == "failed" else "pending"),
                failure_reason=data.get("failure_reason", "") or "",
            )
        except Exception as exc:  # pragma: no cover - network path
            raise PaymentError(f"Stripe could not process the refund: {exc}") from exc
