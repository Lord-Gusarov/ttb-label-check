"""Tier-2 escalation is ON by default but strictly FAIL-SAFE: a missing/broken model, or
an explicit "off", degrades to a human review — it never blocks or crashes the pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from app.escalation import escalate_label_read


def _img() -> np.ndarray:
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_default_on_without_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default is openai:gpt-4o-mini, but with no key reachable it must degrade to None.
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
