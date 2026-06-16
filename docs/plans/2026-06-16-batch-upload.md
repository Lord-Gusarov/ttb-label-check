# Batch Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an applicant submit many applications at once via a JSON manifest + images, verify them in the background, and let an agent triage the results in a tabbed review queue.

**Architecture:** One canonical application payload feeds a shared `process_one` core used by both single submit and batch upload. Every created application is enqueued to a background `ThreadPoolExecutor` worker that runs the existing `verify_label` pipeline and records a per-item `verify_status`. A `Batch` entity groups items; progress is derived by querying them. The frontend gets a batch upload page, a polling progress view, and a tabbed queue.

**Tech Stack:** Python 3.12, FastAPI, SQLite (`sqlite3`), OpenCV, pytest (backend); Vite + React + TypeScript + Tailwind, Playwright (frontend).

---

## File Structure

**Backend (create):**
- `backend/app/service.py` — image validation, `process_one`, `verify_application` (the shared verification logic, extracted from the API).
- `backend/app/worker.py` — background `ThreadPoolExecutor`, `enqueue`, `start`, `shutdown`, startup re-enqueue.
- `backend/app/batch.py` — manifest parsing + per-row validation.
- `backend/app/api/batches.py` — `POST /api/applications/batch` and `GET /api/batches/{id}`.
- `backend/tests/test_service.py`, `test_worker.py`, `test_batch.py`, `test_batch_api.py`.

**Backend (modify):**
- `backend/app/store.py` — new `Application` fields; `Batch` dataclass; batch methods on both stores.
- `backend/app/api/applications.py` — route single submit through `process_one`; drop inline verify; expose `_summary` with new fields.
- `backend/app/main.py` — register batch router; start/stop worker via lifespan.

**Frontend (create):**
- `frontend/src/pages/BatchPage.tsx` — manifest + images upload with client-side reconciliation.
- `frontend/src/pages/BatchProgressPage.tsx` — polling progress view.
- `frontend/e2e/batch.spec.ts` — end-to-end batch flow.
- `frontend/e2e/fixtures/manifest.json` — small test manifest.

**Frontend (modify):**
- `frontend/src/types.ts` — `verify_status` on `AppSummary`; `BatchUploadResult`, `BatchProgress`.
- `frontend/src/api.ts` — `uploadBatch`, `getBatch`.
- `frontend/src/pages/QueuePage.tsx` — tabbed layout, group by `verify_status`, Submitted column.
- `frontend/src/App.tsx` — nav item + routes.
- `frontend/src/ui.tsx` — `Tabs` component + `formatWhen` timestamp helper.

---

## Task 1: Extend the data model

**Files:**
- Modify: `backend/app/store.py`
- Test: `backend/tests/test_store_batch.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_store_batch.py
from app.store import Application, ApplicationStore, Batch, SQLiteApplicationStore


def _app(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40%", net_contents="750 mL", image=b"img")
    base.update(kw)
    return Application.new(**base)


def test_application_defaults_pending_no_batch():
    a = _app()
    assert a.verify_status == "pending"
    assert a.batch_id is None
    assert a.verify_error is None


def test_batch_new_has_id_and_total():
    b = Batch.new(total=3)
    assert b.id and b.total == 3 and b.created_at > 0


def _roundtrip(store):
    b = Batch.new(total=2)
    store.add_batch(b)
    store.add(_app(batch_id=b.id))
    store.add(_app(batch_id=b.id))
    store.add(_app())  # unrelated single
    assert store.get_batch(b.id).total == 2
    assert {a.batch_id for a in store.list_by_batch(b.id)} == {b.id}
    assert len(store.list_by_batch(b.id)) == 2


def test_inmemory_batch_roundtrip():
    _roundtrip(ApplicationStore())


def test_sqlite_batch_roundtrip(tmp_path):
    _roundtrip(SQLiteApplicationStore(tmp_path / "t.db"))


def test_sqlite_persists_new_fields(tmp_path):
    s = SQLiteApplicationStore(tmp_path / "t.db")
    a = _app(verify_status="error", verify_error="boom")
    s.add(a)
    got = s.get(a.id)
    assert got.verify_status == "error" and got.verify_error == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_store_batch.py -v`
Expected: FAIL — `ImportError: cannot import name 'Batch'`.

- [ ] **Step 3: Add the fields, the `Batch` dataclass, and batch methods**

In `backend/app/store.py`, add to the `Application` dataclass (after `responsible_party`):

```python
    batch_id: str | None = None       # groups batch-uploaded items; None for single submits
    verify_status: str = "pending"    # pending | verifying | verified | error
    verify_error: str | None = None   # message when verify_status == "error"
```

Add a `Batch` dataclass after `Application`:

```python
@dataclass
class Batch:
    id: str
    created_at: float
    total: int = 0

    @classmethod
    def new(cls, *, total: int = 0) -> "Batch":
        return cls(id=uuid.uuid4().hex, created_at=time.time(), total=total)
```

In `ApplicationStore.__init__`, add `self._batches: dict[str, Batch] = {}`. Add methods:

```python
    def add_batch(self, batch: "Batch") -> None:
        self._batches[batch.id] = batch

    def get_batch(self, batch_id: str) -> "Batch | None":
        return self._batches.get(batch_id)

    def list_by_batch(self, batch_id: str) -> list[Application]:
        return [a for a in self._items.values() if a.batch_id == batch_id]
```

In `SQLiteApplicationStore`, extend `_COLS` (append): `"batch_id", "verify_status", "verify_error"`. Add columns to the `CREATE TABLE` body:

```python
                       batch_id TEXT,
                       verify_status TEXT NOT NULL DEFAULT 'pending',
                       verify_error TEXT
```

Add a `batches` table in `__init__` (second `c.execute`):

```python
            c.execute(
                """CREATE TABLE IF NOT EXISTS batches (
                       id TEXT PRIMARY KEY,
                       created_at REAL NOT NULL,
                       total INTEGER NOT NULL
                   )"""
            )
```

Extend `_row` (append): `a.batch_id, a.verify_status, a.verify_error`. Extend `_app` to read the new columns (append to the constructor): `batch_id=row[14], verify_status=row[15], verify_error=row[16]`. Add the batch methods:

```python
    def add_batch(self, batch: "Batch") -> None:
        with self._conn() as c:
            c.execute("INSERT INTO batches (id, created_at, total) VALUES (?,?,?)",
                      (batch.id, batch.created_at, batch.total))

    def get_batch(self, batch_id: str) -> "Batch | None":
        with self._conn() as c:
            row = c.execute("SELECT id, created_at, total FROM batches WHERE id=?",
                            (batch_id,)).fetchone()
        return Batch(id=row[0], created_at=row[1], total=row[2]) if row else None

    def list_by_batch(self, batch_id: str) -> list[Application]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM applications WHERE batch_id=? ORDER BY created_at",
                             (batch_id,)).fetchall()
        return [self._app(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_store_batch.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full store-touching suite + types**

Run: `cd backend && uv run pytest -q && uv run mypy app`
Expected: PASS (no regressions; new columns have defaults so existing rows/tests are unaffected).

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/tests/test_store_batch.py
git commit -m "store: add batch grouping and per-item verify status"
```

---

## Task 2: Verification service (`process_one` + `verify_application`)

**Files:**
- Create: `backend/app/service.py`
- Test: `backend/tests/test_service.py`

This extracts the verify logic out of the API so the worker and the API share one path. `verify_label` is referenced as `app.service.verify_label` so tests can monkeypatch it (offline, fast).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service.py
import numpy as np
import pytest

from app import service
from app.service import ImageError, process_one, validate_image, verify_application
from app.store import Application, ApplicationStore


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    s = ApplicationStore()
    monkeypatch.setattr(service, "store", s)
    return s


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch):
    # process_one calls worker.enqueue via late import; stub it so no threads start.
    import app.worker as worker
    monkeypatch.setattr(worker, "enqueue", lambda app_id: None)


def _payload(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40%", net_contents="750 mL", image="a.png")
    base.update(kw)
    return base


def test_validate_image_rejects_garbage():
    with pytest.raises(ImageError):
        validate_image(b"not an image")


def test_process_one_creates_pending_app(_store):
    a = process_one(_payload(), b"imgbytes", batch_id="batch1")
    assert isinstance(a, Application)
    assert a.verify_status == "pending"
    assert a.batch_id == "batch1"
    assert _store.get(a.id) is not None


def test_verify_application_success(monkeypatch, _store):
    a = process_one(_payload(), b"imgbytes")
    monkeypatch.setattr(service, "_decode", lambda raw: np.zeros((4, 4, 3), np.uint8))
    monkeypatch.setattr(service, "verify_label", lambda *a, **k: object())
    monkeypatch.setattr(service, "serialize_verification", lambda vr: {"overall": "pass"})
    verify_application(a)
    assert a.verify_status == "verified"
    assert a.verification == {"overall": "pass"}
    assert a.verify_error is None


def test_verify_application_failsafe(monkeypatch, _store):
    a = process_one(_payload(), b"imgbytes")
    def _boom(raw): raise ValueError("decode failed")
    monkeypatch.setattr(service, "_decode", _boom)
    verify_application(a)
    assert a.verify_status == "error"
    assert "decode failed" in a.verify_error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.service'`.

- [ ] **Step 3: Create the service**

```python
# backend/app/service.py
"""Shared application processing: image validation, creation, and verification.

One path for both single submit and batch upload. `process_one` creates a pending
Application and enqueues it; the worker (or a GET fallback) calls `verify_application`,
which runs the existing pipeline FAIL-SAFE — any failure becomes verify_status='error'
plus a human review, never a crash."""
from __future__ import annotations

import logging

import cv2
import numpy as np

from app.pipeline import verify_label
from app.serialize import serialize_verification
from app.store import Application, store

log = logging.getLogger(__name__)

#: Upload guards (single source; the API imports these). A real label is far under both.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB — memory-exhaustion guard
MAX_PIXELS = 50_000_000               # 50 MP — decompression/pixel-bomb guard


class ImageError(ValueError):
    """An uploaded image is too large, unreadable, or over the pixel cap."""


def _decode(raw: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ImageError("image is not a readable JPEG/PNG")
    return img


def validate_image(raw: bytes) -> None:
    """Raise ImageError if `raw` is too big, unreadable, or over the pixel cap."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError(f"image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")
    img = _decode(raw)
    h, w = img.shape[:2]
    if h * w > MAX_PIXELS:
        raise ImageError(f"image resolution exceeds the {MAX_PIXELS // 1_000_000}MP limit")


def process_one(payload: dict, image_bytes: bytes, *, batch_id: str | None = None) -> Application:
    """Create a pending Application from a canonical payload and enqueue it for verification."""
    from app.worker import enqueue  # late import breaks the worker<->service cycle

    a = Application.new(
        commodity_type=payload["commodity_type"], brand_name=payload["brand_name"],
        class_type=payload["class_type"], alcohol_content=payload["alcohol_content"],
        net_contents=payload["net_contents"], source=payload.get("source", ""),
        country_of_origin=payload.get("country_of_origin", ""),
        responsible_party=payload.get("responsible_party", ""),
        image=image_bytes, batch_id=batch_id,
    )
    store.add(a)
    enqueue(a.id)
    return a


def _application_dict(a: Application) -> dict:
    return {"brand_name": a.brand_name, "class_type": a.class_type,
            "alcohol_content": a.alcohol_content, "net_contents": a.net_contents,
            "source": a.source, "country_of_origin": a.country_of_origin,
            "responsible_party": a.responsible_party}


def verify_application(a: Application) -> None:
    """Run (and persist) verification for one application. FAIL-SAFE: on any error,
    records verify_status='error' so the item degrades to human review, never a crash."""
    a.verify_status = "verifying"
    store.update(a)
    try:
        img = _decode(a.image)
        a.verification = serialize_verification(verify_label(img, a.commodity_type, _application_dict(a)))
        a.verify_status = "verified"
        a.verify_error = None
    except Exception as e:  # noqa: BLE001 — verification must never crash the worker/request
        log.exception("verification failed for %s", a.id)
        a.verify_status = "error"
        a.verify_error = str(e)
    store.update(a)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/service.py backend/tests/test_service.py
git commit -m "service: extract shared process_one and verify_application"
```

---

## Task 3: Background worker

**Files:**
- Create: `backend/app/worker.py`
- Test: `backend/tests/test_worker.py`

The worker is dormant until `start()` is called (so the test suite, which never starts it, behaves exactly as before — see Task 6's GET fallback). `enqueue` is a no-op while dormant.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_worker.py
import pytest

from app import service, worker
from app.store import ApplicationStore


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    s = ApplicationStore()
    monkeypatch.setattr(service, "store", s)
    monkeypatch.setattr(worker, "store", s)
    return s


@pytest.fixture(autouse=True)
def _stub_verify(monkeypatch):
    # Replace real OCR with a fast stub that marks the item verified.
    def fake(a):
        a.verify_status = "verified"
        a.verification = {"overall": "pass"}
        service.store.update(a)
    monkeypatch.setattr(worker, "verify_application", fake)


def _app(_store):
    a = process = None
    from app.store import Application
    a = Application.new(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                        alcohol_content="40%", net_contents="750 mL", image=b"x")
    _store.add(a)
    return a


def test_enqueue_is_noop_when_dormant(_store):
    a = _app(_store)
    worker.enqueue(a.id)  # not started -> nothing happens
    assert _store.get(a.id).verify_status == "pending"


def test_started_worker_processes(_store):
    a = _app(_store)
    worker.start()
    try:
        worker.enqueue(a.id)
        worker.shutdown(wait=True)
    finally:
        worker._executor = None
    assert _store.get(a.id).verify_status == "verified"


def test_start_reenqueues_stranded(_store):
    a = _app(_store)  # status pending
    worker.start()    # should re-enqueue the pending item
    try:
        worker.shutdown(wait=True)
    finally:
        worker._executor = None
    assert _store.get(a.id).verify_status == "verified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker'`.

- [ ] **Step 3: Create the worker**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_worker.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker.py backend/tests/test_worker.py
git commit -m "worker: background verification pool with startup re-enqueue"
```

---

## Task 4: Manifest parsing + row validation

**Files:**
- Create: `backend/app/batch.py`
- Test: `backend/tests/test_batch.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_batch.py
import json

import pytest

from app.batch import MAX_BATCH_ITEMS, ManifestError, parse_manifest, row_skip_reason


def _row(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40%", net_contents="750 mL", image="a.png")
    base.update(kw)
    return base


def test_parse_rejects_non_json():
    with pytest.raises(ManifestError):
        parse_manifest(b"{not json")


def test_parse_rejects_non_array():
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps({"image": "a.png"}).encode())


def test_parse_rejects_oversize():
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps([_row()] * (MAX_BATCH_ITEMS + 1)).encode())


def test_parse_returns_rows():
    rows = parse_manifest(json.dumps([_row(), _row()]).encode())
    assert len(rows) == 2 and rows[0]["image"] == "a.png"


def test_skip_reason_missing_field():
    assert "required" in row_skip_reason(_row(brand_name=""), {"a.png"})


def test_skip_reason_bad_commodity():
    assert "commodity" in row_skip_reason(_row(commodity_type="mead"), {"a.png"})


def test_skip_reason_image_not_uploaded():
    assert "not found" in row_skip_reason(_row(image="missing.png"), {"a.png"})


def test_skip_reason_none_when_valid():
    assert row_skip_reason(_row(), {"a.png"}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.batch'`.

- [ ] **Step 3: Create the parser/validator**

```python
# backend/app/batch.py
"""Batch manifest parsing and per-row validation.

A manifest is a JSON array of canonical application payloads, each naming its image file.
Validation is per-row: a bad row is SKIPPED with a reason, never failing the whole batch.
Only a structurally invalid manifest (not JSON / not an array / oversize) is fatal."""
from __future__ import annotations

import json

from app.rules import RULESETS

#: Required declared fields plus the image reference. responsible_party is optional and
#: country_of_origin is conditional (imports only), matching the single-submit form.
REQUIRED = ("commodity_type", "brand_name", "class_type", "alcohol_content",
            "net_contents", "image")

#: Cap items per batch — an unauthenticated endpoint guard, far above any real batch.
MAX_BATCH_ITEMS = 500


class ManifestError(ValueError):
    """The manifest itself is unusable (not JSON, not an array, or over the item cap)."""


def parse_manifest(raw: bytes) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise ManifestError("manifest must be a JSON array of applications")
    if len(data) > MAX_BATCH_ITEMS:
        raise ManifestError(f"manifest exceeds the {MAX_BATCH_ITEMS}-item limit")
    if not all(isinstance(r, dict) for r in data):
        raise ManifestError("each manifest entry must be a JSON object")
    return data


def row_skip_reason(row: dict, image_names: set[str]) -> str | None:
    """Return why this row can't be processed, or None if it's valid."""
    missing = [k for k in REQUIRED if not str(row.get(k, "")).strip()]
    if missing:
        return f"missing required field(s): {', '.join(missing)}"
    if row["commodity_type"] not in RULESETS:
        return f"unsupported commodity '{row['commodity_type']}'"
    if row["image"] not in image_names:
        return f"image '{row['image']}' not found in upload"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_batch.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/batch.py backend/tests/test_batch.py
git commit -m "batch: JSON manifest parsing and per-row validation"
```

---

## Task 5: Batch API endpoints + single-submit refactor

**Files:**
- Create: `backend/app/api/batches.py`
- Modify: `backend/app/api/applications.py`
- Test: `backend/tests/test_batch_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_batch_api.py
import io
import json

import numpy as np
import cv2
import pytest
from fastapi.testclient import TestClient

from app import service, store as store_mod
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_store():
    store_mod.store.clear()
    yield
    store_mod.store.clear()


def _png(text: bytes = b"x") -> bytes:
    img = np.full((40, 120, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def _row(image, **kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40% Alc./Vol.", net_contents="750 mL", image=image)
    base.update(kw)
    return base


def _upload(client, rows, images):
    files = [("manifest", ("m.json", json.dumps(rows).encode(), "application/json"))]
    for name, data in images.items():
        files.append(("images", (name, data, "image/png")))
    return client.post("/api/applications/batch", files=files)


def test_batch_accepts_valid_and_skips_bad():
    client = TestClient(app)
    rows = [_row("a.png"), _row("missing.png"), _row("b.png", commodity_type="mead")]
    r = _upload(client, rows, {"a.png": _png(), "b.png": _png()})
    assert r.status_code == 201
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["skipped"]) == 2
    assert {s["index"] for s in body["skipped"]} == {1, 2}


def test_batch_progress_counts():
    client = TestClient(app)
    r = _upload(client, [_row("a.png")], {"a.png": _png()})
    batch_id = r.json()["batch_id"]
    prog = client.get(f"/api/batches/{batch_id}").json()
    assert prog["total"] == 1
    # worker dormant in tests -> item stays pending until first GET detail
    assert prog["counts"]["pending"] + prog["counts"]["verified"] == 1
    assert len(prog["items"]) == 1


def test_bad_manifest_is_400():
    client = TestClient(app)
    files = [("manifest", ("m.json", b"{not json", "application/json")),
             ("images", ("a.png", _png(), "image/png"))]
    assert client.post("/api/applications/batch", files=files).status_code == 400


def test_unknown_batch_is_404():
    assert TestClient(app).get("/api/batches/nope").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_batch_api.py -v`
Expected: FAIL — 404 on `/api/applications/batch` (route not registered).

- [ ] **Step 3: Create the batch router**

```python
# backend/app/api/batches.py
"""Batch upload (manifest + images) and batch progress."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.applications import _summary
from app.batch import ManifestError, parse_manifest, row_skip_reason
from app.service import ImageError, process_one, validate_image
from app.store import Batch, store

router = APIRouter(tags=["batches"])


@router.post("/api/applications/batch", status_code=201)
async def create_batch(
    manifest: UploadFile = File(...),
    images: list[UploadFile] = File(...),
) -> dict:
    """Upload a JSON manifest plus its images. Valid rows are created and enqueued for
    background verification; invalid rows are skipped and reported (never fatal)."""
    try:
        rows = parse_manifest(await manifest.read())
    except ManifestError as e:
        raise HTTPException(400, str(e)) from e

    files: dict[str, bytes] = {}
    for im in images:
        files[im.filename or ""] = await im.read()
    image_names = set(files)

    batch = Batch.new()
    accepted = 0
    skipped: list[dict] = []
    for i, row in enumerate(rows):
        reason = row_skip_reason(row, image_names)
        if reason is None:
            try:
                validate_image(files[row["image"]])
            except ImageError as e:
                reason = str(e)
        if reason is not None:
            skipped.append({"index": i, "image": row.get("image"), "reason": reason})
            continue
        process_one(row, files[row["image"]], batch_id=batch.id)
        accepted += 1

    batch.total = accepted
    store.add_batch(batch)
    return {"batch_id": batch.id, "accepted": accepted, "skipped": skipped}


@router.get("/api/batches/{batch_id}")
def get_batch(batch_id: str) -> dict:
    b = store.get_batch(batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    items = store.list_by_batch(batch_id)
    counts = {"pending": 0, "verifying": 0, "verified": 0, "error": 0}
    for a in items:
        counts[a.verify_status] = counts.get(a.verify_status, 0) + 1
    return {"id": b.id, "total": b.total, "counts": counts,
            "items": [_summary(a) for a in items]}
```

- [ ] **Step 4: Refactor single submit + summary in `applications.py`**

Add the import near the top: `from app.service import ImageError, process_one, validate_image, verify_application`.

Replace `_summary` so it carries the new fields:

```python
def _summary(a: Application) -> dict:
    overall = a.verification.get("overall") if a.verification else None
    return {"id": a.id, "brand_name": a.brand_name, "commodity_type": a.commodity_type,
            "status": a.status, "created_at": a.created_at, "overall": overall,
            "verify_status": a.verify_status, "verify_error": a.verify_error}
```

Replace the body of `create` (keep its signature) to route through `process_one`:

```python
    if commodity_type not in RULESETS:
        raise HTTPException(400, f"unsupported commodity '{commodity_type}'")
    raw = await image.read()
    try:
        validate_image(raw)
    except ImageError as e:
        raise HTTPException(413 if "limit" in str(e) else 400, str(e)) from e
    payload = {"commodity_type": commodity_type, "brand_name": brand_name,
               "class_type": class_type, "alcohol_content": alcohol_content,
               "net_contents": net_contents, "source": source,
               "country_of_origin": country_of_origin, "responsible_party": responsible_party}
    a = process_one(payload, raw)
    return {"id": a.id, "status": a.status}
```

Replace `_ensure_verification` usage: delete the `_ensure_verification` function and update `get_application` and `reverify`:

```python
@router.get("/{app_id}")
def get_application(app_id: str) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    # Fallback: if the worker hasn't verified it yet (or is dormant, as in tests), verify now.
    if a.verification is None and a.verify_status != "verifying":
        verify_application(a)
    return _detail(a)


@router.post("/{app_id}/reverify")
def reverify(app_id: str) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    verify_application(a)
    return _detail(a)
```

Update `preview` to reuse the shared guard: replace `img = _decode_or_400(await _read_capped(image))` with:

```python
    raw = await image.read()
    try:
        validate_image(raw)
    except ImageError as e:
        raise HTTPException(413 if "limit" in str(e) else 400, str(e)) from e
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
```

Delete the now-unused `_MAX_UPLOAD_BYTES`, `_MAX_PIXELS`, `_read_capped`, and `_decode_or_400` (their job moved to `service.validate_image`). Keep `_decode` for `/image`? No — `get_image` doesn't decode. Confirm no remaining references with the test run below.

- [ ] **Step 5: Register the router in `main.py`**

Add after the applications router include:

```python
from app.api.batches import router as batches_router
app.include_router(batches_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_batch_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full backend suite + types**

Run: `cd backend && uv run pytest -q && uv run mypy app`
Expected: PASS. (If a pre-existing test asserted that `GET /{id}` populated `verification`, it still passes via the new fallback.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/batches.py backend/app/api/applications.py backend/app/main.py backend/tests/test_batch_api.py
git commit -m "api: batch upload + progress; route single submit through shared core"
```

---

## Task 6: Start the worker with the app lifespan

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_lifespan.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lifespan.py
from fastapi.testclient import TestClient

from app import worker
from app.main import app


def test_worker_starts_and_stops_with_lifespan():
    assert worker._executor is None
    with TestClient(app):           # enters lifespan -> start()
        assert worker._executor is not None
    assert worker._executor is None  # exits lifespan -> shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_lifespan.py -v`
Expected: FAIL — `_executor` stays None (no lifespan wired).

- [ ] **Step 3: Add a lifespan to `main.py`**

Add the import: `from contextlib import asynccontextmanager` and `from app import worker`. Define the lifespan and pass it to `FastAPI(...)`:

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    worker.start()
    try:
        yield
    finally:
        worker.shutdown(wait=False)


app = FastAPI(
    title="label-check",
    version=__version__,
    summary="TTB alcohol label verification — local-first, deterministic compliance.",
    lifespan=_lifespan,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_lifespan.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite once more**

Run: `cd backend && uv run pytest -q`
Expected: PASS. (Other tests use bare `TestClient(app)` without a `with` block, so they never enter the lifespan and the worker stays dormant — verification still runs via the GET fallback.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_lifespan.py
git commit -m "main: start/stop the verification worker with the app lifespan"
```

---

## Task 7: Frontend types + API client

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`

- [ ] **Step 1: Extend the types**

In `frontend/src/types.ts`, add the verify status to `AppSummary` and the batch shapes:

```typescript
export type VerifyStatus = "pending" | "verifying" | "verified" | "error";

export interface AppSummary {
  id: string; brand_name: string; commodity_type: string;
  status: string; created_at: number;
  overall?: Verdict | null; // automated recommendation, for queue triage
  verify_status?: VerifyStatus;
  verify_error?: string | null;
}

export interface BatchSkip { index: number; image: string | null; reason: string; }
export interface BatchUploadResult { batch_id: string; accepted: number; skipped: BatchSkip[]; }
export interface BatchProgress {
  id: string; total: number;
  counts: Record<VerifyStatus, number>;
  items: AppSummary[];
}
```

- [ ] **Step 2: Add the API calls**

In `frontend/src/api.ts`, add (reusing the existing `json<T>` helper) and update the import line to include the new types:

```typescript
import type {
  AppDetail, AppSummary, BatchProgress, BatchUploadResult, Verification,
} from "./types";

export async function uploadBatch(manifest: File, images: File[]): Promise<BatchUploadResult> {
  const fd = new FormData();
  fd.append("manifest", manifest);
  for (const im of images) fd.append("images", im);
  return json(await fetch("/api/applications/batch", { method: "POST", body: fd }));
}

export async function getBatch(id: string): Promise<BatchProgress> {
  return json(await fetch(`/api/batches/${id}`));
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -p tsconfig.app.json --noEmit`
Expected: PASS (no type errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts
git commit -m "frontend: batch types and api client"
```

---

## Task 8: Shared UI bits — `Tabs` and `formatWhen`

**Files:**
- Modify: `frontend/src/ui.tsx`

- [ ] **Step 1: Add an accessible Tabs component and a timestamp helper**

Append to `frontend/src/ui.tsx` (uses the existing exports' style; `useId` from React):

```tsx
import { useId, type ReactNode } from "react";

/** Friendly submitted-at label from an epoch-seconds timestamp. */
export function formatWhen(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export interface TabDef { key: string; label: string; count: number; }

/** WCAG-AA tablist: roving focus, arrow-key navigation, aria-selected. */
export function Tabs({ tabs, active, onChange }: {
  tabs: TabDef[]; active: string; onChange: (key: string) => void;
}) {
  const base = useId();
  function onKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    onChange(tabs[next].key);
  }
  return (
    <div role="tablist" aria-label="Queue filters" className="flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t, i) => {
        const selected = t.key === active;
        return (
          <button
            key={t.key}
            role="tab"
            id={`${base}-${t.key}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => onKey(e, i)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              selected ? "border-brand text-brand" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t.label}
            <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
              selected ? "bg-brand-soft text-brand" : "bg-surface-2 text-muted"
            }`}>{t.count}</span>
          </button>
        );
      })}
    </div>
  );
}
```

(If `ui.tsx` already imports from `react`, merge the `useId`/`ReactNode` import into the existing line rather than adding a duplicate.)

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -p tsconfig.app.json --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/ui.tsx
git commit -m "ui: accessible Tabs component and submitted-at formatter"
```

---

## Task 9: Batch upload page

**Files:**
- Create: `frontend/src/pages/BatchPage.tsx`

- [ ] **Step 1: Create the page with client-side reconciliation**

```tsx
// frontend/src/pages/BatchPage.tsx
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadBatch } from "../api";
import { Card, PageHeading, btnPrimary, inputCls } from "../ui";

interface Reconciliation { count: number; missing: string[]; unreferenced: string[]; error: string | null; }

function reconcile(manifestText: string | null, imageNames: Set<string>): Reconciliation {
  if (manifestText === null) return { count: 0, missing: [], unreferenced: [], error: null };
  let rows: unknown;
  try { rows = JSON.parse(manifestText); }
  catch { return { count: 0, missing: [], unreferenced: [], error: "Manifest is not valid JSON." }; }
  if (!Array.isArray(rows)) return { count: 0, missing: [], unreferenced: [], error: "Manifest must be a JSON array." };
  const referenced = rows.map((r) => (r && typeof r === "object" ? String((r as Record<string, unknown>).image ?? "") : ""));
  const missing = [...new Set(referenced.filter((n) => n && !imageNames.has(n)))];
  const refSet = new Set(referenced);
  const unreferenced = [...imageNames].filter((n) => !refSet.has(n));
  return { count: rows.length, missing, unreferenced, error: null };
}

export function BatchPage() {
  const [manifest, setManifest] = useState<File | null>(null);
  const [manifestText, setManifestText] = useState<string | null>(null);
  const [images, setImages] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const imageNames = useMemo(() => new Set(images.map((f) => f.name)), [images]);
  const rec = useMemo(() => reconcile(manifestText, imageNames), [manifestText, imageNames]);
  const ready = manifest !== null && rec.error === null && rec.count > 0 && rec.missing.length === 0;

  async function onManifest(file: File | null) {
    setManifest(file);
    setManifestText(file ? await file.text() : null);
  }

  async function submit() {
    if (!manifest) return;
    setBusy(true); setError(null);
    try {
      const res = await uploadBatch(manifest, images);
      navigate(`/batch/${res.batch_id}`, { state: { skipped: res.skipped } });
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="rise space-y-6">
      <PageHeading title="Batch upload" subtitle="Upload a JSON manifest and the label images. Each manifest entry names its image file." />
      <Card className="space-y-5 p-6">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink">Manifest (.json)</span>
          <input type="file" accept="application/json,.json" className={inputCls}
            onChange={(e) => onManifest(e.currentTarget.files?.[0] ?? null)} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink">Label images</span>
          <input type="file" accept="image/png,image/jpeg" multiple className={inputCls}
            onChange={(e) => setImages([...(e.currentTarget.files ?? [])])} />
        </label>

        {manifestText !== null && (
          <div role="status" className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm">
            {rec.error ? (
              <p className="font-medium text-fail">{rec.error}</p>
            ) : (
              <>
                <p className="font-medium text-ink">
                  Manifest: {rec.count} applications · {images.length} images
                  {ready && <span className="text-pass"> · all matched ✓</span>}
                </p>
                {rec.missing.length > 0 && (
                  <p className="mt-1 text-fail">Rows reference images you didn’t include: {rec.missing.join(", ")}</p>
                )}
                {rec.unreferenced.length > 0 && (
                  <p className="mt-1 text-muted">Images not referenced by any row: {rec.unreferenced.join(", ")}</p>
                )}
              </>
            )}
          </div>
        )}

        <button disabled={!ready || busy} onClick={submit} className={`${btnPrimary} px-5 py-3 text-base disabled:opacity-50`}>
          {busy ? "Uploading…" : `Upload ${rec.count || ""} applications`.trim()}
        </button>
        {error && <p role="alert" className="text-sm font-medium text-fail">Could not upload: {error}</p>}
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -p tsconfig.app.json --noEmit`
Expected: PASS. (Wiring the route is Task 11; the page isn't reachable yet.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/BatchPage.tsx
git commit -m "frontend: batch upload page with client-side reconciliation"
```

---

## Task 10: Batch progress page

**Files:**
- Create: `frontend/src/pages/BatchProgressPage.tsx`

- [ ] **Step 1: Create the polling progress view**

```tsx
// frontend/src/pages/BatchProgressPage.tsx
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { getBatch } from "../api";
import type { BatchProgress, BatchSkip } from "../types";
import { Card, PageHeading, StatusBadge, VerdictPill, btnPrimary } from "../ui";

export function BatchProgressPage() {
  const { id = "" } = useParams();
  const skipped = (useLocation().state as { skipped?: BatchSkip[] } | null)?.skipped ?? [];
  const [prog, setProg] = useState<BatchProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const p = await getBatch(id);
        if (!live) return;
        setProg(p);
        if (p.counts.pending + p.counts.verifying > 0) timer = setTimeout(tick, 1500);
      } catch (e) { if (live) setError(String(e)); }
    }
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [id]);

  if (error) return <Card className="mt-8 border-fail/30 p-8 text-center"><p role="alert" className="font-medium text-fail">{error}</p></Card>;
  if (!prog) return <p className="mt-8 text-muted">Loading…</p>;

  const done = prog.counts.verified + prog.counts.error;
  const clear = prog.items.filter((a) => a.verify_status === "verified" && a.overall === "pass").length;
  const attention = prog.items.filter((a) => a.verify_status === "verified" && a.overall !== "pass").length;
  const complete = prog.counts.pending + prog.counts.verifying === 0;

  return (
    <div className="rise space-y-6">
      <PageHeading title="Batch" subtitle={`${done} / ${prog.total} verified`} />

      {skipped.length > 0 && (
        <details className="rounded-lg border border-flag/40 bg-flag/5 px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium text-ink">{skipped.length} rows skipped — see why</summary>
          <ul className="mt-2 space-y-1 text-muted">
            {skipped.map((s) => <li key={s.index}>Row {s.index + 1} ({s.image ?? "no image"}): {s.reason}</li>)}
          </ul>
        </details>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Clear" value={clear} tone="text-pass" />
        <Stat label="Needs attention" value={attention} tone="text-flag" />
        <Stat label="Verifying" value={prog.counts.pending + prog.counts.verifying} tone="text-muted" />
        <Stat label="Errors" value={prog.counts.error} tone="text-fail" />
      </div>

      <Card className="overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line bg-surface-2 text-xs uppercase tracking-wide text-muted">
            <tr><th className="px-5 py-3 font-semibold">Brand</th><th className="px-5 py-3 font-semibold">Check</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {prog.items.map((a) => (
              <tr key={a.id}>
                <td className="px-5 py-3 font-semibold text-ink">
                  <Link to={`/queue/${a.id}`} className="hover:text-brand hover:underline">{a.brand_name}</Link>
                </td>
                <td className="px-5 py-3">
                  {a.verify_status === "verified" && a.overall ? <VerdictPill verdict={a.overall} />
                    : a.verify_status === "error" ? <span className="text-xs font-medium text-fail">Error</span>
                    : <span className="text-xs text-muted">Verifying…</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {complete && (
        <div className="flex items-center gap-3">
          <p className="text-sm font-medium text-ink">{clear} clear · {attention} need attention · {prog.counts.error} errors</p>
          <Link to="/queue?tab=attention" className={`${btnPrimary} px-4 py-2.5 text-sm`}>Go to review queue</Link>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className={`text-2xl font-bold ${tone}`}>{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
}
```

Add `BatchSkip` to the type import in this file (it's exported from Task 7). If `StatusBadge` is unused here, omit it from the import.

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -p tsconfig.app.json --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/BatchProgressPage.tsx
git commit -m "frontend: batch progress view with polling"
```

---

## Task 11: Tabbed queue + Submitted column + routes/nav

**Files:**
- Modify: `frontend/src/pages/QueuePage.tsx`, `frontend/src/App.tsx`

- [ ] **Step 1: Rework QueuePage into tabs grouped by verify_status**

Replace the grouping + render in `frontend/src/pages/QueuePage.tsx`. Update imports:

```tsx
import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { decide, listApplications } from "../api";
import type { AppSummary } from "../types";
import { Card, PageHeading, StatusBadge, Tabs, VerdictPill, btnOutlinePass, btnPass, btnPrimary, formatWhen } from "../ui";
```

Replace everything from `const submitted = ...` down to the end of the returned JSX in the component with:

```tsx
  const [params, setParams] = useSearchParams();
  const verifying = apps.filter((a) => a.status === "submitted" && a.verify_status !== "verified" && a.verify_status !== "error");
  const verified = apps.filter((a) => a.status === "submitted" && (a.verify_status === "verified" || a.verify_status === "error"));
  const clear = verified.filter((a) => a.overall === "pass");
  const attention = verified.filter((a) => a.overall !== "pass");
  const decided = apps.filter((a) => a.status !== "submitted");

  const tabs = [
    { key: "attention", label: "Needs attention", count: attention.length },
    { key: "approve", label: "Recommended to approve", count: clear.length },
    { key: "verifying", label: "Verifying", count: verifying.length },
    { key: "decided", label: "Decided", count: decided.length },
  ];
  const active = params.get("tab") ?? "attention";
  const setTab = (key: string) => setParams({ tab: key }, { replace: true });

  return (
    <div className="rise space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeading title="Review queue" subtitle="The tool recommends; you decide." />
        <Link to="/submit" className={`${btnPrimary} px-4 py-2.5 text-sm`}>+ New application</Link>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-fail/30 bg-fail/5 px-4 py-3 text-sm font-medium text-fail">
          Action failed: {error}
        </p>
      )}

      <Tabs tabs={tabs} active={active} onChange={setTab} />

      {apps.length === 0 ? <EmptyState /> : (
        <div role="tabpanel" className="space-y-3">
          {active === "attention" && (attention.length
            ? <Table apps={attention} onOpen={(id) => navigate(`/queue/${id}`)} />
            : <Empty msg="Nothing flagged. 🎉" />)}
          {active === "approve" && (clear.length ? (
            <>
              <div className="flex justify-end">
                <button disabled={busy} onClick={() => approve(clear.map((a) => a.id))} className={`${btnPass} px-4 py-2.5 text-sm`}>
                  {busy ? "Approving…" : `Approve all ${clear.length}`}
                </button>
              </div>
              <Table apps={clear} onOpen={(id) => navigate(`/queue/${id}`)}
                rowAction={(a) => (
                  <button disabled={busy} onClick={(e) => { e.stopPropagation(); approve([a.id]); }} className={`${btnOutlinePass} px-3 py-1.5 text-xs`}>
                    Approve
                  </button>
                )} />
            </>
          ) : <Empty msg="No clear applications waiting." />)}
          {active === "verifying" && (verifying.length
            ? <Table apps={verifying} onOpen={(id) => navigate(`/queue/${id}`)} />
            : <Empty msg="Nothing in progress." />)}
          {active === "decided" && (decided.length
            ? <Table apps={decided} onOpen={(id) => navigate(`/queue/${id}`)} />
            : <Empty msg="No decisions yet." />)}
        </div>
      )}
    </div>
  );
```

Add a tiny `Empty` helper next to `EmptyState`:

```tsx
function Empty({ msg }: { msg: string }) {
  return <p className="px-1 py-8 text-center text-muted">{msg}</p>;
}
```

Update the `Table` to show the verdict-or-spinner and a Submitted column. In `Table`'s `<thead>` add a header after "Check" (before Status):

```tsx
            <th className="hidden px-5 py-3 font-semibold md:table-cell">Submitted</th>
```

In the row body, change the Check cell to handle verifying state and add the timestamp cell:

```tsx
              <td className="px-5 py-4">
                {a.verify_status === "verified" && a.overall ? <VerdictPill verdict={a.overall} />
                  : a.verify_status === "error" ? <span className="text-xs font-medium text-fail">Error</span>
                  : <span className="text-xs text-muted">Verifying…</span>}
              </td>
              <td className="hidden px-5 py-4 text-muted md:table-cell">{formatWhen(a.created_at)}</td>
```

(Keep the existing rowAction column last.) Newest-first sort: at the top of each `Table` render, sort a copy — change `{apps.map(...)}` to iterate `[...apps].sort((x, y) => y.created_at - x.created_at).map(...)`.

- [ ] **Step 2: Add nav item + routes in `App.tsx`**

In the `NAV` array, add between Submit and Queue:

```tsx
  { to: "/batch", label: "Batch upload", icon: <PlusIcon /> },
```

Import the new pages and add routes inside `<Routes>`:

```tsx
import { BatchPage } from "./pages/BatchPage";
import { BatchProgressPage } from "./pages/BatchProgressPage";
```

```tsx
              <Route path="/batch" element={<BatchPage />} />
              <Route path="/batch/:id" element={<BatchProgressPage />} />
```

- [ ] **Step 3: Type-check + build**

Run: `cd frontend && npx tsc -p tsconfig.app.json --noEmit && npm run build`
Expected: PASS (both).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/QueuePage.tsx frontend/src/App.tsx
git commit -m "frontend: tabbed review queue grouped by verify status, with submitted column"
```

---

## Task 12: End-to-end batch flow + accessibility

**Files:**
- Create: `frontend/e2e/batch.spec.ts`, `frontend/e2e/fixtures/manifest.json`
- Reuse: an existing label image from `backend/tests/fixtures/labels/`

- [ ] **Step 1: Create a small manifest fixture**

```json
[
  { "commodity_type": "distilled_spirits", "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey", "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL", "responsible_party": "Bottled by Old Tom, Bardstown, KY",
    "image": "label-a.png" }
]
```

- [ ] **Step 2: Write the E2E test**

```typescript
// frontend/e2e/batch.spec.ts
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "..", "..");
// Copy/point at any real fixture label; rename to label-a.png to match the manifest.
const IMAGE = path.join(ROOT, "backend/tests/fixtures/labels"); // pick a concrete file at runtime

test("batch upload → progress → queue", async ({ page }) => {
  await page.goto("/batch");
  const manifest = path.join(__dirname, "fixtures/manifest.json");
  await page.getByLabel("Manifest (.json)").setInputFiles(manifest);
  // Use one real label image, presented to the form under the manifest's referenced name.
  const sample = readFileSync(path.join(IMAGE, "clean-front.png")); // adjust to a file that exists
  await page.getByLabel("Label images").setInputFiles({ name: "label-a.png", mimeType: "image/png", buffer: sample });

  await expect(page.getByText(/all matched/)).toBeVisible();
  await page.getByRole("button", { name: /Upload/ }).click();

  await expect(page).toHaveURL(/\/batch\//);
  await expect(page.getByText(/\/ 1 verified/)).toBeVisible({ timeout: 30000 });
  await page.getByRole("link", { name: "Go to review queue" }).click();

  await expect(page.getByRole("tab", { name: /Needs attention|Recommended to approve/ }).first()).toBeVisible();
});

test("queue tabs are keyboard navigable", async ({ page }) => {
  await page.goto("/queue");
  const firstTab = page.getByRole("tab").first();
  await firstTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { selected: true })).toBeVisible();
});
```

Note for the implementer: pick an actual filename that exists under `backend/tests/fixtures/labels/` for both `IMAGE`/`sample`; the manifest references `label-a.png`, and the upload presents the bytes under that name so the server matches it.

- [ ] **Step 3: Run E2E**

Run: `cd frontend && npx playwright test batch.spec.ts`
Expected: PASS (Playwright auto-starts both servers per the existing config; the worker verifies the single item within the timeout).

- [ ] **Step 4: Run the accessibility contrast audit**

Run: `node frontend/scripts/contrast-check.mjs`
Expected: PASS (new pages use existing tokens; fix any flagged pair by swapping to an AA-passing token).

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/batch.spec.ts frontend/e2e/fixtures/manifest.json
git commit -m "e2e: batch upload flow and queue tab keyboard navigation"
```

---

## Task 13: Docs — README + limitations

**Files:**
- Modify: `README.md`, `docs/design-decisions.md`

- [ ] **Step 1: Document the feature and its boundaries**

In `README.md` "What it does", note batch upload (manifest + images, background verification, tabbed queue). In "Scope & limitations" (and `docs/design-decisions.md`), record the deliberate choices: JSON-only manifest (CSV deferred — comma-heavy fields), multi-file upload (no zip), no per-batch queue filter, in-process worker (fine for a single-container prototype; a real deployment would use a durable queue).

- [ ] **Step 2: Commit**

```bash
git add README.md docs/design-decisions.md
git commit -m "docs: document batch upload and its scope boundaries"
```

---

## Self-Review

- **Spec coverage:** Manifest+images full-match (Tasks 4–5); JSON format (Task 4); shared `process_one`/`verify_application` with single = batch-of-one (Tasks 2, 5); background worker + startup re-enqueue (Tasks 3, 6); `Batch` entity + derived counts (Tasks 1, 5); progress endpoint (Task 5); per-row skip + verify-time error (Tasks 4, 2, 5); bounds (Tasks 2, 4); batch upload page with reconciliation (Task 9); progress view polling (Task 10); tabbed queue grouped by verify_status + Submitted column + ARIA tabs + URL tab (Tasks 8, 11); testing across unit/parity/E2E/accessibility (all tasks + 12); limitations (Task 13). All spec sections map to a task.
- **Placeholder scan:** None — every code step is complete. The only runtime choice left to the implementer is the concrete fixture filename in Task 12, flagged explicitly because it depends on what exists on disk.
- **Type consistency:** `verify_status`/`verify_error`/`batch_id` names match across `store.py`, `service.py`, `_summary`, `types.ts`, and the queue/progress components. `process_one(payload, image_bytes, *, batch_id=None)`, `verify_application(a)`, `enqueue(app_id)`, `Batch.new(total=...)`, `getBatch`/`uploadBatch`, and the `BatchProgress.counts` shape are used identically wherever referenced.
