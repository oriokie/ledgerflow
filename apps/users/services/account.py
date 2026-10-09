"""Account-level actions that sit above any one workspace."""

from __future__ import annotations

import logging
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import close_workspace

logger = logging.getLogger(__name__)
User = get_user_model()


class AccountError(Exception):
    pass


@transaction.atomic
def delete_account(*, user, password: str) -> None:
    """Deactivate the account, close owned workspaces, and drop the email.

    Password is required so a stolen session cannot erase someone. The email
    is replaced rather than left on a dead row so the address can be reused
    and so a restore of this table does not resurrect a login.
    """
    if not user.check_password(password):
        raise AccountError("The password is incorrect.")

    owned = list(Membership.objects.filter(user=user, role=Role.OWNER).select_related("tenant"))
    for membership in owned:
        if not membership.tenant.is_active:
            continue
        with use_tenant(membership.tenant_id, actor_id=user.id):
            bind_db_tenant(membership.tenant_id)
            close_workspace(tenant=membership.tenant, actor_membership=membership)

    user.is_active = False
    user.is_verified = False
    user.email = f"deleted+{uuid.uuid4().hex}@invalid.ledgerflow"
    user.set_unusable_password()
    user.save(update_fields=["is_active", "is_verified", "email", "password"])
    logger.info("Account deleted for user %s", user.id)
