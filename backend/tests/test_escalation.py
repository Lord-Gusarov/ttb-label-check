"""Tier-2 escalation is OFF by default (opt-in) and strictly FAIL-SAFE: when not enabled, or
when the model is missing/broken, it degrades to a human review — never blocks or crashes."""

from __future__ import annotations

import numpy as np
import pytest

from app.escalation import escalate_label_read


def _img() -> np.ndarray:
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_default_off_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    # Escalation is off by default: with the env var unset it must NOT call out, even when a
    # key is available — opting in requires explicitly setting WARNING_ESCALATION_MODEL.
    monkeypatch.delenv("WARNING_ESCALATION_MODEL", raising=False)
    monkeypatch.setattr("app.escalation._read_key", lambda: "sk-fake")
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
