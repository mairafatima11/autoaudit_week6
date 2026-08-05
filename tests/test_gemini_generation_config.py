"""Gemini request shape and response handling.

A small repository was spending ~270s in the Quality/Documentation drafting
phase. The request payload was:

    {"contents": [{"parts": [{"text": prompt}]}]}

with no `generationConfig` at all. For `gemini-2.5-flash` that means
*thinking is enabled by default* — the model does extended internal
reasoning before answering. Nothing here needs it (every prompt is "write
1-2 sentences" or "write a docstring"), and on a batched prompt it was slow
enough to exceed the 60s HTTP timeout, which then triggered the full retry
ladder: 4 attempts x 60s + backoff is ~247s, matching what was observed.

It also meant unbounded output, and `_extract_text` returning `""` for a
response with no parts — which is exactly what a thinking model produces
when the output budget is consumed before it writes anything. That empty
string flowed silently into a finding's description.
"""
from __future__ import annotations

import pytest
import requests

from autoaudit.llm.base import ProviderUnavailable
from autoaudit.llm.batching import DEFAULT_MAX_BATCH_CHARS, chunk_items
from autoaudit.llm.gemini_client import GeminiClient


class _Resp:
    def __init__(self, status_code=200, payload=None, text="{}"):
        self.status_code = status_code
        self.text = text
        self.headers = {}
        self._payload = payload if payload is not None else {
            "candidates": [{"content": {"parts": [{"text": "answer"}]}}]
        }

    def json(self):
        return self._payload


def _capture(monkeypatch, response=None):
    """Capture the outgoing request payload."""
    sent: dict = {}

    def _post(url, params=None, json=None, timeout=None):
        sent["url"] = url
        sent["payload"] = json
        sent["timeout"] = timeout
        return response if response is not None else _Resp()

    monkeypatch.setattr(requests, "post", _post)
    return sent


def _client(model="gemini-2.5-flash", **kwargs):
    kwargs.setdefault("request_delay_ms", 0)
    return GeminiClient(api_key="k", mock=False, model=model, **kwargs)


# --- generation config: 2.x family ------------------------------------------


def test_2x_disables_thinking_with_a_budget(monkeypatch):
    """2.5 Flash thinks by default; `thinkingBudget: 0` turns it off."""
    sent = _capture(monkeypatch)
    _client().complete("hello")

    config = sent["payload"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingBudget": 0}
    assert "thinking" not in config, "3.x-style field must not go to a 2.x model"


def test_2x_still_sends_temperature(monkeypatch):
    sent = _capture(monkeypatch)
    _client().complete("hello")
    assert 0 <= sent["payload"]["generationConfig"]["temperature"] <= 1


def test_output_length_is_bounded(monkeypatch):
    sent = _capture(monkeypatch)
    _client().complete("hello")

    config = sent["payload"]["generationConfig"]
    # Must comfortably fit a full batch of items plus their markers.
    assert config["maxOutputTokens"] >= 2048


def test_thinking_budget_is_configurable(monkeypatch):
    sent = _capture(monkeypatch)
    _client(thinking_budget=512).complete("hello")
    assert sent["payload"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 512}


# --- generation config: 3.x family ------------------------------------------
#
# Gemini 3.x changed the reasoning controls, and mixing generations is not
# harmless: `thinkingBudget` together with `thinkingLevel` is a documented
# 400, and `temperature`/`topP`/`topK` are deprecated (ignored now,
# documented to error in later model generations).


@pytest.mark.parametrize(
    "model", ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.1-pro-preview", "gemini-4-flash"]
)
def test_3x_uses_thinking_level_not_budget(monkeypatch, model):
    sent = _capture(monkeypatch)
    _client(model=model).complete("hello")

    config = sent["payload"]["generationConfig"]
    assert config["thinking"] == {"thinkingLevel": "minimal"}
    assert "thinkingConfig" not in config, "legacy 2.x budget must not be sent to a 3.x model"


@pytest.mark.parametrize(
    "model", ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-4-flash"]
)
def test_3x_omits_deprecated_sampling_parameters(monkeypatch, model):
    sent = _capture(monkeypatch)
    _client(model=model).complete("hello")

    config = sent["payload"]["generationConfig"]
    for deprecated in ("temperature", "topP", "topK", "top_p", "top_k"):
        assert deprecated not in config, f"{deprecated} is deprecated on {model}"


def test_3x_never_sends_both_thinking_fields(monkeypatch):
    """Sending both is a documented 400."""
    sent = _capture(monkeypatch)
    _client(model="gemini-3.5-flash-lite", thinking_budget=1024).complete("hello")

    config = sent["payload"]["generationConfig"]
    assert ("thinking" in config) != ("thinkingConfig" in config)


def test_thinking_level_is_configurable(monkeypatch):
    sent = _capture(monkeypatch)
    _client(model="gemini-3.5-flash-lite", thinking_level="high").complete("hello")
    assert sent["payload"]["generationConfig"]["thinking"] == {"thinkingLevel": "high"}


def test_an_invalid_thinking_level_falls_back_to_the_default(monkeypatch):
    sent = _capture(monkeypatch)
    _client(model="gemini-3.5-flash-lite", thinking_level="turbo").complete("hello")
    assert sent["payload"]["generationConfig"]["thinking"] == {"thinkingLevel": "minimal"}


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini-2.5-flash", False),
        ("gemini-2.0-flash", False),
        ("gemini-3-flash-preview", True),
        ("gemini-3.5-flash-lite", True),
        ("gemini-3.6-flash", True),
        ("gemini-10-flash", True),
        ("", False),
    ],
)
def test_model_family_detection(model, expected):
    from autoaudit.llm.gemini_client import _is_gemini_3_or_newer

    assert _is_gemini_3_or_newer(model) is expected


def test_http_timeout_is_configurable_and_generous(monkeypatch):
    sent = _capture(monkeypatch)
    _client(http_timeout_seconds=120).complete("hello")
    assert sent["timeout"] == 120
    # Default must leave room for a batched request.
    assert _client().http_timeout_seconds >= 60


def test_a_model_rejecting_thinking_config_downgrades_instead_of_failing(monkeypatch):
    """Some models (2.5 Pro) don't allow disabling thinking. Dropping the
    field costs latency; failing every request costs the whole run."""
    payloads = []
    responses = [
        _Resp(400, text='{"error": {"message": "thinkingConfig is not supported"}}'),
        _Resp(),
    ]

    def _post(url, params=None, json=None, timeout=None):
        payloads.append(json)
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", _post)

    client = _client(max_retries=2)
    assert client.complete("hello") == "answer"
    assert "thinkingConfig" in payloads[0]["generationConfig"]
    assert "thinkingConfig" not in payloads[1]["generationConfig"], "should stop sending it"
    assert client._thinking_supported is False


def test_other_4xx_still_fails_fast(monkeypatch):
    calls = []

    def _post(url, params=None, json=None, timeout=None):
        calls.append(1)
        return _Resp(401, text='{"error": {"message": "API key not valid"}}')

    monkeypatch.setattr(requests, "post", _post)
    with pytest.raises(RuntimeError) as exc:
        _client(max_retries=2).complete("hello")
    assert not isinstance(exc.value, ProviderUnavailable)
    assert len(calls) == 1


# --- response handling ------------------------------------------------------


def test_empty_response_is_an_error_not_an_empty_description(monkeypatch):
    """Returning "" here silently wrote an empty description into findings."""
    _capture(monkeypatch, _Resp(payload={"candidates": []}))
    with pytest.raises(ProviderUnavailable):
        _client(max_retries=0).complete("hello")


def test_truncated_response_is_reported_with_actionable_advice(monkeypatch):
    _capture(monkeypatch, _Resp(payload={"candidates": [{"finishReason": "MAX_TOKENS", "content": {}}]}))
    with pytest.raises(ProviderUnavailable) as exc:
        _client(max_retries=0).complete("hello")
    assert "GEMINI_MAX_OUTPUT_TOKENS" in str(exc.value)


def test_blocked_prompt_is_surfaced(monkeypatch):
    _capture(monkeypatch, _Resp(payload={"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ProviderUnavailable) as exc:
        _client(max_retries=0).complete("hello")
    assert "SAFETY" in str(exc.value)


def test_a_transient_empty_response_is_retried(monkeypatch):
    responses = [_Resp(payload={"candidates": []}), _Resp()]
    monkeypatch.setattr(requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("autoaudit.llm.gemini_client.time.sleep", lambda *_: None)
    assert _client(max_retries=2).complete("hello") == "answer"


def test_normal_response_still_parses(monkeypatch):
    _capture(monkeypatch, _Resp(payload={
        "candidates": [{"content": {"parts": [{"text": "line one"}, {"text": "line two"}]}}]
    }))
    assert _client().complete("hello") == "line one\nline two"


# --- size-aware batching ----------------------------------------------------


def test_batches_are_capped_by_item_count():
    batches = chunk_items(["x"] * 20, max_items=8)
    assert [len(b) for b in batches] == [8, 8, 4]


def test_batches_are_also_capped_by_total_size():
    """Documentation prompts embed source code, so 8 of them can be huge —
    slow to generate against and likelier to truncate mid-batch."""
    big = "y" * 5_000
    batches = chunk_items([big] * 8, max_items=8, max_chars=12_000)
    assert len(batches) > 1
    for batch in batches:
        assert sum(len(i) for i in batch) <= 12_000 or len(batch) == 1


def test_an_oversized_single_item_still_gets_sent():
    huge = "z" * 50_000
    batches = chunk_items([huge, "small"], max_items=8, max_chars=1_000)
    assert [len(b) for b in batches] == [1, 1]
    assert batches[0][0] == huge


def test_chunking_preserves_order_and_loses_nothing():
    items = [f"item-{i}" for i in range(37)]
    flattened = [i for batch in chunk_items(items, max_items=8) for i in batch]
    assert flattened == items


def test_size_of_lets_richer_objects_be_batched():
    class Item:
        def __init__(self, prompt):
            self.prompt = prompt

    items = [Item("a" * 5_000) for _ in range(4)]
    batches = chunk_items(items, max_items=8, max_chars=12_000, size_of=lambda i: len(i.prompt))
    assert len(batches) == 2


def test_default_batch_char_cap_is_sane():
    assert 1_000 < DEFAULT_MAX_BATCH_CHARS < 100_000
