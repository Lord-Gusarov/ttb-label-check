# Submit → Review → Decide Flow — Implementation Plan (Phase 1)

> Steps use checkbox (`- [ ]`) syntax for task tracking. TDD: write the failing test, watch it
> fail, implement minimally, watch it pass, commit.

**Goal:** Wrap the existing verification engine in a single-application flow: an applicant submits
declared fields + a label image; an agent reviews AI-assisted per-field results on the label and
decides Approve / Reject / Needs Correction.

**Architecture:** FastAPI exposes an in-memory `Application` store + 4 JSON endpoints over the
existing `pipeline.verify_label`. A Vite/React UI has a no-auth top toggle between an Applicant
form and an Agent review queue; the review view overlays reader word-boxes on the label and shows
per-field verdicts. Local-first — zero external calls.

**Tech Stack:** Python 3.12 / FastAPI / OpenCV / existing readers+rules engine; Vite + React + TS
+ Tailwind. Quality gates: **mypy** (backend types), **strict TypeScript** (frontend), and
**Playwright** (E2E + visual validation + console-error capture). Run backend via `uv`.

**Quality gates & observability (cross-cutting — see Tasks 10–12):**
- **No silent failures (dev) vs. graceful errors (demo).** Backend logs every unhandled error
  with a stack trace via a FastAPI exception handler. Frontend: *development* gets raw visibility
  for free — Vite's error overlay + `console`, which Playwright captures and asserts on. The
  *demo* shows users only **friendly** handling: inline action messages ("Couldn't verify — try
  again / request a better image") and a top-level **ErrorBoundary** fallback ("Something went
  wrong — reload"). Never a raw stack trace in the user's face; the real error goes to the console.
- **Type enforcement.** `uv run mypy app` (backend) and `tsc --noEmit` (frontend strict) are gates.
- **Playwright artifacts.** E2E tests capture browser console, page errors, failed requests, and
  screenshots into `artifacts/e2e/`, and **assert zero console/page errors** — so a console error
  fails the run and leaves an inspectable artifact (screenshots render as images on review).

**Reuses (do not reimplement):**
- `app/pipeline.py` → `verify_label(image: np.ndarray, commodity: str, application: dict) -> VerificationResult`
  where `VerificationResult(commodity, result: LabelResult, read: ReadResult)`.
- `app/rules/result.py` → `Verdict` (`pass|warn|needs_review|fail`), `FieldResult(field, label, verdict, expected, found, detail)`, `LabelResult(commodity, overall, fields)`.
- `app/readers/types.py` → `ReadResult(text, words, confidence, engine, elapsed_ms)`, `WordBox(text, confidence, bbox=(x1,y1,x2,y2))`.

---

## File Structure

**Backend (create):**
- `backend/app/store.py` — `Application` dataclass + in-memory `ApplicationStore` (one responsibility: hold applications).
- `backend/app/serialize.py` — turn a `VerificationResult` into a JSON-able dict, attaching per-field `kind` and best-effort evidence boxes.
- `backend/app/api/applications.py` — the 4 endpoints (`APIRouter`).
- `backend/tests/test_store.py`, `backend/tests/test_serialize.py`, `backend/tests/test_api_applications.py`.

**Backend (modify):**
- `backend/app/main.py` — include the applications router.

**Frontend (create):**
- `frontend/src/types.ts` — shared TS types mirroring the API.
- `frontend/src/api.ts` — typed fetch helpers.
- `frontend/src/modes/ApplicantForm.tsx` — submit form.
- `frontend/src/modes/AgentQueue.tsx` — queue list.
- `frontend/src/modes/ReviewView.tsx` — label + overlay + per-field results + decision buttons.

**Frontend (modify):**
- `frontend/src/App.tsx` — top toggle between the two modes.

---

## Task 1: Application model + in-memory store

**Files:**
- Create: `backend/app/store.py`
- Test: `backend/tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_store.py
from app.store import Application, ApplicationStore


def _app(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="OLD TOM DISTILLERY",
                class_type="Kentucky Straight Bourbon Whiskey",
                alcohol_content="45% Alc./Vol.", net_contents="750 mL", image=b"\x89PNG")
    base.update(kw)
    return Application.new(**base)


def test_new_application_has_id_status_and_timestamp():
    app = _app()
    assert app.id and isinstance(app.id, str)
    assert app.status == "submitted"
    assert app.created_at > 0
    assert app.verification is None


def test_store_add_get_list_roundtrip():
    store = ApplicationStore()
    a, b = _app(), _app(brand_name="STONE'S THROW")
    store.add(a); store.add(b)
    assert store.get(a.id) is a
    assert {x.id for x in store.list()} == {a.id, b.id}
    assert store.get("missing") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_store.py -q`
Expected: FAIL (`ModuleNotFoundError: app.store`).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/store.py
"""In-memory Application store (prototype; nothing sensitive persisted)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Application:
    id: str
    commodity_type: str
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    image: bytes                       # raw uploaded image bytes
    created_at: float
    status: str = "submitted"          # submitted | approved | rejected | needs_correction
    decision_note: str | None = None
    verification: dict | None = None   # cached serialized verification result

    @classmethod
    def new(cls, **kw) -> "Application":
        return cls(id=uuid.uuid4().hex, created_at=time.time(), **kw)


class ApplicationStore:
    def __init__(self) -> None:
        self._items: dict[str, Application] = {}

    def add(self, app: Application) -> None:
        self._items[app.id] = app

    def get(self, app_id: str) -> Application | None:
        return self._items.get(app_id)

    def list(self) -> list[Application]:
        return list(self._items.values())


store = ApplicationStore()  # module-level singleton used by the API
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_store.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/store.py backend/tests/test_store.py
git commit -m "Add in-memory Application store"
```

---

## Task 2: Serialize verification result (+ field kind + evidence boxes)

**Files:**
- Create: `backend/app/serialize.py`
- Test: `backend/tests/test_serialize.py`

**Design:** `serialize_verification(vr)` returns a dict the frontend renders. Each field gets a
`kind` (`match` = must equal a declared value; `present` = mandatory on label) and best-effort
`boxes` (pixel `[x1,y1,x2,y2]`) located by matching the field's words against the reader's word
boxes — empty list when not locatable (degrade gracefully, never error).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_serialize.py
from app.readers.types import ReadResult, WordBox
from app.rules.result import FieldResult, LabelResult, Verdict
from app.pipeline import VerificationResult
from app.serialize import FIELD_KIND, serialize_verification


def _vr():
    words = [
        WordBox("OLD", 0.9, (10, 10, 40, 30)),
        WordBox("TOM", 0.9, (45, 10, 80, 30)),
        WordBox("45%", 0.9, (10, 50, 60, 70)),
    ]
    read = ReadResult(text="OLD TOM 45%", words=words, confidence=0.9,
                      engine="tesseract", elapsed_ms=12.3)
    fields = [
        FieldResult("brand_name", "Brand name", Verdict.PASS, "OLD TOM", "OLD TOM", "match"),
        FieldResult("warning_text", "Government warning text", Verdict.NEEDS_REVIEW,
                    "(canonical)", "GOVERNMENT WARNING…", "review"),
    ]
    result = LabelResult("distilled_spirits", Verdict.NEEDS_REVIEW, fields)
    return VerificationResult("distilled_spirits", result, read)


def test_serialize_shape_and_kinds():
    out = serialize_verification(_vr())
    assert out["overall"] == "needs_review"
    assert out["engine"] == "tesseract"
    brand = next(f for f in out["fields"] if f["field"] == "brand_name")
    assert brand["kind"] == "match"
    # "OLD" and "TOM" boxes are located for the brand value
    assert [10, 10, 40, 30] in brand["boxes"]
    assert FIELD_KIND["warning_text"] == "present"
    # all reader words are included for the faint base overlay
    assert len(out["words"]) == 3


def test_serialize_handles_unlocatable_field():
    out = serialize_verification(_vr())
    warning = next(f for f in out["fields"] if f["field"] == "warning_text")
    assert warning["boxes"] == []  # no warning words in this read -> empty, no crash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_serialize.py -q`
Expected: FAIL (`ModuleNotFoundError: app.serialize`).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/serialize.py
"""Serialize a VerificationResult into a JSON-able dict for the UI."""
from __future__ import annotations

import re

from app.pipeline import VerificationResult
from app.readers.types import ReadResult
from app.rules.result import FieldResult

# match = label must equal a declared value; present = mandatory element, no declared value.
FIELD_KIND: dict[str, str] = {
    "brand_name": "match",
    "class_type": "match",
    "alcohol_content": "match",
    "net_contents": "match",
    "warning_text": "present",
    "warning_caps": "present",
    "warning_bold": "present",
}

_WARNING_TOKENS = {"government", "warning"}


def _tokens(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _locate_boxes(field: FieldResult, read: ReadResult) -> list[list[int]]:
    """Best-effort: boxes of reader words that make up this field's value."""
    if field.field.startswith("warning"):
        wanted = _WARNING_TOKENS
    else:
        wanted = _tokens(field.found) or _tokens(field.expected)
    if not wanted:
        return []
    boxes = []
    for w in read.words:
        if _tokens(w.text) & wanted:
            boxes.append([int(c) for c in w.bbox])
    return boxes


def serialize_field(field: FieldResult, read: ReadResult) -> dict:
    return {
        "field": field.field,
        "label": field.label,
        "verdict": field.verdict.value,
        "kind": FIELD_KIND.get(field.field, "present"),
        "expected": field.expected,
        "found": field.found,
        "detail": field.detail,
        "boxes": _locate_boxes(field, read),
    }


def serialize_verification(vr: VerificationResult) -> dict:
    read = vr.read
    return {
        "overall": vr.result.overall.value,
        "engine": read.engine,
        "elapsed_ms": round(read.elapsed_ms, 1),
        "fields": [serialize_field(f, read) for f in vr.result.fields],
        "words": [{"text": w.text, "bbox": [int(c) for c in w.bbox]} for w in read.words],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_serialize.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/serialize.py backend/tests/test_serialize.py
git commit -m "Add verification serialization with field kinds and evidence boxes"
```

---

## Task 3: Applications API (create, list, detail+verify, decide)

**Files:**
- Create: `backend/app/api/applications.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_applications.py`

**Endpoints:**
- `POST /api/applications` (multipart: form fields + `image` file) → `{id, status}`
- `GET /api/applications` → `[{id, brand_name, commodity_type, status, created_at}]`
- `GET /api/applications/{id}` → full record + `verification` (run lazily on first GET, cached)
- `POST /api/applications/{id}/decision` (`{decision, note}`) → updated record

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_applications.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store

CLEAN = Path(__file__).resolve().parents[1] / "corpus" / "images" / "old_tom_clean.png"
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_store():
    store._items.clear()
    yield
    store._items.clear()


def _submit(**overrides):
    fields = dict(commodity_type="distilled_spirits", brand_name="OLD TOM DISTILLERY",
                  class_type="Kentucky Straight Bourbon Whiskey",
                  alcohol_content="45% Alc./Vol. (90 Proof)", net_contents="750 mL")
    fields.update(overrides)
    with open(CLEAN, "rb") as fh:
        return client.post("/api/applications", data=fields,
                           files={"image": ("label.png", fh, "image/png")})


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_submit_then_list():
    r = _submit()
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    listing = client.get("/api/applications").json()
    assert any(a["id"] == app_id and a["status"] == "submitted" for a in listing)


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_detail_runs_verification_clean_label_passes():
    app_id = _submit().json()["id"]
    detail = client.get(f"/api/applications/{app_id}").json()
    assert detail["verification"]["overall"] in ("pass", "warn", "needs_review")
    fields = {f["field"]: f for f in detail["verification"]["fields"]}
    assert fields["brand_name"]["verdict"] == "pass"
    assert fields["alcohol_content"]["verdict"] == "pass"


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_wrong_abv_flags_fail():
    app_id = _submit(alcohol_content="40% Alc./Vol.").json()["id"]
    detail = client.get(f"/api/applications/{app_id}").json()
    fields = {f["field"]: f for f in detail["verification"]["fields"]}
    assert fields["alcohol_content"]["verdict"] == "fail"


def test_decision_updates_status():
    # No image needed for the decision path; create directly via the store.
    from app.store import Application
    a = Application.new(commodity_type="distilled_spirits", brand_name="X", class_type="Y",
                        alcohol_content="40%", net_contents="750 mL", image=b"")
    store.add(a)
    r = client.post(f"/api/applications/{a.id}/decision",
                    json={"decision": "approved", "note": "looks good"})
    assert r.status_code == 200
    assert client.get(f"/api/applications/{a.id}").json()["status"] == "approved"


def test_unknown_id_404():
    assert client.get("/api/applications/nope").status_code == 404


def test_bad_decision_rejected():
    from app.store import Application
    a = Application.new(commodity_type="distilled_spirits", brand_name="X", class_type="Y",
                        alcohol_content="40%", net_contents="750 mL", image=b"")
    store.add(a)
    assert client.post(f"/api/applications/{a.id}/decision",
                       json={"decision": "banana"}).status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_api_applications.py -q`
Expected: FAIL (404s / route not found).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/applications.py
"""Application submit/list/review/decide endpoints."""
from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.pipeline import verify_label
from app.serialize import serialize_verification
from app.store import Application, store

router = APIRouter(prefix="/api/applications", tags=["applications"])

_DECISIONS = {"approved", "rejected", "needs_correction"}


class Decision(BaseModel):
    decision: str
    note: str | None = None


def _summary(a: Application) -> dict:
    return {"id": a.id, "brand_name": a.brand_name, "commodity_type": a.commodity_type,
            "status": a.status, "created_at": a.created_at}


def _detail(a: Application) -> dict:
    return {**_summary(a), "class_type": a.class_type,
            "alcohol_content": a.alcohol_content, "net_contents": a.net_contents,
            "decision_note": a.decision_note, "verification": a.verification}


@router.post("", status_code=201)
async def create(
    commodity_type: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    raw = await image.read()
    if cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) is None:
        raise HTTPException(400, "image is not a readable JPEG/PNG")
    a = Application.new(commodity_type=commodity_type, brand_name=brand_name,
                        class_type=class_type, alcohol_content=alcohol_content,
                        net_contents=net_contents, image=raw)
    store.add(a)
    return {"id": a.id, "status": a.status}


@router.get("")
def list_applications() -> list[dict]:
    return [_summary(a) for a in store.list()]


@router.get("/{app_id}")
def get_application(app_id: str) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    if a.verification is None and a.image:  # verify lazily, cache on first view
        img = cv2.imdecode(np.frombuffer(a.image, np.uint8), cv2.IMREAD_COLOR)
        application = {"brand_name": a.brand_name, "class_type": a.class_type,
                       "alcohol_content": a.alcohol_content, "net_contents": a.net_contents}
        a.verification = serialize_verification(
            verify_label(img, a.commodity_type, application))
    return _detail(a)


@router.post("/{app_id}/decision")
def decide(app_id: str, body: Decision) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    if body.decision not in _DECISIONS:
        raise HTTPException(422, f"decision must be one of {sorted(_DECISIONS)}")
    a.status = body.decision
    a.decision_note = body.note
    return _detail(a)
```

- [ ] **Step 4: Wire the router into the app**

In `backend/app/main.py`, after `app = FastAPI(...)` and middleware, add:

```python
from app.api.applications import router as applications_router

app.include_router(applications_router)
```

(Keep the existing `/api/health` and static-mount block. The catch-all SPA route must remain
defined LAST so it doesn't shadow `/api/...` routes.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_api_applications.py -q`
Expected: PASS (all). If the SPA catch-all shadows the API, move `include_router` above it.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/applications.py backend/app/main.py backend/tests/test_api_applications.py
git commit -m "Add applications API: submit, list, review, decide"
```

---

## Task 4: Full backend suite + lint gate

- [ ] **Step 1: Run the whole backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all prior tests + the new ones PASS.

- [ ] **Step 2: Lint**

Run: `cd backend && uv run ruff check app tests`
Expected: `All checks passed!` (fix any issues, re-run).

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "Fix lint in applications API"   # only if changes
```

---

## Task 5: Frontend types + API client

**Files:**
- Create: `frontend/src/types.ts`, `frontend/src/api.ts`

- [ ] **Step 1: Create the shared types**

```ts
// frontend/src/types.ts
export type Verdict = "pass" | "warn" | "needs_review" | "fail";
export type Box = [number, number, number, number];

export interface FieldResult {
  field: string;
  label: string;
  verdict: Verdict;
  kind: "match" | "present";
  expected: string | null;
  found: string | null;
  detail: string;
  boxes: Box[];
}
export interface Verification {
  overall: Verdict;
  engine: string;
  elapsed_ms: number;
  fields: FieldResult[];
  words: { text: string; bbox: Box }[];
}
export interface AppSummary {
  id: string; brand_name: string; commodity_type: string;
  status: string; created_at: number;
}
export interface AppDetail extends AppSummary {
  class_type: string; alcohol_content: string; net_contents: string;
  decision_note: string | null; verification: Verification | null;
}
```

- [ ] **Step 2: Create the API client**

```ts
// frontend/src/api.ts
import type { AppDetail, AppSummary } from "./types";

export async function submitApplication(form: FormData): Promise<{ id: string }> {
  const r = await fetch("/api/applications", { method: "POST", body: form });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
  return r.json();
}
export async function listApplications(): Promise<AppSummary[]> {
  const r = await fetch("/api/applications");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function getApplication(id: string): Promise<AppDetail> {
  const r = await fetch(`/api/applications/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function decide(id: string, decision: string, note: string): Promise<AppDetail> {
  const r = await fetch(`/api/applications/${id}/decision`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts
git commit -m "Add frontend API client and shared types"
```

---

## Task 6: App shell with mode toggle

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Replace App with a two-mode toggle**

```tsx
// frontend/src/App.tsx
import { useState } from "react";
import { ApplicantForm } from "./modes/ApplicantForm";
import { AgentQueue } from "./modes/AgentQueue";
import { ErrorBoundary } from "./ErrorBoundary";

type Mode = "applicant" | "agent";

export default function App() {
  const [mode, setMode] = useState<Mode>("agent");
  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-slate-900">Label Check</h1>
          <nav className="flex gap-1 rounded-lg bg-slate-100 p-1" role="tablist">
            {(["applicant", "agent"] as Mode[]).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`px-4 py-2 rounded-md text-sm font-medium ${
                  mode === m ? "bg-white text-slate-900 shadow" : "text-slate-600"}`}>
                {m === "applicant" ? "Submit application" : "Agent review"}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl w-full px-6 py-8 flex-1">
        <ErrorBoundary>
          {mode === "applicant" ? <ApplicantForm /> : <AgentQueue />}
        </ErrorBoundary>
      </main>
    </div>
  );
}
```

- [ ] **Step 1b: Create the friendly ErrorBoundary** (demo-grade fallback; real error → console)

```tsx
// frontend/src/ErrorBoundary.tsx
import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error("UI error:", error); // visible to dev + captured by Playwright; not shown raw
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-lg font-medium text-red-800">Something went wrong.</p>
        <button onClick={() => location.reload()}
          className="mt-3 rounded-md bg-red-600 px-4 py-2 text-white">Reload</button>
      </div>
    );
  }
}
```

- [ ] **Step 2: Commit** (build verified after the mode components exist, Task 9)

```bash
git add frontend/src/App.tsx
git commit -m "Add app shell with applicant/agent mode toggle"
```

---

## Task 7: Applicant form

**Files:**
- Create: `frontend/src/modes/ApplicantForm.tsx`

- [ ] **Step 1: Create the form**

```tsx
// frontend/src/modes/ApplicantForm.tsx
import { useState } from "react";
import { submitApplication } from "../api";

const FIELDS = [
  { name: "brand_name", label: "Brand name", placeholder: "OLD TOM DISTILLERY" },
  { name: "class_type", label: "Class / type", placeholder: "Kentucky Straight Bourbon Whiskey" },
  { name: "alcohol_content", label: "Alcohol content", placeholder: "45% Alc./Vol. (90 Proof)" },
  { name: "net_contents", label: "Net contents", placeholder: "750 mL" },
];

export function ApplicantForm() {
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const { id } = await submitApplication(new FormData(e.currentTarget));
      setDone(id); e.currentTarget.reset();
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-xl space-y-5">
      <h2 className="text-xl font-medium text-slate-800">Submit a label for approval</h2>
      <label className="block">
        <span className="text-slate-700">Product type</span>
        <select name="commodity_type" defaultValue="distilled_spirits"
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-lg">
          <option value="distilled_spirits">Distilled spirits</option>
          <option value="wine">Wine</option>
          <option value="malt_beverage">Malt beverage</option>
        </select>
      </label>
      {FIELDS.map((f) => (
        <label key={f.name} className="block">
          <span className="text-slate-700">{f.label}</span>
          <input name={f.name} required placeholder={f.placeholder}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-lg" />
        </label>
      ))}
      <label className="block">
        <span className="text-slate-700">Label image</span>
        <input type="file" name="image" accept="image/png,image/jpeg" required
          className="mt-1 block w-full text-slate-700" />
      </label>
      <button disabled={busy}
        className="rounded-md bg-blue-600 px-5 py-3 text-lg font-medium text-white disabled:opacity-50">
        {busy ? "Submitting…" : "Submit application"}
      </button>
      {done && <p className="text-green-700">Submitted. Application id <code>{done}</code> is now in the agent queue.</p>}
      {error && <p className="text-red-700">Could not submit: {error}</p>}
    </form>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/modes/ApplicantForm.tsx
git commit -m "Add applicant submission form"
```

---

## Task 8: Agent queue + review view

**Files:**
- Create: `frontend/src/modes/AgentQueue.tsx`, `frontend/src/modes/ReviewView.tsx`

- [ ] **Step 1: Create the queue**

```tsx
// frontend/src/modes/AgentQueue.tsx
import { useEffect, useState } from "react";
import { listApplications } from "../api";
import type { AppSummary } from "../types";
import { ReviewView } from "./ReviewView";

const STATUS_COLOR: Record<string, string> = {
  submitted: "bg-slate-100 text-slate-700", approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700", needs_correction: "bg-amber-100 text-amber-700",
};

export function AgentQueue() {
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

  const refresh = () => listApplications().then(setApps).catch(() => setApps([]));
  useEffect(() => { refresh(); }, []);

  if (openId) return <ReviewView id={openId} onBack={() => { setOpenId(null); refresh(); }} />;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-medium text-slate-800">Review queue</h2>
      {apps.length === 0 && <p className="text-slate-500">No applications yet. Submit one from “Submit application”.</p>}
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {apps.map((a) => (
          <li key={a.id}>
            <button onClick={() => setOpenId(a.id)}
              className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-slate-50">
              <span className="font-medium text-slate-800">{a.brand_name}</span>
              <span className={`rounded-full px-3 py-1 text-sm font-medium ${STATUS_COLOR[a.status] ?? ""}`}>
                {a.status.replace("_", " ")}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Create the review view (overlay + per-field results + decision)**

```tsx
// frontend/src/modes/ReviewView.tsx
import { useEffect, useState } from "react";
import { decide, getApplication } from "../api";
import type { AppDetail, Verdict } from "../types";

const V_COLOR: Record<Verdict, string> = {
  pass: "#16a34a", warn: "#d97706", needs_review: "#d97706", fail: "#dc2626",
};

export function ReviewView({ id, onBack }: { id: string; onBack: () => void }) {
  const [app, setApp] = useState<AppDetail | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => { getApplication(id).then(setApp).catch(() => setApp(null)); }, [id]);
  if (!app) return <p className="text-slate-500">Loading…</p>;
  const v = app.verification;

  async function act(decision: string) {
    setApp(await decide(id, decision, ""));
  }

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-blue-600">← Back to queue</button>
      <h2 className="text-xl font-medium text-slate-800">{app.brand_name}</h2>
      <div className="grid gap-6 lg:grid-cols-2">
        <LabelImage id={id} words={v?.words ?? []}
          highlight={v?.fields.find((f) => f.field === hover)} />
        <div className="space-y-3">
          {v?.fields.map((f) => (
            <div key={f.field} onMouseEnter={() => setHover(f.field)} onMouseLeave={() => setHover(null)}
              className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium text-slate-800">{f.label}</span>
                <span className="text-sm font-semibold uppercase" style={{ color: V_COLOR[f.verdict] }}>
                  {f.verdict.replace("_", " ")}
                </span>
              </div>
              <p className="text-sm text-slate-600">
                {f.kind === "match" && <>declared <b>{f.expected}</b> · </>}{f.detail}
              </p>
            </div>
          ))}
          <div className="flex gap-2 pt-2">
            <button onClick={() => act("approved")} className="rounded-md bg-green-600 px-4 py-2 text-white">Approve</button>
            <button onClick={() => act("needs_correction")} className="rounded-md bg-amber-600 px-4 py-2 text-white">Needs correction</button>
            <button onClick={() => act("rejected")} className="rounded-md bg-red-600 px-4 py-2 text-white">Reject</button>
          </div>
          <p className="text-sm text-slate-500">Status: <b>{app.status.replace("_", " ")}</b></p>
        </div>
      </div>
    </div>
  );
}

function LabelImage({ id, words, highlight }:
  { id: string; words: { bbox: [number, number, number, number] }[];
    highlight?: { boxes: [number, number, number, number][]; verdict: Verdict } }) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  const src = `/api/applications/${id}/image`;
  return (
    <div className="relative inline-block border border-slate-200 bg-white">
      <img src={src} alt="submitted label" className="block max-w-full"
        onLoad={(e) => setDim({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
      {dim && (
        <svg viewBox={`0 0 ${dim.w} ${dim.h}`} className="absolute inset-0 h-full w-full">
          {words.map((w, i) => (
            <rect key={i} x={w.bbox[0]} y={w.bbox[1]} width={w.bbox[2] - w.bbox[0]}
              height={w.bbox[3] - w.bbox[1]} fill="none" stroke="#94a3b8" strokeWidth={1} opacity={0.4} />
          ))}
          {highlight?.boxes.map((b, i) => (
            <rect key={`h${i}`} x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]}
              fill="none" stroke={V_COLOR[highlight.verdict]} strokeWidth={3} />
          ))}
        </svg>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add the image endpoint the review view needs**

In `backend/app/api/applications.py` add (returns the stored image bytes):

```python
from fastapi.responses import Response

@router.get("/{app_id}/image")
def get_image(app_id: str) -> Response:
    a = store.get(app_id)
    if a is None or not a.image:
        raise HTTPException(404, "image not found")
    return Response(content=a.image, media_type="image/*")
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/modes/AgentQueue.tsx frontend/src/modes/ReviewView.tsx backend/app/api/applications.py
git commit -m "Add agent queue and review view with label overlay and decisions"
```

---

## Task 9: Build, end-to-end check, and container

- [ ] **Step 1: Type-check + build the frontend**

Run: `cd frontend && npm run build`
Expected: builds with no TS errors.

- [ ] **Step 2: Manual end-to-end (dev)**

```bash
# terminal 1
cd backend && uv run uvicorn app.main:app --reload
# terminal 2
cd frontend && npm run dev
```
Then in the browser: Submit application → fill OLD TOM fields → upload `backend/corpus/images/old_tom_clean.png` → Submit. Switch to Agent review → open it → confirm brand/ABV/net-contents show PASS, the warning rows show, word boxes overlay the label, hovering a field highlights its box → click Approve → status shows "approved".

- [ ] **Step 3: Verify the container still builds and serves**

```bash
docker build -t label-check . && docker run -d --rm -p 8001:8000 --name lc label-check
sleep 6 && curl -s localhost:8001/api/health && curl -s localhost:8001/api/applications
docker stop lc
```
Expected: health ok; `[]` from the (empty) applications list.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "Wire submit-review-decide UI end to end"   # only if changes
```

---

## Task 10: Backend logging + global exception handler (no silent failures)

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_errors.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_errors.py
from fastapi.testclient import TestClient

from app.main import app


def test_unhandled_error_returns_clean_json(monkeypatch):
    # Force an unexpected error deep in a handler and confirm it's caught + logged,
    # not leaked as an empty 500 or a silent failure.
    from app import store as store_mod

    def boom(_id):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(store_mod.store, "get", boom)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/applications/anything")
    assert r.status_code == 500
    assert r.json()["detail"] == "internal error"
    assert r.json()["path"] == "/api/applications/anything"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_errors.py -q`
Expected: FAIL (default 500 has no JSON body / raises).

- [ ] **Step 3: Add logging + handler to `app/main.py`**

Near the top, after imports:

```python
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
)
log = logging.getLogger("labelcheck")
```

After `app = FastAPI(...)` (and the router include):

```python
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "internal error", "path": request.url.path}
    )
```

(FastAPI's own `HTTPException`s — our 400/404/422 — are still handled normally; this only
catches the *unexpected* ones and guarantees they're logged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_errors.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_errors.py
git commit -m "Log unhandled errors and return clean JSON (no silent failures)"
```

---

## Task 11: Type-enforcement gates (mypy + strict TypeScript)

**Files:**
- Modify: `backend/pyproject.toml`, `frontend/package.json`, `.gitignore`

- [ ] **Step 1: Add mypy to backend dev deps + config**

In `backend/pyproject.toml`, add `"mypy>=1.13"` to the `dev` optional-deps list, and append:

```toml
[tool.mypy]
python_version = "3.12"
files = ["app"]
ignore_missing_imports = true   # cv2/pytesseract/rapidocr/easyocr/paddleocr ship no stubs
check_untyped_defs = true
```

Then: `cd backend && uv sync --extra readers --extra dev`

- [ ] **Step 2: Run mypy and fix what it flags**

Run: `cd backend && uv run mypy`
Expected: `Success` — our code is already annotated. Fix any real type errors it surfaces
(add/correct annotations); do **not** silence them with broad `# type: ignore` unless a
third-party type is genuinely unavailable.

- [ ] **Step 3: Lock in strict TS + add a typecheck script**

Confirm `frontend/tsconfig.app.json` has `"strict": true` (Vite default — leave it on). Add to
`frontend/package.json` `"scripts"`: `"typecheck": "tsc --noEmit"`. Run `cd frontend && npm run typecheck` → no errors.

- [ ] **Step 4: Ignore tool output**

Add to `.gitignore`: `artifacts/`, `frontend/test-results/`, `frontend/playwright-report/`.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml frontend/package.json .gitignore
git commit -m "Enforce types: mypy gate (backend) and strict tsc typecheck (frontend)"
```

---

## Task 12: Playwright E2E with console-error capture + screenshots

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/submit-review.spec.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Install Playwright**

```bash
cd frontend && npm i -D @playwright/test && npx playwright install chromium
```
Add to `frontend/package.json` `"scripts"`: `"e2e": "playwright test"`.

- [ ] **Step 2: Config — start backend + dev server, save artifacts**

```ts
// frontend/playwright.config.ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./artifacts/e2e",
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: { baseURL: "http://localhost:5173", screenshot: "only-on-failure", trace: "on-first-retry" },
  webServer: [
    {
      command: "cd ../backend && uv run uvicorn app.main:app --port 8000",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --port 5173",   // dev server proxies /api -> :8000
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
```

- [ ] **Step 3: The E2E test (captures console/page errors, asserts none)**

```ts
// frontend/e2e/submit-review.spec.ts
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

const ART = path.resolve("artifacts/e2e");
const LABEL = path.resolve("../backend/corpus/images/old_tom_clean.png");

test("submit → review → approve, with zero console errors", async ({ page }) => {
  fs.mkdirSync(ART, { recursive: true });
  const logs: string[] = [];
  const errors: string[] = [];
  page.on("console", (m) => {
    logs.push(`[${m.type()}] ${m.text()}`);
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) =>
    errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));

  await page.goto("/");

  // Applicant: submit OLD TOM
  await page.getByRole("tab", { name: "Submit application" }).click();
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.locator('input[type="file"]').setInputFiles(LABEL);
  await page.getByRole("button", { name: "Submit application" }).click();
  await expect(page.getByText(/Submitted/)).toBeVisible();
  await page.screenshot({ path: path.join(ART, "01-submitted.png"), fullPage: true });

  // Agent: open, review, approve
  await page.getByRole("tab", { name: "Agent review" }).click();
  await page.getByRole("button", { name: /OLD TOM DISTILLERY/ }).click();
  await expect(page.getByText("Brand name")).toBeVisible();
  await page.screenshot({ path: path.join(ART, "02-review.png"), fullPage: true });
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Status:\s*approved/i)).toBeVisible();
  await page.screenshot({ path: path.join(ART, "03-approved.png"), fullPage: true });

  fs.writeFileSync(path.join(ART, "console.log"), logs.join("\n"));
  expect(errors, `console/page errors:\n${errors.join("\n")}`).toHaveLength(0);
});
```

- [ ] **Step 4: Run it**

Run: `cd frontend && npm run e2e`
Expected: PASS, with `frontend/artifacts/e2e/01-submitted.png`, `02-review.png`, `03-approved.png`,
and `console.log` written. On any failure, screenshots + trace land in `artifacts/e2e/` for review.

- [ ] **Step 5: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e frontend/package.json frontend/package-lock.json
git commit -m "Add Playwright E2E with console-error capture and screenshot artifacts"
```

---

## Self-review checklist (run before execution)

- **Spec coverage:** Applicant submit ✓ (Task 3,7) · Agent queue+review ✓ (Task 8) ·
  match/present kinds ✓ (Task 2) · verdict→decision via buttons ✓ (Task 8) · overlay ✓ (Task 8) ·
  local-first (no external calls added) ✓ · error handling (bad image 400, unknown id 404, bad
  decision 422, missing field → NEEDS_REVIEW from engine) ✓ · batch is Phase 2 (not in this plan) ✓ ·
  no-silent-failures logging ✓ (Task 10) · type gates mypy+strict-tsc ✓ (Task 11) ·
  Playwright E2E + console capture + screenshots ✓ (Task 12).
- **Type consistency:** `Verdict` values match the backend enum; `boxes`/`bbox` are `[x1,y1,x2,y2]`
  everywhere; `FieldResult` shape identical in `serialize.py` and `types.ts`.
- **Reuse:** verification via `verify_label`; no engine logic reimplemented.
