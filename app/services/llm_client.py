"""Provider-neutral LLM client used by Lighty's explanations, drafts and copilot.

The provider protocol has NOT been verified against hessian.AI documentation.
Only one wire format is implemented: ``AI_PROTOCOL=openai_chat_completions``
(POST {AI_BASE_URL}{AI_CHAT_PATH} with ``{AI_AUTH_HEADER}: {AI_AUTH_SCHEME} <key>``),
because many hosted gateways expose it. Path and auth header are configurable so
a gateway can be adapted once its documentation has been checked. Any other
protocol value disables the client and every caller uses its deterministic
fallback.

The API key is held as a SecretStr. Errors are logged by exception type only, so
neither the key nor prompt content ends up in logs.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from app.config.settings import AppSettings

log = logging.getLogger("lighty.llm")

SUPPORTED_PROTOCOLS = {"openai_chat_completions"}


class LLMUnavailable(RuntimeError):
    """The model could not be reached or returned an unusable response."""


class ChatModel(Protocol):
    enabled: bool

    def complete(self, messages: list[dict[str, str]], max_tokens: int | None = None,
                 temperature: float = 0.2) -> str: ...


class LLMClient:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return self.settings.ai_configured and self.settings.ai_protocol in SUPPORTED_PROTOCOLS

    def status(self) -> dict[str, Any]:
        s = self.settings
        return {"configured": s.ai_configured, "protocol": s.ai_protocol, "enabled": self.enabled,
                "protocol_verified": False, "model": s.ai_model if s.ai_configured else None}

    def complete(self, messages: list[dict[str, str]], max_tokens: int | None = None,
                 temperature: float = 0.2) -> str:
        if not self.enabled:
            raise LLMUnavailable("AI integration not configured")
        s = self.settings
        url = s.ai_base_url.rstrip("/") + "/" + s.ai_chat_path.lstrip("/")
        key = s.ai_api_key.get_secret_value()
        headers = {s.ai_auth_header: f"{s.ai_auth_scheme} {key}".strip()}
        body = {"model": s.ai_model, "temperature": temperature, "max_tokens": max_tokens or s.ai_max_tokens,
                "messages": messages}
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=s.ai_timeout_s)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # never include headers (key) or bodies in the log
            log.warning("AI call failed: %s", type(exc).__name__)
            raise LLMUnavailable(f"AI call failed: {type(exc).__name__}") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailable("AI returned an empty response")
        return content.strip()
