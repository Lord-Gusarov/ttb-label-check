# Architecture

Label Check verifies an alcohol-beverage label against an application's declared fields and the
TTB regulations. The guiding rule is **the model reads, the deterministic engine decides** —
text extraction is swappable and best-effort; the legal verdict is rendered by deterministic,
auditable rules.

## High-level shape

```
 Applicant / Agent (React SPA)
        │  multipart: declared fields + 1 label image
        ▼
 FastAPI  (app/api/applications.py)
        │
        ▼
 pipeline.verify_label  ──────────────────────────────────────────────┐
        │                                                              │
        │  ① READ (cheap, local — on-box, no outbound call)          │
        │     reader.extract(image)  → text + word boxes (RapidOCR)   │
        │     warning re-read (anchored crop, scale search)           │
        │                                                              │
        │  ② DECIDE (deterministic rules)                             │
        │     engine.evaluate(commodity, application, text)           │
        │       FieldPolicy table → comparators → FieldResult[]       │
        │     warning checks (text / ALL-CAPS / bold)                 │
        │                                                              │
        │  ③ ESCALATE (only if a field ≠ PASS)                        │
        │     Tier-2 LLM re-read (on by default, fail-safe), OR       │
        │     local geometry rescues (deskew / 90° re-read)           │
        │                                                              │
        ▼                                                              │
 LabelResult (overall = worst field verdict) ◄────────────────────────┘
        │
        ▼
 serialize → JSON (verdicts + evidence + bbox) → SPA overlay → agent decision
```

## The two-tier design (cheapest-first)

The prior vendor died at 30–40 s/label, so the common case must be **fast and local**, and any
expensive step must be **earned**:

- **Tier 1 — local & deterministic (always on).** RapidOCR reads the label on-box; the rules
  engine renders the verdict. ~sub-2 s median, no outbound call. This clears the easy/clean labels.
- **Tier 2 — semantic-validation LLM (on by default).** Runs **only** when Tier 1 leaves a field
  unverified. An LLM re-reads the label; the **same deterministic comparators** then judge the
  model's text. Fail-safe: if the model is unavailable it degrades to the local verdict + human
  review. The model never renders the verdict, and the client is **decoupled** (see below).

Whatever neither tier can clear is `NEEDS REVIEW` → a human decides. Nothing auto-rejects.

## Network security & deployment strategy

Stakeholder discovery flagged that the internal network restricts outbound traffic to external
cloud APIs (it previously broke a vendor integration). The design respects this **by being
decoupled, not by disabling the LLM**:

- **Local edge processing (OCR)** runs entirely on-box, so the common case needs no network and
  high-bandwidth image traffic is avoided.
- **The semantic-validation layer is pluggable.** This prototype calls the OpenAI API over HTTPS
  for demonstration; the client swaps — with no change to the verdict logic — for an **Azure
  OpenAI** deployment inside the agency **FedRAMP** boundary, or an **internal vLLM enclave**
  with zero outbound internet. The same architecture therefore runs fully in-boundary in prod.

## Components

### Reading layer — `app/readers/` (pluggable)
Every reader implements one interface → `ReadResult { text, words[], confidence, engine,
elapsed_ms }`, where each `WordBox` carries text + bounding box (for the overlay and for
anchoring the warning re-read).

- `rapidocr_reader.py` — **hot path** (ONNX, bundled models, offline, angle-robust).
- `easyocr_reader.py`, `paddle_reader.py` — optional bake-off entrants (heavier; opt-in extras).
- `build_reader()` returns the configured reader (`LABELCHECK_READER`, default `rapidocr`).

The engine choice is **measured, not assumed** — see [`docs/evaluation.md`](docs/evaluation.md)
and [`docs/adr/0001-pluggable-reading-layer.md`](docs/adr/0001-pluggable-reading-layer.md).

### Rules engine — `app/rules/`
- `rulesets.py` — a declarative **`FieldPolicy` table per commodity** (distilled spirits, wine,
  malt beverage): which comparator runs for each field, with what params. Adding a rule edits
  data, not code.
- `comparators.py` — the field checks: `match_text` (fuzzy, fold-normalized — so "STONE'S THROW"
  ≈ "Stone's Throw"), `match_abv` / `match_abv_wine` (numeric tolerances, the 14% wine class
  line), `match_net_contents`, `match_responsible_party`, `match_country_of_origin`,
  `require_phrase` (sulfites).
- `warning.py` + `warning_region.py` + `bold/detector.py` + `spec/government_warning.py` — the
  **government health warning**: exact wording (ordered token alignment), ALL-CAPS, and bold
  (OpenCV stroke-width, OCR-free; optional model tiebreak when unclear).
- `result.py` — `Verdict` (`PASS` < `WARN` < `NEEDS_REVIEW`) and `LabelResult.from_fields()`,
  the **single** place the label verdict is derived (overall = worst field).

### Pipeline — `app/pipeline.py`
Orchestrates read → evaluate → (escalate) and assembles the final `LabelResult`. Records
per-stage timings (`ocr`, `tier1_reread`, `tier1_rescues`, `tier2_model`).

### Escalation — `app/escalation.py`
The optional Tier-2 vision-LLM (cloud). Two prompts: `_LABEL_PROMPT` (transcribe fields) and
`_BOLD_PROMPT` (bold tiebreak). Declared-blind (the model only sees the image, never the
declared values, so it can't "helpfully" match). Off unless `WARNING_ESCALATION_MODEL` is set.

### API + store + frontend
- `app/api/applications.py` — submit (`/preview` non-persisting self-check; `POST` to queue),
  list, get-with-verification, decide, image. Upload size + pixel caps; clean JSON errors.
- `app/store.py` — SQLite (with an in-memory test double); nothing sensitive retained.
- `frontend/` — React SPA: applicant submit, agent queue (triaged by verdict), review view with
  the label + hover-highlighted regions; WCAG-AA.

## Request lifecycle (one label)

```
POST /api/applications/preview  (declared fields + image)
  → _decode_or_400 (size/pixel-bomb guards)
  → verify_label → LabelResult + per-field evidence
  → serialize → JSON           (NOT persisted — submit-time self-check)
POST /api/applications         (applicant confirms) → persisted, status "submitted"
GET  /api/applications/{id}    → runs + caches verification → review view
POST /api/applications/{id}/decision  → status approved|rejected|needs_correction (human)
```

## Designed for batch (not yet built)

The agent side is already a **queue**, each application is an **independent unit**, and the
engine is **stateless** — so batch is additive (a bulk-create endpoint + a batch summary), not a
rewrite. See [`docs/specs/2026-06-11-submit-review-decide-flow.md`](docs/specs/2026-06-11-submit-review-decide-flow.md).

## Evaluation harnesses — `eval/`
Separate from the app: the reader bake-off, a synthetic label generator (exact ground truth),
and the model-prompt eval suites (real LLM calls, gated). These are how engine and prompt
choices are validated empirically.
