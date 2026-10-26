"""Provider-neutral LLM client used by Lighty's explanations, drafts and copilot.

One wire format is implemented: ``AI_PROTOCOL=openai_chat_completions``
(POST {AI_BASE_URL}{AI_CHAT_PATH} with ``{AI_AUTH_HEADER}: {AI_AUTH_SCHEME} <key>``).
It was checked against the hessian.AI Inference API handout for the Futury
Build Days (endpoint ``https://hip-gw.hessian.ai/v1``, route ``/chat/completions``,
API key as Bearer token, models ``vllm/Kolibri-1`` and ``vllm/GLM-Flash:Latest``).
``status()`` reports ``protocol_verified`` only for gateways whose documentation
has been checked. Path and auth header stay configurable for other gateways.
Any other protocol value disables the client and every caller uses its
deterministic fallback.

A network failure (gateway unreachable, connect or read timeout) pauses AI calls
for ``AI_COOLDOWN_S`` so callers fall back immediately instead of waiting on
every request; the next call after the pause tries again.

The API key is held as a SecretStr. Errors are logged by exception type only, so
neither the key nor prompt content ends up in logs.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.config.settings import AppSettings

log = logging.getLogger("lighty.llm")

SUPPORTED_PROTOCOLS = {"openai_chat_completions"}
# Gateways whose request format was checked against their documentation.
VERIFIED_GATEWAYS = {("openai_chat_completions", "hip-gw.hessian.ai")}
# Reasoning models served by vLLM may prepend their chain of thought; it is never shown or validated as the answer.
_THINK_RE = re.compile(r"<think>.*?</think>|^.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMUnavailable(RuntimeError):
    """The model could not be reached or returned an unusable response."""


class ChatModel(Protocol):
    enabled: bool

    def complete(self, messages: list[dict[str, str]], max_tokens: int | None = None,
                 temperature: float = 0.2) -> str: ...


class LLMClient:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._paused_until = 0.0  # time.monotonic() until which calls are skipped after a network failure

    @property
    def enabled(self) -> bool:
        return self.settings.ai_configured and self.settings.ai_protocol in SUPPORTED_PROTOCOLS

    def status(self) -> dict[str, Any]:
        s = self.settings
        host = urlparse(s.ai_base_url or "").hostname
        return {"configured": s.ai_configured, "protocol": s.ai_protocol, "enabled": self.enabled,
                "protocol_verified": (s.ai_protocol, host) in VERIFIED_GATEWAYS,
                "model": s.ai_model if s.ai_configured else None,
                "paused_after_network_error_s": max(0, round(self._paused_until - time.monotonic()))}

    def complete(self, messages: list[dict[str, str]], max_tokens: int | None = None,
                 temperature: float = 0.2) -> str:
        if not self.enabled:
            raise LLMUnavailable("AI integration not configured")
        if time.monotonic() < self._paused_until:
            raise LLMUnavailable("AI paused after a recent network error")
        s = self.settings
        url = s.ai_base_url.rstrip("/") + "/" + s.ai_chat_path.lstrip("/")
        key = s.ai_api_key.get_secret_value()
        headers = {s.ai_auth_header: f"{s.ai_auth_scheme} {key}".strip()}
        body = {"model": s.ai_model, "temperature": temperature, "max_tokens": max_tokens or s.ai_max_tokens,
                "messages": messages}
        try:
            resp = httpx.post(url, json=body, headers=headers,
                              timeout=httpx.Timeout(s.ai_timeout_s, connect=s.ai_connect_timeout_s))
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except httpx.TransportError as exc:
            self._paused_until = time.monotonic() + s.ai_cooldown_s
            log.warning("AI call failed: %s; pausing AI calls for %.0f s", type(exc).__name__, s.ai_cooldown_s)
            raise LLMUnavailable(f"AI call failed: {type(exc).__name__}") from None
        except Exception as exc:  # never include headers (key) or bodies in the log
            log.warning("AI call failed: %s", type(exc).__name__)
            raise LLMUnavailable(f"AI call failed: {type(exc).__name__}") from None
        if isinstance(content, str):
            content = _THINK_RE.sub("", content, count=1)
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailable("AI returned an empty response")
        return content.strip()
