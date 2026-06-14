# Repo cleanup & reorg — `eval/` separation — design

Date: 2026-06-14
Status: approved (design), pending written-spec review

## Problem

Dev/research code and large datasets live *inside* `backend/`, conflated under `backend/corpus/`
(+ `backend/bench/`). `backend/corpus/` is 176 MB and mixes three unrelated things: generator/
fetcher **scripts**, synthetic test **fixtures**, and a 148 MB downloaded **dataset**. None of
the scripts or data are part of the backend service (the Dockerfile already ships only `app/`),
yet they bloat the working tree, the build context, and the mental model of "what is the backend."
The 148 MB `corpus/real/` is untracked but **not** gitignored — one `git add -A` from a huge commit.

## Goal

Industry-standard separation:
- `backend/` = the deployable FastAPI **service** (`app/`) and its **hermetic** tests.
- `frontend/` = the UI.
- `eval/` (new, repo root) = everything that **generates data or measures verification quality** —
  generators, fetchers, dataset-shapers, the eval harnesses, their helpers, the dataset, and the
  harness's own tests. Never deployed.

Non-goals: changing `app/` runtime behavior; changing the deployment image (already correct);
renaming the eval scripts (keep current filenames to minimize churn).

## Decisions (from brainstorming)

1. New top-level **`eval/`** holds all non-service code + the dataset. No generic `tools/` junk drawer.
2. **Two test suites:** `backend/tests/` stays the fast, hermetic, CI-gating service suite;
   `eval/tests/` covers the harness (slower / model-gated). Each suite is self-contained.
3. **Delete** the ~14 unused synthetic images; keep only the 3 the tests/e2e use, as committed
   fixtures under `backend/tests/fixtures/labels/`.
4. The 148 MB real dataset moves to **`eval/data/`** and is **gitignored**.

## Target structure

```
repo/
  backend/
    app/                       # service — UNCHANGED (the only dir the image COPYs)
    tests/
      fixtures/labels/         # old_tom_clean.png, old_tom_rich_circular.png,
                               #   old_tom_rich_vertical.png   (committed)
      conftest.py  test_*.py   # service tests only
    pyproject.toml
  frontend/
  eval/
    generate.py  generate_rich.py  generate_circular.py
    fetch_cola.py  combine_panels.py  merge_declared.py  analyze_fields.py
    eval_combined.py  eval_real.py  eval_vlm.py  degrade.py  bakeoff.py
    data/                      # synthetic + real + combined dataset — GITIGNORED
    tests/                     # tests for the eval helpers (degrade / metrics)
    pyproject.toml             # eval-suite pytest config only
  docs/
```

`backend/corpus/` and `backend/bench/` cease to exist.

## File moves (current → target)

**Fixtures (committed):**
- `backend/corpus/images/old_tom_clean.png` → `backend/tests/fixtures/labels/old_tom_clean.png`
- `backend/corpus/images/old_tom_rich_circular.png` → `backend/tests/fixtures/labels/old_tom_rich_circular.png`
- `backend/corpus/images/old_tom_rich_vertical.png` → `backend/tests/fixtures/labels/old_tom_rich_vertical.png`

**Delete (~14 unreferenced):** `old_tom_busy/glare/lowlight/rotated`,
`old_tom_rich_arc/blurnoise/condensed/multipanel/perelement/perspective/seal/semicircle`,
`cedar_ridge_rich_arc_persp`, `cedar_ridge_rich_multipanel`.

**Eval code (→ `eval/`):**
- `backend/corpus/generate.py`, `generate_rich.py`, `generate_circular.py`
- `backend/corpus/tools/{degrade,eval_vlm,fetch_cola,combine_panels,merge_declared,analyze_fields,eval_combined,eval_real}.py`
- `backend/bench/bakeoff.py` (drop `backend/bench/__init__.py`)

**Eval-harness tests (→ `eval/tests/`):**
- `backend/tests/test_degrade.py` → `eval/tests/test_degrade.py`

**Dataset (→ gitignored):**
- `backend/corpus/real/` → `eval/data/real/`
- `backend/corpus/manifest.json` → `eval/data/manifest.json` (regenerable synthetic index; verify
  nothing imports it — if unused, it simply lives in the gitignored data dir)

## Import & path wiring

**Editable install is unchanged.** The wheel packages only `app`; the editable `.pth` puts
`backend/` on `sys.path`, so `import app...` works from anywhere in the venv — including from
`eval/`. No `pyproject` packaging change.

**`eval/` gets its own minimal `pyproject.toml`** with just a pytest section:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]          # so eval/tests can `from degrade import ...`, `from eval_vlm import ...`
markers = ["vlm: live VLM eval tests; opt-in via RUN_VLM_EVAL=1 (skipped by default)"]
```
Eval modules use flat sibling imports (`from degrade import render_warning`) + `from app...` (via
the editable install). Run the eval suite with `cd eval && ../backend/.venv/bin/python -m pytest`.

**Import edits:**
- `eval/eval_vlm.py`: `from corpus.tools.degrade import …` → `from degrade import …`.
- `eval/tests/test_degrade.py`: `from corpus.tools.degrade …`/`from corpus.tools.eval_vlm …`
  → `from degrade …` / `from eval_vlm …`.

**Backend test fixture paths** (`backend/tests/...`): replace `parents[1]/"corpus"/"images"/X`
with `Path(__file__).resolve().parent / "fixtures" / "labels" / X` in `test_pipeline.py`,
`test_api_applications.py`, `test_readers.py`, `test_engines.py`, `test_warning_region.py`.

**Real-dataset path:** `test_warning_region.py`'s `_REAL` (real-corpus, `skipif`-guarded) →
`parents[2] / "eval" / "data" / "real" / "images"`. This is the one deliberate cross-root
reference; it tests `app.rules.warning_region` (service code) so it stays a backend test, and it
never runs in hermetic CI (skips when the dataset is absent). Splitting it out is not worth it.

**Eval scripts' data paths:** `fetch_cola.py`, `eval_combined.py`, `eval_real.py`,
`merge_declared.py`, `analyze_fields.py`, `combine_panels.py`, `generate*.py` currently compute
paths like `Path(__file__).resolve().parent.parent / "real"` (or `/ "images"`). After the move,
repoint them to `eval/data/...` (e.g. `Path(__file__).resolve().parent / "data" / "real"`).
Generators write synthetic output to `eval/data/` (gitignored); the 3 committed fixtures are
independent canonical copies.

**Frontend e2e** (`frontend/e2e/submit-review.spec.ts`): the 3 image paths
`../backend/corpus/images/<name>.png` → `../backend/tests/fixtures/labels/<name>.png`.
`playwright.config.ts` is unchanged (its webServer cwd is `../backend`).

## Ignore / build config

- `.gitignore`: add `eval/data/`. (`backend/data/` already ignored.)
- `.dockerignore`: add `eval`, `backend/tests`, `backend/data` — trims the build context (the image
  already excludes them via the selective `COPY backend/app`).
- `Dockerfile`: unchanged — copies only `backend/app` + built frontend.
- `backend/pyproject.toml`: remove the now-misplaced `markers = ["vlm: …"]` (moves to `eval/pyproject.toml`); everything else unchanged.

## Testing / verification

- **Backend suite** (`cd backend && .venv/bin/python -m pytest`): all pass / skip, hermetic, no
  reference to `corpus`/`bench`. Fixture-dependent tests resolve from `tests/fixtures/labels/`.
- **Eval suite** (`cd eval && ../backend/.venv/bin/python -m pytest`): `test_degrade.py` passes;
  the `@pytest.mark.vlm` case stays skipped without `RUN_VLM_EVAL`.
- **Typecheck**: `cd frontend && npx tsc --noEmit` clean.
- **E2e** (`cd frontend && npx playwright test`): all pass with the new fixture paths.
- **Grep gate**: no remaining `corpus` / `bench` path or import references in `backend/`,
  `frontend/`, `eval/` (comment mentions of "real-corpus finding" etc. are fine).

## Risks

- **Cross-root test reference**: `backend/tests/test_warning_region.py` reaches into `eval/data`
  for its `skipif`-guarded real-corpus cases. Accepted: guarded, never in CI, and it tests app code.
- **Two test suites**: CI must invoke both (`backend` and `eval`). Intentional — different
  stability/gating profiles.
- **`git mv` history**: moving tracked images/scripts preserves history; deleting the 14 unused
  images drops ~24 MB from the working tree (history retains them, which is fine).

## Deliverables

- New `eval/` with all generators/fetchers/harness/bench + `eval/data/` (gitignored) + `eval/tests/`
  + `eval/pyproject.toml`.
- `backend/tests/fixtures/labels/` with the 3 committed fixtures; ~14 unused images deleted;
  `backend/corpus/` and `backend/bench/` removed.
- Updated import/path references across backend tests, eval modules, and the e2e spec.
- `.gitignore`, `.dockerignore`, `backend/pyproject.toml` updated.
- Both suites + tsc + e2e green; grep gate clean.
