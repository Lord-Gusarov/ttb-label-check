# Label Check — TTB Alcohol Label Verification

A prototype that helps TTB compliance agents verify alcohol-beverage labels. An applicant
submits the declared fields + one label image; the tool reads the label, checks it against the
application and the TTB regulations, and returns explainable, evidence-backed verdicts. A human
always makes the final call.

> Standalone proof-of-concept for a Department of the Treasury take-home. Not integrated with
> COLA; no auth; stores nothing sensitive.

- **Approach, tools & assumptions:** [`docs/design-decisions.md`](docs/design-decisions.md)
- **Architecture:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Reader bake-off (the measured engine choice):** [`docs/evaluation.md`](docs/evaluation.md)
- **Users & flows:** [`docs/users.md`](docs/users.md) · **ADR:** [`docs/adr/`](docs/adr/)

## What it does

A submit → review → decide flow over a verification engine:

1. **Submit** — declared fields (brand, class/type, ABV, net contents, responsible party,
   country of origin) + one combined label image.
2. **Verify** — read the label and check each mandatory element: the declared fields *match*,
   and the **government health warning** is present, ALL-CAPS, and bold. Each field gets a
   verdict (`PASS` / `NEEDS REVIEW`) with evidence — declared vs. found, and a bounding-box
   overlay on the label.
3. **Decide** — an agent reviews the queue and records **Approve / Reject / Needs Correction**.

**The tool advises; it never auto-rejects.** Anything it can't confidently clear is
`NEEDS REVIEW` for a human — the design deliberately flags rather than fails.

## How it's built (the one-paragraph version)

Two tiers, cheapest first. A **local, deterministic** tier does the work for the common case:
fast OCR (RapidOCR) reads the label, and a deterministic rules engine renders the verdict — so
compliance is exact, reproducible, and auditable, and it runs **air-gapped** (no cloud egress,
per the agency firewall). Only when the local tier can't confidently clear a label does an
**optional model tier** (a vision LLM) re-read it — **opt-in and off by default**, fail-safe,
and never the thing that decides legality. The model reads; the rules decide. See
[`docs/design-decisions.md`](docs/design-decisions.md) for why, and what we measured.

## Stack

- **Backend:** Python 3.12, FastAPI, OpenCV, RapidOCR (ONNX, offline). SQLite store.
- **Frontend:** Vite + React + Tailwind, WCAG-AA, fonts vendored (no CDN).
- **Packaging:** one Docker image; the backend serves the built SPA.

## Setup & run (local dev)

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+. No system OCR binary needed
(RapidOCR ships its own models).

```bash
# Backend — http://localhost:8000
cd backend
uv sync --extra readers --extra dev      # 'readers' = RapidOCR; 'dev' = tests/lint/types
uv run uvicorn app.main:app --reload

# Frontend — http://localhost:5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, go to **Submit**, fill the fields, drop a label image (samples
in `backend/tests/fixtures/labels/`), and **Check** → **Submit** → review it in the **Queue**.

## Run as one container

```bash
docker build -t label-check .
docker run -p 8000:8000 label-check       # open http://localhost:8000
```

## Tests

```bash
cd backend  && uv run pytest              # backend suite (offline, deterministic)
cd backend  && uv run mypy app            # type gate
cd frontend && npx tsc -p tsconfig.app.json --noEmit   # frontend type gate
cd frontend && npx playwright test        # end-to-end (auto-starts both servers)
```

**Evals** (measured quality, not unit tests) live in `eval/` and are opt-in:

```bash
node frontend/scripts/contrast-check.mjs                  # WCAG-AA color audit
cd eval && uv run --project ../backend pytest             # eval-harness unit tests (offline)
# Live model-prompt evals (real LLM calls) — opt-in:
cd eval && RUN_LLM_EVAL=1 uv run --project ../backend pytest tests/test_llm_prompts.py
```

## Optional: enable the model tier

Off by default (fully local). To turn on the Tier-2 vision-LLM escalation:

```bash
export WARNING_ESCALATION_MODEL=openai:gpt-5.4-mini      # opt-in; unset = air-gapped
export OPENAI_API_KEY=sk-...                             # or ~/.oai_key
```

It is fail-safe: if the key/network/model is unavailable it degrades to the local verdict and
a human review — it can never block or crash a verification.

## Deployed application

Single container, any host that runs Docker (the agency runs on Azure; this is a plain
image). Build/run as above, or deploy the image to a container service.

> **Live prototype:** _<add deployed URL here>_

## Scope & limitations

A prototype, intentionally bounded — see [`docs/design-decisions.md`](docs/design-decisions.md)
for the full list and rationale. In short: one combined image per application; three commodities
(distilled spirits seeded deepest; wine/malt structural); single-application flow (batch is
designed-for but not built); no COLA integration, no auth, nothing sensitive stored.
