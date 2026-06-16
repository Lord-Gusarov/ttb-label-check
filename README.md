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

1. **Submit (with a self-check)** — declared fields (brand, class/type, ABV, net contents,
   responsible party, country of origin) + one combined label image. Before anything is queued,
   the applicant clicks **Check label** and sees the *full* verification result — nothing is
   persisted yet — then chooses **Submit** (clean) or **Submit anyway** (flagged).
2. **Verify** — read the label and check each mandatory element: the declared fields *match*,
   and the **government health warning** is present, ALL-CAPS, and bold. Each field gets a
   verdict (`PASS` / `NEEDS REVIEW`) with evidence — declared vs. found, and a bounding-box
   overlay on the label.
3. **Decide** — an agent reviews the queue and records **Approve / Reject / Needs Correction**.

**The tool advises; it never auto-rejects.** Anything it can't confidently clear is
`NEEDS REVIEW` for a human — the design deliberately flags rather than fails.

**Shift-left verification.** Running the same checks at the *submission* moment lets applicants
catch and fix the obvious mismatches *before* they ever reach an agent — so the queue carries
fewer junk submissions, and what arrives has already been seen by the person who can fix it. The
agents are "drowning in routine stuff"; this moves the routine triage to where it's cheapest.

## How it's built (the one-paragraph version)

Two tiers, cheapest first. A **local, deterministic** tier does the work for the common case:
fast OCR (RapidOCR) reads the label, and a deterministic rules engine renders the verdict — so
compliance is exact, reproducible, and auditable, and most labels are cleared **on-box** with no
outbound call. The harder minority escalate to a **pluggable semantic-validation LLM tier**
(**on by default**, fail-safe, and never the thing that decides legality — the model reads, the
rules decide). That tier is **decoupled**: the demo uses the OpenAI API over HTTPS, but it swaps
cleanly to an in-boundary endpoint (Azure OpenAI in a FedRAMP enclave, or an internal vLLM) for
production — see [Network security & deployment strategy](#network-security--deployment-strategy).
Details + what we measured: [`docs/design-decisions.md`](docs/design-decisions.md).

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

## Model tier (the semantic-validation layer)

**On by default.** The Tier-2 LLM re-reads labels the local tier can't confidently clear. It
needs a key (`$OPENAI_API_KEY` or `~/.oai_key`); it's **fail-safe** — if the key/network/model
is unavailable it degrades to the local verdict + human review, never blocking or crashing.

```bash
export OPENAI_API_KEY=sk-...                          # or ~/.oai_key
# default model is openai:gpt-5.4-mini; override or disable:
export WARNING_ESCALATION_MODEL=openai:gpt-4.1-mini   # swap model/provider
export WARNING_ESCALATION_MODEL=off                   # local-only
```

## Network security & deployment strategy

Stakeholder discovery flagged that the internal network restricts outbound traffic to external
cloud APIs — a constraint that previously broke a third-party vendor integration. We address it
**by architecture, not by disabling capability**, while still meeting the sub-5-second budget:

- **Local edge processing (OCR).** Pixel processing, text extraction, and bounding-box
  coordination run entirely locally (RapidOCR) — the common case is cleared on-box, so most
  labels never need an outbound call.
- **Pluggable semantic-validation layer (LLM).** The harder minority escalate to an LLM. This
  prototype uses the OpenAI API over HTTPS for ease of demonstration, but the client is **fully
  decoupled** — for an agency rollout it swaps, with no change to the verdict logic, for an
  **Azure OpenAI** deployment inside the agency's existing **FedRAMP** boundary, or an
  **internal inference enclave** (e.g. vLLM on government servers) with **zero outbound
  internet**.

So the same design runs entirely inside the agency boundary in production, while the prototype
demonstrates end-to-end behavior over a standard HTTPS endpoint.

## Deployed application

Deployed on **DigitalOcean App Platform** (built from this repo's Dockerfile; instance sized
with headroom for the OCR workload). Any Docker host works — including, in production, an
Azure environment inside the agency boundary.

> **Live prototype:** https://label-check-lbhhi.ondigitalocean.app

## Scope & limitations

A prototype, intentionally bounded — see [`docs/design-decisions.md`](docs/design-decisions.md)
for the full list and rationale. In short: one combined image per application; three commodities
(distilled spirits seeded deepest; wine/malt structural); single-application flow (batch is
designed-for but not built); no COLA integration, no auth, nothing sensitive stored.
