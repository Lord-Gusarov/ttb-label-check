# backend/app/worker.py
"""Background verification worker. (Minimal stub — Task 3 builds out the pool,
start/shutdown, and startup re-enqueue. Dormant by default: enqueue is a no-op.)"""
from __future__ import annotations

_executor = None


def enqueue(app_id: str) -> None:
    if _executor is None:
        return  # dormant: a synchronous fallback handles verification
