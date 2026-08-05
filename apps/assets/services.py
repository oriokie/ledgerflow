"""Write operations on assets.

Nothing here posts to the ledger, and that is the design rather than an
omission. An asset's worth changes because somebody re-estimated it, not because
money moved, and the ledger's whole claim is that every figure in it traces to a
posting. See the note in `models.py`.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from .models import Asset, AssetKind, Valuation, ValuationSource


class AssetError(ValueError):
    """A write that would produce an asset record the product cannot defend."""


@transaction.atomic
def create_asset(
    *,
    name: str,
    currency: str,
    kind: str = AssetKind.OTHER,
    description: str = "",
    acquired_on: date | None = None,
    acquisition_cost_minor: int | None = None,
    secured_by_debt=None,
    include_in_net_worth: bool = True,
    notes: str = "",
    initial_value_minor: int | None = None,
) -> Asset:
    """Record something owned.

    `initial_value_minor` is a convenience: most people adding a house know
    roughly what it is worth today, and making them add the asset and then
    value it as a second step is the friction that leaves assets unvalued —
    which is precisely the state that makes the net-worth total wrong.
    """
    if not name.strip():
        raise AssetError("An asset needs a name.")
    if acquisition_cost_minor is not None and acquisition_cost_minor < 0:
        raise AssetError("What it cost cannot be negative.")
    if secured_by_debt is not None:
        from apps.finance.services import _LIABILITY_TYPES

        if secured_by_debt.account_type not in _LIABILITY_TYPES:
            raise AssetError("An asset can only be secured by a loan or a credit account.")

    asset = Asset.objects.create(
        name=name.strip(),
        kind=kind,
        currency=currency.upper(),
        description=description,
        acquired_on=acquired_on,
        acquisition_cost_minor=acquisition_cost_minor,
        secured_by_debt=secured_by_debt,
        include_in_net_worth=include_in_net_worth,
        notes=notes,
    )

    if initial_value_minor is not None:
        record_valuation(
            asset=asset,
            value_minor=initial_value_minor,
            as_of=date.today(),
            source=ValuationSource.OWNER,
        )
    return asset


@transaction.atomic
def update_asset(*, asset: Asset, **changes) -> Asset:
    """Edit an asset.

    ``currency`` is absent by design, the same refusal income sources, savings
    goals and receivables make: every valuation already recorded is denominated
    in it, so changing it would reinterpret history rather than correct it.
    """
    allowed = {
        "name",
        "kind",
        "description",
        "acquired_on",
        "acquisition_cost_minor",
        "secured_by_debt",
        "include_in_net_worth",
        "notes",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise AssetError(f"Cannot change {', '.join(sorted(unknown))} on an existing asset.")

    for field, value in changes.items():
        setattr(asset, field, value)

    if not asset.name.strip():
        raise AssetError("An asset needs a name.")
    if asset.acquisition_cost_minor is not None and asset.acquisition_cost_minor < 0:
        raise AssetError("What it cost cannot be negative.")
    if asset.secured_by_debt is not None:
        from apps.finance.services import _LIABILITY_TYPES

        if asset.secured_by_debt.account_type not in _LIABILITY_TYPES:
            raise AssetError("An asset can only be secured by a loan or a credit account.")

    asset.save()
    return asset


@transaction.atomic
def delete_asset(*, asset: Asset) -> None:
    """Remove an asset. Soft-deleted, so a mis-keyed entry can be reversed
    without taking its valuation history with it."""
    asset.delete()


@transaction.atomic
def record_valuation(
    *,
    asset: Asset,
    value_minor: int,
    as_of: date | None = None,
    source: str = ValuationSource.OWNER,
    notes: str = "",
) -> Valuation:
    """Record what the asset is judged to be worth.

    A second valuation on a date that already has one **replaces** it. Two
    judgements about the same day are a correction, not two data points, and
    keeping both would let the interpolation draw a line between a figure and
    its own correction.
    """
    if value_minor < 0:
        raise AssetError("A valuation cannot be negative.")
    as_of = as_of or date.today()
    if asset.acquired_on and as_of < asset.acquired_on:
        raise AssetError("An asset cannot be valued before it was acquired.")

    existing = Valuation.objects.filter(asset=asset, as_of=as_of).first()
    if existing is not None:
        existing.value_minor = value_minor
        existing.source = source
        existing.notes = notes
        existing.save(update_fields=["value_minor", "source", "notes", "updated_at"])
        return existing

    return Valuation.objects.create(
        asset=asset, as_of=as_of, value_minor=value_minor, source=source, notes=notes
    )


@transaction.atomic
def delete_valuation(*, valuation: Valuation) -> None:
    """Remove one judgement. The rest of the history, and the interpolation
    through it, simply re-derives without it."""
    valuation.delete()
