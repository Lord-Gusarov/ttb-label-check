"""Test-suite defaults.

Tier-2 model escalation is ON by default in production, but the test suite must stay fully
local, offline, and deterministic — so we disable it for every test. Tests that exercise
escalation behaviour re-enable/override it via their own ``monkeypatch``.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# The store singleton reads LABEL_CHECK_DB at import time; point it at a throwaway
# file BEFORE any test imports `app.*` so suites never touch (or depend on) the real
# backend/data/app.db.
os.environ.setdefault(
    "LABEL_CHECK_DB", os.path.join(tempfile.mkdtemp(prefix="label-check-test-"), "app.db")
)


@pytest.fixture(autouse=True)
def _local_only_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WARNING_ESCALATION_MODEL", "off")
