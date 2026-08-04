"""Provider registry — resolve a PaymentProvider adapter by its key."""

from __future__ import annotations

from functools import cache

from .base import PaymentProvider
from .mpesa_provider import MpesaProvider
from .stripe_provider import StripeProvider

_PROVIDERS: dict[str, type[PaymentProvider]] = {
    StripeProvider.key: StripeProvider,
    MpesaProvider.key: MpesaProvider,
}


@cache
def get_provider(key: str) -> PaymentProvider:
    try:
        return _PROVIDERS[key]()
    except KeyError as exc:
        raise ValueError(f"Unknown payment provider {key!r}. Known: {sorted(_PROVIDERS)}.") from exc


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)
