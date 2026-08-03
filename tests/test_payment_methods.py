"""Managing saved payment methods after they're added.

Adding a method could always set it as the default; nothing could change that
afterwards. These tests cover promotion, and the quieter problem underneath it:
deleting the default used to leave a workspace with several methods and no
default at all, which silently changed which card renewals would charge.
"""

from __future__ import annotations

import pytest

from apps.billing import services
from apps.billing.models import PaymentMethod
from apps.tenancy.models import Role
from tests.conftest import _bearer_client as _bearer
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _add_card(client, token="tok_visa", make_default=True):
    resp = client.post(
        "/api/v1/billing/payment-methods/",
        {"provider": "stripe", "token": token, "kind": "card", "make_default": make_default},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.json()["id"]


def _owner():
    m = MembershipFactory(role=Role.OWNER)
    return m, _bearer(m.user, m.tenant_id)


def test_promoting_a_method_demotes_the_previous_default():
    m, client = _owner()
    first = _add_card(client, "tok_visa")
    second = _add_card(client, "tok_mc")

    # The second was added as default, so promoting the first is a real change.
    resp = client.patch(f"/api/v1/billing/payment-methods/{first}/", {}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.json()["is_default"] is True

    defaults = PaymentMethod.objects.filter(tenant_id=m.tenant_id, is_default=True)
    assert defaults.count() == 1
    assert str(defaults.first().id) == first
    assert str(PaymentMethod.objects.get(id=second).id) == second
    assert PaymentMethod.objects.get(id=second).is_default is False


def test_promoting_the_current_default_is_a_no_op():
    m, client = _owner()
    only = _add_card(client)

    resp = client.patch(f"/api/v1/billing/payment-methods/{only}/", {}, format="json")
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True
    assert PaymentMethod.objects.filter(tenant_id=m.tenant_id, is_default=True).count() == 1


def test_promoting_an_unknown_method_is_not_found():
    _m, client = _owner()
    resp = client.patch(
        "/api/v1/billing/payment-methods/00000000-0000-0000-0000-000000000000/", {}, format="json"
    )
    assert resp.status_code == 404


def test_a_workspace_cannot_promote_another_workspaces_method():
    _m_a, client_a = _owner()
    m_b, client_b = _owner()
    theirs = _add_card(client_b)

    resp = client_a.patch(f"/api/v1/billing/payment-methods/{theirs}/", {}, format="json")
    assert resp.status_code == 404
    # And theirs is untouched.
    assert PaymentMethod.objects.get(id=theirs).is_default is True
    assert PaymentMethod.objects.get(id=theirs).tenant_id == m_b.tenant_id


def test_removing_the_default_promotes_a_successor():
    m, client = _owner()
    first = _add_card(client, "tok_visa")
    second = _add_card(client, "tok_mc")  # becomes default

    resp = client.delete(f"/api/v1/billing/payment-methods/{second}/")
    assert resp.status_code == 204

    remaining = PaymentMethod.objects.filter(tenant_id=m.tenant_id)
    assert remaining.count() == 1
    # Without promotion the workspace would hold a card that isn't the default,
    # and renewal would fall back to it without the user ever choosing it.
    assert remaining.first().is_default is True
    assert str(remaining.first().id) == first


def test_removing_a_non_default_leaves_the_default_alone():
    m, client = _owner()
    first = _add_card(client, "tok_visa")
    second = _add_card(client, "tok_mc")  # default

    resp = client.delete(f"/api/v1/billing/payment-methods/{first}/")
    assert resp.status_code == 204

    defaults = PaymentMethod.objects.filter(tenant_id=m.tenant_id, is_default=True)
    assert defaults.count() == 1
    assert str(defaults.first().id) == second


def test_removing_the_only_method_leaves_nothing_behind():
    m, client = _owner()
    only = _add_card(client)

    assert client.delete(f"/api/v1/billing/payment-methods/{only}/").status_code == 204
    assert PaymentMethod.objects.filter(tenant_id=m.tenant_id).count() == 0


def test_removing_an_unknown_method_is_quietly_idempotent():
    _m, client = _owner()
    resp = client.delete("/api/v1/billing/payment-methods/00000000-0000-0000-0000-000000000000/")
    assert resp.status_code == 204


def test_a_member_cannot_change_payment_methods():
    """Billing is an admin concern; a viewer must not be able to reroute it."""
    m = MembershipFactory(role=Role.MEMBER)
    client = _bearer(m.user, m.tenant_id)
    resp = client.patch(
        "/api/v1/billing/payment-methods/00000000-0000-0000-0000-000000000000/", {}, format="json"
    )
    assert resp.status_code == 403


def test_service_promotion_is_atomic_about_the_single_default():
    """Directly at the service layer, since the invariant is a data one."""
    m, client = _owner()
    ids = [_add_card(client, f"tok_{i}") for i in range(3)]

    for pm_id in ids:
        services.set_default_payment_method(tenant_id=m.tenant_id, payment_method_id=pm_id)
        defaults = PaymentMethod.objects.filter(tenant_id=m.tenant_id, is_default=True)
        assert defaults.count() == 1
        assert str(defaults.first().id) == pm_id
