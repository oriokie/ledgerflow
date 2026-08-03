"""
Payment-provider abstraction.

Every provider (Stripe, M-PESA, …) implements `PaymentProvider`. The billing
service talks only to this interface, so adding a provider never touches the
service or the models. Providers translate between our domain (integer minor
units, our Subscription/Payment concepts) and their own APIs.

Each method returns a plain dataclass result, never a provider SDK object, so
provider types never leak upward.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChargeResult:
    success: bool
    provider_ref: str
    status: str  # maps to PaymentStatus values: pending | succeeded | failed
    # For async flows (M-PESA STK push, 3-D Secure) the charge isn't final yet;
    # `requires_action` tells the caller to wait for a webhook.
    requires_action: bool = False
    action_detail: dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""


@dataclass(frozen=True)
class PaymentMethodResult:
    provider_ref: str
    kind: str  # card | mpesa
    brand: str = ""
    last4: str = ""
    exp_month: int | None = None
    exp_year: int | None = None
    phone_masked: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundResult:
    """Outcome of asking a provider to return money.

    `pending` is a real, common outcome rather than an error: card networks
    settle refunds asynchronously and M-PESA reversals are queued for operator
    approval. Callers must not treat "not yet succeeded" as "failed".
    """

    success: bool
    provider_ref: str
    status: str  # succeeded | pending | failed
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookResult:
    """Normalized view of a provider webhook the service knows how to apply."""

    event_id: str
    event_type: str
    # What the event is about, normalized to our vocabulary:
    #   "payment.succeeded" | "payment.failed" | "subscription.canceled" | ...
    normalized_type: str
    provider_ref: str  # the charge/subscription id the event concerns
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentError(Exception):
    """Raised for provider-side failures the caller should surface, not crash on."""


class PaymentProvider(abc.ABC):
    """The contract every payment provider implements."""

    #: short stable key stored on Payment.provider etc.
    key: str = ""

    @abc.abstractmethod
    def attach_payment_method(self, *, tenant_id: str, token: str, kind: str) -> PaymentMethodResult:
        """Exchange a client-side token (from the provider's JS/SDK, so raw card
        data never touches our server) for a reusable payment-method reference."""

    @abc.abstractmethod
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
        """Attempt to collect `amount_minor`. May return requires_action=True
        for async confirmation (webhook to follow)."""

    @abc.abstractmethod
    def parse_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookResult:
        """Verify signature and normalize an inbound webhook. Raises
        PaymentError if the signature is invalid."""

    # ---------------------------------------------------------------- refunds
    #: Concrete, not abstract, and defaults to refusing. Refunds arrived after
    #: the first providers shipped, and making the method abstract would have
    #: broken every existing adapter at import time — including any written by
    #: a deployment against this interface. Declining loudly at call time is
    #: the honest behaviour for a provider that genuinely cannot refund
    #: (several mobile-money rails cannot), so the default is also the correct
    #: permanent implementation for some adapters rather than a placeholder.
    supports_refunds: bool = False

    def refund(
        self,
        *,
        charge_ref: str,
        amount_minor: int,
        currency: str,
        reason: str = "",
        idempotency_key: str = "",
    ) -> RefundResult:
        raise PaymentError(f"The {self.key or type(self).__name__} provider does not support refunds.")
