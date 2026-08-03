"""Wallet service layer.

A Wallet never touches the ledger — it's a pure grouping/presentation layer
over FinancialAccounts that already exist and already post their own
balanced entries. See the `Wallet` model docstring for why this is
deliberately NOT a new accounting primitive.
"""

from __future__ import annotations

from django.db import transaction

from .models import FinancialAccount, Wallet


class WalletError(Exception): ...


@transaction.atomic
def create_wallet(*, name: str, icon: str = "", color: str = "", is_default: bool = False) -> Wallet:
    if is_default:
        Wallet.objects.filter(is_default=True).update(is_default=False)
    return Wallet.objects.create(name=name, icon=icon, color=color, is_default=is_default)


@transaction.atomic
def assign_account_to_wallet(
    *, financial_account: FinancialAccount, wallet: Wallet | None
) -> FinancialAccount:
    """`wallet=None` removes the account from any wallet — accounts don't
    have to belong to one."""
    financial_account.wallet = wallet
    financial_account.save(update_fields=["wallet", "updated_at"])
    return financial_account
