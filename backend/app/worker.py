# backend/app/worker.py
"""Background verification worker.

Every created application is enqueued here and verified off the request path by a small
ThreadPoolExecutor (OCR is CPU-bound, so we keep the pool small). Dormant until start():
while dormant, enqueue() is a no-op and callers fall back to synchronous verification
(see the API GET fallback) — which is exactly how the test suite runs."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from app.service import verify_application
from app.store import store

log = logging.getLogger(__name__)

_POOL_SIZE = int(os.getenv("BATCH_WORKERS", "2"))
_executor: ThreadPoolExecutor | None = None


def _process(app_id: str) -> None:
    a = store.get(app_id)
    if a is None:
        log.warning("worker: application %s vanished before verification", app_id)
        return
    verify_application(a)


def start() -> None:
    """Start the pool and re-enqueue any items left mid-flight by a previous run."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_POOL_SIZE, thread_name_prefix="verify")
        log.info("verification worker started (%d threads)", _POOL_SIZE)
    for a in store.list():
        if a.verify_status in ("pending", "verifying"):
            enqueue(a.id)


def enqueue(app_id: str) -> None:
    if _executor is None:
        return  # dormant: the caller's synchronous fallback handles verification
    _executor.submit(_process, app_id)


def shutdown(*, wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
