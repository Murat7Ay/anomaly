from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class LlmResponse:
    text: str
    raw_json: dict[str, Any]


class OnPremLlmClient:
    """
    On-prem LLM client using an OpenAI-compatible Chat Completions API.

    Expected endpoint: POST {LLM_BASE_URL}/v1/chat/completions
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def generate(self, *, prompt_text: str) -> LlmResponse:
        url = str(self._settings.llm_base_url).rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": self._settings.llm_model_name,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an internal billing operations analyst. You must be deterministic, factual, and concise.",
                },
                {"role": "user", "content": prompt_text},
            ],
        }

        timeout = httpx.Timeout(self._settings.llm_timeout_seconds)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json()

        # OpenAI-compatible format: choices[0].message.content
        text = ""
        try:
            text = raw["choices"][0]["message"]["content"]
        except Exception:
            text = str(raw)
        return LlmResponse(text=text, raw_json=raw)


