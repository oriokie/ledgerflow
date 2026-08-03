"""LLM client — one small HTTP adapter, many providers.

The product does not depend on any AI vendor. This module exists so that a
workspace *may* configure one, and it is built around a deliberate observation:
almost every popular and free-tier LLM service now speaks the OpenAI
chat-completions wire format. Groq, OpenRouter, Together, DeepSeek, Mistral,
Ollama, LM Studio and vLLM are all reachable through the same request shape, so
supporting them is a base URL and a model name — not an SDK each.

Anthropic and Google use their own shapes, so they get small explicit adapters.
That is the whole vendor surface: three request formats covering roughly a dozen
services, and no vendor SDK dependency anywhere in the codebase.

Design rules:

1. **No hard dependency.** Nothing here is imported unless an LLM provider is
   actually configured. The product ships fully functional with `LLM_ENABLED`
   off, which is the default.

2. **Failure is expected and survivable.** Timeouts, rate limits, malformed
   JSON and outages are normal for hosted models. Every call is bounded and
   every caller falls back to the deterministic provider — an unreachable model
   must never mean an unusable product.

3. **The prompt is data, not privilege.** The model receives a summarised
   context and returns candidate text. It cannot reach the database, cannot
   write to the ledger, and its output is validated before it is stored.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings

logger = logging.getLogger("ledgerflow.intelligence")


class LLMError(Exception):
    """Any failure reaching or parsing a model. Always caught by callers."""


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Connection defaults for a known service.

    `wire` selects the request/response shape, not the vendor: everything that
    speaks OpenAI's format shares one adapter regardless of who runs it.
    """

    label: str
    base_url: str
    wire: str  # "openai" | "anthropic" | "google"
    default_model: str
    #: False for services that run locally and need no credential.
    requires_key: bool = True
    #: Free tier available without payment details, for the settings UI.
    free_tier: bool = False
    docs_url: str = ""


#: Popular and free-tier services, keyed by the value of `LLM_PROVIDER`.
#:
#: Presets are a convenience, never a constraint — `LLM_BASE_URL` and
#: `LLM_MODEL` override any of them, and `custom` exists precisely so an
#: unlisted OpenAI-compatible endpoint needs no code change.
PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset(
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        wire="openai",
        default_model="gpt-4o-mini",
        docs_url="https://platform.openai.com/docs",
    ),
    "anthropic": ProviderPreset(
        label="Anthropic",
        base_url="https://api.anthropic.com/v1",
        wire="anthropic",
        default_model="claude-3-5-haiku-latest",
        docs_url="https://docs.anthropic.com",
    ),
    "google": ProviderPreset(
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        wire="google",
        default_model="gemini-1.5-flash",
        free_tier=True,
        docs_url="https://ai.google.dev",
    ),
    "groq": ProviderPreset(
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        wire="openai",
        default_model="llama-3.3-70b-versatile",
        free_tier=True,
        docs_url="https://console.groq.com/docs",
    ),
    "openrouter": ProviderPreset(
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        wire="openai",
        default_model="meta-llama/llama-3.3-70b-instruct:free",
        free_tier=True,
        docs_url="https://openrouter.ai/docs",
    ),
    "together": ProviderPreset(
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        wire="openai",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        free_tier=True,
        docs_url="https://docs.together.ai",
    ),
    "deepseek": ProviderPreset(
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        wire="openai",
        default_model="deepseek-chat",
        docs_url="https://api-docs.deepseek.com",
    ),
    "mistral": ProviderPreset(
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        wire="openai",
        default_model="mistral-small-latest",
        free_tier=True,
        docs_url="https://docs.mistral.ai",
    ),
    "ollama": ProviderPreset(
        label="Ollama (local)",
        base_url="http://localhost:11434/v1",
        wire="openai",
        default_model="llama3.2",
        requires_key=False,
        free_tier=True,
        docs_url="https://ollama.com",
    ),
    "lmstudio": ProviderPreset(
        label="LM Studio (local)",
        base_url="http://localhost:1234/v1",
        wire="openai",
        default_model="local-model",
        requires_key=False,
        free_tier=True,
        docs_url="https://lmstudio.ai",
    ),
    "custom": ProviderPreset(
        label="Custom (OpenAI-compatible)",
        base_url="",
        wire="openai",
        default_model="",
        requires_key=False,
    ),
}


@dataclass(frozen=True, slots=True)
class LLMConfig:
    provider: str
    label: str
    base_url: str
    wire: str
    model: str
    api_key: str
    timeout_seconds: int
    max_output_tokens: int
    enabled: bool
    #: Whether the operator has consented to sending financial summaries out.
    share_financial_context: bool

    @property
    def is_local(self) -> bool:
        """Local endpoints never leave the machine, so the privacy gate below
        doesn't apply to them."""
        return "localhost" in self.base_url or "127.0.0.1" in self.base_url


def get_llm_config() -> LLMConfig:
    """Resolve LLM settings, preset defaults filled in where unset."""
    provider = getattr(settings, "LLM_PROVIDER", "custom") or "custom"
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])

    return LLMConfig(
        provider=provider,
        label=preset.label,
        base_url=(getattr(settings, "LLM_BASE_URL", "") or preset.base_url).rstrip("/"),
        wire=preset.wire,
        model=getattr(settings, "LLM_MODEL", "") or preset.default_model,
        api_key=getattr(settings, "LLM_API_KEY", "") or "",
        timeout_seconds=int(getattr(settings, "LLM_TIMEOUT_SECONDS", 20)),
        max_output_tokens=int(getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 1500)),
        enabled=bool(getattr(settings, "LLM_ENABLED", False)),
        share_financial_context=bool(getattr(settings, "LLM_SHARE_FINANCIAL_CONTEXT", False)),
    )


def llm_available() -> tuple[bool, str]:
    """Whether an LLM call can be attempted, and why not if it can't.

    The reason string is surfaced in settings so an operator who switched the
    feature on and saw nothing happen gets told what's missing, rather than
    silence.
    """
    config = get_llm_config()
    if not config.enabled:
        return False, "LLM features are turned off."
    if not config.base_url:
        return False, "No base URL configured for the selected provider."
    if not config.model:
        return False, "No model name configured."

    preset = PROVIDER_PRESETS.get(config.provider)
    if preset and preset.requires_key and not config.api_key:
        return False, f"{preset.label} needs an API key."

    # Sending a household's spending to a third party is a decision the operator
    # must make explicitly. Local models are exempt: nothing leaves the machine.
    if not config.is_local and not config.share_financial_context:
        return False, (
            "Sending financial context to an external provider hasn't been enabled. "
            "Turn on LLM_SHARE_FINANCIAL_CONTEXT to allow it, or use a local model."
        )
    return True, ""


def _post(url: str, *, headers: dict, payload: dict, timeout: int) -> dict:
    """Single HTTP entry point.

    `requests` is already a dependency; no vendor SDK is introduced. Every
    non-2xx or unparseable response becomes an `LLMError`, which callers treat
    as "fall back to the deterministic provider".
    """
    import requests

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except Exception as exc:
        raise LLMError(f"request failed: {exc}") from exc

    if response.status_code >= 400:
        raise LLMError(f"provider returned {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError("provider returned a non-JSON body") from exc


def complete(*, system: str, user: str, config: LLMConfig | None = None) -> str:
    """Send one prompt, return the model's text.

    Stateless and single-turn by design: the coach has no conversation to
    maintain, and a stateless call is trivially retryable and cacheable.
    """
    config = config or get_llm_config()

    if config.wire == "anthropic":
        data = _post(
            f"{config.base_url}/messages",
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload={
                "model": config.model,
                "max_tokens": config.max_output_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=config.timeout_seconds,
        )
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    if config.wire == "google":
        # Google takes the key as a query parameter and has no system role;
        # the system prompt is prepended to the user turn instead.
        data = _post(
            f"{config.base_url}/models/{config.model}:generateContent?key={config.api_key}",
            headers={"content-type": "application/json"},
            payload={
                "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
                "generationConfig": {"maxOutputTokens": config.max_output_tokens},
            },
            timeout=config.timeout_seconds,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("no candidates returned")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    # OpenAI-compatible: the majority case.
    headers = {"content-type": "application/json"}
    if config.api_key:
        headers["authorization"] = f"Bearer {config.api_key}"
    data = _post(
        f"{config.base_url}/chat/completions",
        headers=headers,
        payload={
            "model": config.model,
            "max_tokens": config.max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=config.timeout_seconds,
    )
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("no choices returned")
    return choices[0].get("message", {}).get("content", "")


def complete_json(*, system: str, user: str, config: LLMConfig | None = None) -> Any:
    """Send a prompt and parse the reply as JSON.

    Models routinely wrap JSON in prose or a markdown fence despite being asked
    not to, so the outermost bracketed span is extracted before parsing. This is
    pragmatic rather than strict: refusing slightly-wrapped-but-valid output
    would make the feature flaky for no benefit, while anything genuinely
    malformed still raises and triggers the fallback.
    """
    raw = complete(system=system, user=user, config=config)
    if not raw or not raw.strip():
        raise LLMError("empty response")

    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        # The fenced block is the odd-indexed segment; drop a leading "json".
        if len(parts) >= 2:
            block = parts[1]
            text = block[4:] if block.lstrip().lower().startswith("json") else block
            text = text.strip()

    start = min(
        (i for i in (text.find("["), text.find("{")) if i != -1),
        default=-1,
    )
    if start == -1:
        raise LLMError("no JSON found in response")
    end = max(text.rfind("]"), text.rfind("}"))
    if end <= start:
        raise LLMError("unterminated JSON in response")

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON: {exc}") from exc
