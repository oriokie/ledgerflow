"""A workspace can point itself at a different model.

`Tenant.ai_enabled` lets an owner decline AI; this lets them substitute it —
a household that would rather run a local model than send anything to a vendor,
or one spending its own provider quota. Owner-gated for the same reason
`ai_enabled` is: choosing where a household's finances go is decided for
everyone in it, not by whichever member opened a settings page.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.intelligence.llm import get_llm_config
from apps.platform_admin import settings_store
from apps.tenancy.models import TenantAISettings

pytestmark = pytest.mark.django_db


# ------------------------------------------------ the platform layer is read
@override_settings(LLM_PROVIDER="openai", LLM_MODEL="gpt-env", LLM_ENABLED=True)
def test_the_console_setting_actually_reaches_the_model_client():
    """The regression this file exists for: the console had offered provider
    and model fields since the settings store was built, and nothing read them
    — an operator could fill the form in, save, and change nothing at all."""
    settings_store.set_value(key="ai.model", raw="gpt-from-console")
    assert get_llm_config().model == "gpt-from-console"


@override_settings(LLM_MODEL="gpt-env", LLM_ENABLED=True)
def test_the_environment_still_applies_when_the_console_is_silent():
    assert get_llm_config().model == "gpt-env"


@override_settings(LLM_ENABLED=False)
def test_the_platform_owns_the_master_switch():
    settings_store.set_value(key="ai.enabled", raw="true")
    assert get_llm_config().enabled is True


# --------------------------------------------------- the workspace layer
@override_settings(LLM_PROVIDER="openai", LLM_MODEL="gpt-env", LLM_ENABLED=True)
def test_a_workspace_override_wins_over_the_platform(tenant_context):
    membership, _ = tenant_context
    settings_store.set_value(key="ai.model", raw="gpt-from-console")
    row = TenantAISettings.objects.create(tenant=membership.tenant, provider="ollama", model="llama3")

    config = get_llm_config(tenant_id=row.tenant_id)
    assert config.provider == "ollama"
    assert config.model == "llama3"


@override_settings(LLM_PROVIDER="openai", LLM_MODEL="gpt-env", LLM_ENABLED=True)
def test_a_caller_without_a_tenant_gets_the_platform_answer(tenant_context):
    membership, _ = tenant_context
    TenantAISettings.objects.create(tenant=membership.tenant, provider="ollama", model="llama3")

    assert get_llm_config().model == "gpt-env"


@override_settings(LLM_ENABLED=False)
def test_a_workspace_cannot_switch_ai_on_for_itself(tenant_context):
    """A workspace may decline AI or substitute the model. Granting itself AI
    the operator turned off would override a cost and data-processing decision
    that was never the workspace's to make."""
    membership, _ = tenant_context
    row = TenantAISettings.objects.create(tenant=membership.tenant, provider="ollama", model="llama3")

    assert get_llm_config(tenant_id=row.tenant_id).enabled is False


def test_a_blank_override_falls_through(tenant_context):
    """A row that exists but chose nothing must not shadow the platform with
    empty strings."""
    membership, _ = tenant_context
    TenantAISettings.objects.create(tenant=membership.tenant)

    with override_settings(LLM_MODEL="gpt-env", LLM_ENABLED=True):
        assert get_llm_config(tenant_id=membership.tenant_id).model == "gpt-env"


# ------------------------------------------------------------------- the key
def test_the_workspace_key_is_encrypted_at_rest(tenant_context):
    membership, _ = tenant_context
    row = TenantAISettings(tenant=membership.tenant, provider="openai")
    row.set_api_key("sk-workspace-secret")
    row.save()

    row.refresh_from_db()
    assert "sk-workspace-secret" not in row.encrypted_api_key
    assert row.api_key == "sk-workspace-secret"


def test_an_unreadable_key_does_not_break_every_ai_call(tenant_context):
    """A key encrypted under a rotated FIELD_ENCRYPTION_KEY is unreadable, not
    a reason to raise on every coach request in the workspace."""
    membership, _ = tenant_context
    row = TenantAISettings.objects.create(tenant=membership.tenant, encrypted_api_key="not-valid-ciphertext")
    assert row.api_key == ""


# ------------------------------------------------------------------- the API
def test_an_owner_can_read_and_set_it(tenant_context):
    membership, client = tenant_context
    url = f"/api/v1/tenancy/workspaces/{membership.tenant_id}/ai/"

    assert client.get(url).data["provider"] == ""

    resp = client.put(url, {"provider": "ollama", "model": "llama3"}, format="json")
    assert resp.status_code == 200
    assert resp.data["provider"] == "ollama"
    assert client.get(url).data["model"] == "llama3"


def test_the_key_is_never_read_back(tenant_context):
    membership, client = tenant_context
    url = f"/api/v1/tenancy/workspaces/{membership.tenant_id}/ai/"
    resp = client.put(url, {"provider": "openai", "api_key": "sk-secret"}, format="json")

    assert "api_key" not in resp.data
    assert resp.data["api_key_set"] is True
    assert "sk-secret" not in str(resp.data)


def test_saving_another_field_does_not_wipe_the_key(tenant_context):
    """Absent means "leave it alone"; only an explicit empty string clears."""
    membership, client = tenant_context
    url = f"/api/v1/tenancy/workspaces/{membership.tenant_id}/ai/"
    client.put(url, {"provider": "openai", "api_key": "sk-secret"}, format="json")

    client.put(url, {"provider": "openai", "model": "gpt-4o"}, format="json")
    assert client.get(url).data["api_key_set"] is True


def test_an_unknown_provider_is_refused(tenant_context):
    membership, client = tenant_context
    url = f"/api/v1/tenancy/workspaces/{membership.tenant_id}/ai/"
    resp = client.put(url, {"provider": "definitely-not-a-provider"}, format="json")

    assert resp.status_code == 400
