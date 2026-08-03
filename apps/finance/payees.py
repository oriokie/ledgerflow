"""Payee service layer. Payees are looked up by a normalized (lowercased,
whitespace-collapsed) name so "Trader Joe's", "trader joe's ", and "TRADER
JOE'S" all resolve to one record — this is what makes payee-based
auto-categorization and spend-by-merchant reports useful instead of
fragmented across near-duplicate names."""

from __future__ import annotations

import re

from django.db import transaction

from .models import Category, Payee


class PayeeError(Exception): ...


def normalize_payee_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


@transaction.atomic
def create_payee(*, name: str, default_category: Category | None = None) -> Payee:
    name = name.strip()
    if not name:
        raise PayeeError("Payee name cannot be blank.")
    normalized = normalize_payee_name(name)
    if Payee.objects.filter(normalized_name=normalized).exists():
        raise PayeeError(f"A payee named {name!r} already exists.")
    return Payee.objects.create(name=name, normalized_name=normalized, default_category=default_category)


@transaction.atomic
def get_or_create_payee(*, name: str, default_category: Category | None = None) -> tuple[Payee, bool]:
    """Idempotent variant for import pipelines: bank feeds report merchant
    names as free text, and re-processing the same feed must not create
    duplicate payees."""
    name = name.strip()
    normalized = normalize_payee_name(name)
    payee = Payee.objects.filter(normalized_name=normalized).first()
    if payee is not None:
        return payee, False
    return (
        Payee.objects.create(name=name, normalized_name=normalized, default_category=default_category),
        True,
    )
