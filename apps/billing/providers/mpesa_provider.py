"""
M-PESA adapter (Safaricom Daraja API — STK Push / Lipa Na M-PESA Online).

M-PESA is fundamentally asynchronous: you initiate an STK push, the user
approves on their phone, and the result arrives later on a callback URL. So
`charge()` here returns `requires_action=True` with `status="pending"`; the
Payment is only marked succeeded when the callback (webhook) lands.

Modes mirror the Stripe adapter:
* **live** — `MPESA_CONSUMER_KEY`/`MPESA_CONSUMER_SECRET`/`MPESA_SHORTCODE`/
  `MPESA_PASSKEY` set: real Daraja calls (OAuth token then STK push).
* **sandbox** — credentials missing: deterministic simulated STK push so the
  flow is exercisable without Safaricom credentials.

Going live is credentials-only; no code change.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from django.conf import settings

from .base import (
    ChargeResult,
    PaymentError,
    PaymentMethodResult,
    PaymentProvider,
    RefundResult,
    WebhookResult,
)


def _mpesa_configured() -> bool:
    return all(
        getattr(settings, key, "")
        for key in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY")
    )


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 6:
        return phone
    return f"+{digits[:3]}****{digits[-3:]}"


class MpesaProvider(PaymentProvider):
    key = "mpesa"
    supports_refunds = True

    def attach_payment_method(self, *, tenant_id: str, token: str, kind: str) -> PaymentMethodResult:
        # For M-PESA the "token" is the phone number itself (there's no stored
        # card equivalent); we keep only a masked form.
        return PaymentMethodResult(
            provider_ref=f"mpesa_{uuid.uuid4().hex[:12]}",
            kind="mpesa",
            phone_masked=_mask_phone(token),
            metadata={"msisdn_hash": str(abs(hash(token)))[:12]},
        )

    def _access_token(self) -> str:  # pragma: no cover - network path
        import requests

        base = getattr(settings, "MPESA_API_BASE", "https://sandbox.safaricom.co.ke")
        resp = requests.get(
            f"{base}/oauth/v1/generate?grant_type=client_credentials",
            auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

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
        # M-PESA transacts in whole KES shillings, not cents.
        amount_kes = max(1, round(amount_minor / 100))

        if not _mpesa_configured():
            # Sandbox: pretend the STK push was accepted; a webhook will confirm.
            checkout_id = f"ws_CO_sandbox_{uuid.uuid4().hex[:16]}"
            return ChargeResult(
                success=False,
                provider_ref=checkout_id,
                status="pending",
                requires_action=True,
                action_detail={
                    "message": "An M-PESA prompt was sent to the customer's phone (sandbox).",
                    "checkout_request_id": checkout_id,
                },
            )

        try:  # pragma: no cover - network path
            import requests

            token = self._access_token()
            shortcode = settings.MPESA_SHORTCODE
            passkey = settings.MPESA_PASSKEY
            ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            password = base64.b64encode(f"{shortcode}{passkey}{ts}".encode()).decode()
            base = getattr(settings, "MPESA_API_BASE", "https://sandbox.safaricom.co.ke")
            payload = {
                "BusinessShortCode": shortcode,
                "Password": password,
                "Timestamp": ts,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount_kes,
                "PartyA": payment_method_ref,
                "PartyB": shortcode,
                "PhoneNumber": payment_method_ref,
                "CallBackURL": getattr(settings, "MPESA_CALLBACK_URL", ""),
                "AccountReference": tenant_id[:12],
                "TransactionDesc": description[:13] or "Subscription",
            }
            resp = requests.post(
                f"{base}/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            return ChargeResult(
                success=False,
                provider_ref=data.get("CheckoutRequestID", ""),
                status="pending",
                requires_action=True,
                action_detail={"message": "STK push sent.", "raw": data},
            )
        except Exception as exc:
            raise PaymentError(f"M-PESA STK push failed: {exc}") from exc

    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookResult:
        import json

        data = json.loads(body or b"{}")
        # Daraja STK callback shape: {"Body": {"stkCallback": {...}}}
        callback = data.get("Body", {}).get("stkCallback", {})
        result_code = callback.get("ResultCode", 0)
        checkout_id = callback.get("CheckoutRequestID", "")
        normalized = "payment.succeeded" if result_code == 0 else "payment.failed"
        return WebhookResult(
            event_id=checkout_id or uuid.uuid4().hex,
            event_type=f"mpesa.stk.{result_code}",
            normalized_type=normalized,
            provider_ref=checkout_id,
            raw=data,
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
        """M-PESA reversals are never synchronous.

        Safaricom queues a reversal for approval and confirms it out-of-band,
        so the honest return is always `pending` — the refund is settled by a
        later webhook, not by this call. Reporting success here would tell a
        customer their money was returned before Safaricom had agreed to
        return it.
        """
        amount_kes = max(1, round(amount_minor / 100))
        if not _mpesa_configured():
            return RefundResult(
                success=False,
                provider_ref=f"reversal_sandbox_{uuid.uuid4().hex[:16]}",
                status="pending",
                metadata={"sandbox": True, "amount_kes": amount_kes},
            )
        try:  # pragma: no cover - network path
            import requests

            token = self._access_token()
            base = getattr(settings, "MPESA_API_BASE", "https://sandbox.safaricom.co.ke")
            resp = requests.post(
                f"{base}/mpesa/reversal/v1/request",
                json={
                    "CommandID": "TransactionReversal",
                    "TransactionID": charge_ref,
                    "Amount": amount_kes,
                    "ReceiverParty": settings.MPESA_SHORTCODE,
                    "RecieverIdentifierType": "11",
                    "Remarks": (reason or "Refund")[:100],
                    "QueueTimeOutURL": getattr(settings, "MPESA_CALLBACK_URL", ""),
                    "ResultURL": getattr(settings, "MPESA_CALLBACK_URL", ""),
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return RefundResult(
                success=False,
                provider_ref=data.get("ConversationID", ""),
                status="pending",
                metadata=data,
            )
        except Exception as exc:  # pragma: no cover - network path
            raise PaymentError(f"M-PESA could not queue the reversal: {exc}") from exc
