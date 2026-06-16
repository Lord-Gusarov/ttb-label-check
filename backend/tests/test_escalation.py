"""Tier-2 escalation is ON by default and strictly FAIL-SAFE: when the model is missing/broken,
or explicitly disabled, it degrades to a human review — never blocks or crashes."""

from __future__ import annotations

import numpy as np
import pytest

from app.escalation import escalate_label_read


def _img() -> np.ndarray:
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_default_on_attempts_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    # ON by default: with the env var unset, escalation still runs (reaches the model call).
    # Stub the network layer so no real request is made.
    monkeypatch.delenv("WARNING_ESCALATION_MODEL", raising=False)
    monkeypatch.setattr("app.escalation._chat_json", lambda *a, **k: {"brand_name": "ACME"})
    out = escalate_label_read(_img())
    assert out is not None and out["brand_name"] == "ACME"


def test_default_on_without_key_is_failsafe(monkeypatch: pytest.MonkeyPatch) -> None:
    # On by default, but fail-safe: no key reachable -> degrades to None, never raises.
    monkeypatch.delenv("WARNING_ESCALATION_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.escalation._read_key", lambda: None)
    assert escalate_label_read(_img()) is None


def test_explicit_off_disables_even_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WARNING_ESCALATION_MODEL", "off")
    monkeypatch.setattr("app.escalation._read_key", lambda: "sk-fake")
    assert escalate_label_read(_img()) is None  # off wins, no call attempted


def test_unknown_provider_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WARNING_ESCALATION_MODEL", "frobnicate:whatever")
    assert escalate_label_read(_img()) is None  # must not raise


def test_openai_without_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WARNING_ESCALATION_MODEL", "openai:gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.escalation._read_key", lambda: None)
    assert escalate_label_read(_img()) is None
