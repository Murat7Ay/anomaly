"""LLM providers behind one narrow interface: system + user prompt in, schema-valid JSON out.

The model never decides anything in this system. Providers are swappable so an organisation can run an
on-prem model (OpenAI-compatible server such as vLLM) or Claude via the official Anthropic SDK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from loadguard.core.config import Settings, get_settings

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"


class AiUnavailable(Exception):
    """No provider configured, provider failed, or the model declined. Callers fall back to rules."""


@dataclass(frozen=True)
class AiResult:
    data: dict[str, Any]
    provider: str
    model: str | None


class LlmProvider(Protocol):
    name: str

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> AiResult: ...


class NullProvider:
    name = "none"

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> AiResult:
        raise AiUnavailable("AI sağlayıcısı yapılandırılmamış")


class AnthropicProvider:
    """Claude via the official SDK, structured JSON output, server-side refusal fallback enabled."""

    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        import anthropic

        self._anthropic = anthropic
        key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else None
        self._client = (
            anthropic.Anthropic(api_key=key, timeout=settings.ai_timeout_seconds)
            if key
            else anthropic.Anthropic(timeout=settings.ai_timeout_seconds)
        )
        self._model = settings.ai_model or DEFAULT_CLAUDE_MODEL

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> AiResult:
        a = self._anthropic
        try:
            resp = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            )
        except a.RateLimitError as e:
            raise AiUnavailable("AI hız sınırına takıldı") from e
        except a.APIStatusError as e:
            raise AiUnavailable(f"AI servis hatası ({e.status_code})") from e
        except a.APIConnectionError as e:
            raise AiUnavailable("AI servisine bağlanılamadı") from e
        if resp.stop_reason == "refusal":
            raise AiUnavailable("Model isteği yanıtlamadı")
        if resp.stop_reason == "max_tokens":
            raise AiUnavailable("Model yanıtı yarıda kesildi")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return AiResult(json.loads(text), self.name, resp.model)
        except json.JSONDecodeError as e:
            raise AiUnavailable("Model geçersiz JSON döndürdü") from e


class OpenAICompatibleProvider:
    """On-prem model server exposing /v1/chat/completions (vLLM, TGI, Ollama...). Data never leaves the organisation."""

    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_base_url:
            raise ValueError("LG_AI_BASE_URL is required for openai_compatible provider")
        self._url = settings.ai_base_url.rstrip("/") + "/v1/chat/completions"
        self._model = settings.ai_model or "local-model"
        self._timeout = settings.ai_timeout_seconds
        self._headers = (
            {"Authorization": f"Bearer {settings.ai_api_key.get_secret_value()}"}
            if settings.ai_api_key
            else {}
        )

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> AiResult:
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}},
        }
        try:
            r = httpx.post(self._url, json=payload, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            raw = r.json()
            return AiResult(json.loads(raw["choices"][0]["message"]["content"]), self.name, raw.get("model"))
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
            raise AiUnavailable(f"Yerel model hatası: {type(e).__name__}") from e


def get_provider(settings: Settings | None = None) -> LlmProvider:
    settings = settings or get_settings()
    match settings.ai_provider:
        case "anthropic":
            return AnthropicProvider(settings)
        case "openai_compatible":
            return OpenAICompatibleProvider(settings)
        case _:
            return NullProvider()
