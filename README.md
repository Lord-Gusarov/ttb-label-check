# Label Check — TTB Alcohol Label Verification

A prototype that helps TTB compliance agents verify alcohol-beverage labels: it reads a
label image, compares it against the application's declared fields and the TTB regulations,
and returns explainable **PASS / NEEDS REVIEW / FAIL** verdicts — fast enough to actually use.

> Standalone proof-of-concept for a Department of the Treasury take-home. Not integrated with
> COLA; stores nothing sensitive.

## Why it's built this way

The stakeholder interviews set hard constraints that drive every decision:

- **< 5 seconds per label** — the prior scanning vendor died at 30–40s, so speed is non-negotiable.
- **No cloud egress** — the agency firewall blocks outbound ML endpoints. Everything runs
  **local-first**; no cloud APIs on the compliance path.
- **Usable by non-technical agents** ("a 73-year-old could figure it out").
- **Batch** of 200–300 labels at once.
- **Trust** — the tool *assists*; a human always decides. Every verdict shows its evidence.

Guiding principle: **the model reads, the deterministic engine decides.** OCR / a local vision
model extracts text; a deterministic rules engine renders the legal verdict — so compliance is
exact, reproducible, and auditable (no model "decides" legality).

The reading layer is **pluggable**: Tesseract / PaddleOCR / EasyOCR / a small local VLM all sit
behind one interface, and a bake-off picks the hot-path engine by measured latency + accuracy.

See `docs/` for the architecture decision records and the evaluation write-up.

## Stack

- **Backend:** Python 3.12, FastAPI, OpenCV, pluggable OCR/VLM readers.
- **Frontend:** Vite + React + Tailwind (built ahead-of-time, vendored — no CDN).
- **Packaging:** one Docker image (Tesseract bundled); the backend serves the built SPA.

## Develop

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, and `tesseract` (`brew install tesseract`).

```bash
# Backend (http://localhost:8000)
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload

# Frontend (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

## Test

```bash
cd backend && uv run pytest        # backend golden tests
cd frontend && npm run build       # type-check + production build
```

## Run as one container

```bash
docker build -t label-check .
docker run -p 8000:8000 label-check   # open http://localhost:8000
```

## Status

Scaffold complete (FastAPI + React shell, single-container Docker). Reader bake-off, rules
engine, government-warning/bold checks, annotation UI, and batch processing are in progress —
see the task list and `docs/`.
