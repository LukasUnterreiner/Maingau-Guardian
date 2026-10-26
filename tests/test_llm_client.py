"""LLM client wire format against the hessian.AI Inference API handout (no network)."""
from __future__ import annotations

import logging

import httpx
import pytest

from app.config.settings import AppSettings
from app.services.llm_client import LLMClient, LLMUnavailable

KEY = "sk-test-0000-not-a-real-key"


def _settings(**kw) -> AppSettings:
    base = {"AI_API_KEY": KEY, "AI_BASE_URL": "https://hip-gw.hessian.ai/v1", "AI_MODEL": "vllm/Kolibri-1"}
    return AppSettings(**{**base, **kw})


class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "https://x"), response=None)

    def json(self):
        return self.payload


def _reply(content):
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def test_request_matches_the_hessian_ai_handout(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, body=json, headers=headers)
        return _Resp(_reply("Hallo!"))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LLMClient(_settings())
    assert client.complete([{"role": "user", "content": "Sag Hallo"}]) == "Hallo!"
    assert seen["url"] == "https://hip-gw.hessian.ai/v1/chat/completions"
    assert seen["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert seen["body"]["model"] == "vllm/Kolibri-1" and seen["body"]["messages"][0]["content"] == "Sag Hallo"
    status = client.status()
    assert status["enabled"] and status["protocol_verified"] is True and KEY not in str(status)


def test_unknown_gateway_is_not_reported_as_verified():
    assert LLMClient(_settings(AI_BASE_URL="https://llm.example.org/v1")).status()["protocol_verified"] is False


@pytest.mark.parametrize("content", ['<think>\nerst nachdenken\n</think>\n{"answer": "ok"}',
                                     'nachdenken ohne Anfang</think>{"answer": "ok"}'])
def test_reasoning_blocks_are_removed(monkeypatch, content):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(_reply(content)))
    assert LLMClient(_settings()).complete([{"role": "user", "content": "x"}]) == '{"answer": "ok"}'


@pytest.mark.parametrize("resp", [_Resp({"error": "bad key"}, 401), _Resp({"choices": []}), _Resp(_reply(None)),
                                  _Resp(_reply("<think>nur Gedanken</think>"))])
def test_failures_raise_without_leaking_the_key(monkeypatch, caplog, resp):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: resp)
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMUnavailable) as err:
        LLMClient(_settings()).complete([{"role": "user", "content": "x"}])
    assert KEY not in str(err.value) and KEY not in caplog.text


def test_network_failure_pauses_calls_and_uses_a_short_connect_timeout(monkeypatch):
    calls = []

    def unreachable(url, json, headers, timeout):
        calls.append(timeout)
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", unreachable)
    client = LLMClient(_settings(AI_CONNECT_TIMEOUT_S="3", AI_COOLDOWN_S="60"))
    for _ in range(3):
        with pytest.raises(LLMUnavailable):
            client.complete([{"role": "user", "content": "x"}])
    assert len(calls) == 1 and calls[0].connect == 3  # later calls fall back without waiting
    assert client.status()["paused_after_network_error_s"] > 0

    client._paused_until = 0  # pause over: the next call tries the gateway again
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(_reply("wieder da")))
    assert client.complete([{"role": "user", "content": "x"}]) == "wieder da"
