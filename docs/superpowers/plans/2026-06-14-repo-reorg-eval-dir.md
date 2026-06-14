# Repo reorg — `eval/` separation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all data-generation / quality-measurement code and the eval dataset out of `backend/` into a top-level `eval/` (with its own test suite), leave `backend/` as the service + its hermetic tests, and delete unused fixtures — without changing `app/` runtime or the deployment image.

**Architecture:** Pure relocation + reference rewiring. `git mv` tracked code/fixtures; plain `mv` the untracked 148 MB dataset; repoint path constants and imports; give `eval/` a minimal pytest config so its suite is self-contained. The editable install (`backend/` on `sys.path`, wheel packages only `app`) is unchanged, so `import app` keeps working from `eval/`.

**Tech Stack:** Python 3.12 (pytest, hatchling editable install), React/Vite (Playwright e2e). Backend suite: `cd backend && .venv/bin/python -m pytest`. Eval suite: `cd eval && ../backend/.venv/bin/python -m pytest`. E2e: `cd frontend && npx playwright test`.

Spec: `docs/superpowers/specs/2026-06-14-repo-reorg-eval-dir-design.md`

**Verification anchors** (most edits below are mechanical relocations; these gates catch breakage):
- *Eval suite green* → validates `eval/` imports + `degrade`/`eval_vlm`.
- *Backend suite green* → validates fixture-path moves and that nothing in `app`/tests broke.
- *E2e green* → validates e2e fixture paths.
- *Grep gate* → no stray `corpus`/`bench` path or import references remain.

Note on unexercised scripts: `fetch_cola`, `combine_panels`, `merge_declared`, `analyze_fields`, `eval_combined`, `eval_real`, `generate*`, `bakeoff` are dev/CLI scripts no test runs. Their path edits below are exact but not test-gated — the grep gate is their safety net.

---

## Task 1: Stand up `eval/` and move the harness + its test

**Files:**
- Create: `eval/pyproject.toml`, `eval/tests/` (move `test_degrade.py` here)
- Move (git mv): `backend/corpus/tools/*.py`, `backend/corpus/generate*.py`, `backend/bench/bakeoff.py` → `eval/`
- Modify: `eval/eval_vlm.py`, `eval/tests/test_degrade.py` imports

- [ ] **Step 1: Move the eval code and harness test with git mv**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
mkdir -p eval/tests
git mv backend/corpus/tools/degrade.py            eval/degrade.py
git mv backend/corpus/tools/eval_vlm.py           eval/eval_vlm.py
git mv backend/corpus/tools/fetch_cola.py         eval/fetch_cola.py
git mv backend/corpus/tools/combine_panels.py     eval/combine_panels.py
git mv backend/corpus/tools/merge_declared.py     eval/merge_declared.py
git mv backend/corpus/tools/analyze_fields.py     eval/analyze_fields.py
git mv backend/corpus/tools/eval_combined.py      eval/eval_combined.py
git mv backend/corpus/tools/eval_real.py          eval/eval_real.py
git mv backend/corpus/generate.py                 eval/generate.py
git mv backend/corpus/generate_rich.py            eval/generate_rich.py
git mv backend/corpus/generate_circular.py        eval/generate_circular.py
git mv backend/bench/bakeoff.py                    eval/bakeoff.py
git mv backend/tests/test_degrade.py              eval/tests/test_degrade.py
git rm backend/bench/__init__.py
```

- [ ] **Step 2: Create `eval/pyproject.toml`**

```toml
# Eval suite config only. The package itself isn't built/installed — eval modules are run
# as scripts and imported flat (pythonpath=".") with `app` available via the backend editable install.
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = ["vlm: live VLM eval tests; opt-in via RUN_VLM_EVAL=1 (skipped by default)"]
```

- [ ] **Step 3: Fix the harness's internal import**

In `eval/eval_vlm.py`, replace:
```python
from corpus.tools.degrade import render_label, render_warning
```
with:
```python
from degrade import render_label, render_warning
```

- [ ] **Step 4: Fix the harness test's imports**

In `eval/tests/test_degrade.py`, replace the three `corpus.tools.*` import lines:
```python
from corpus.tools.degrade import truncate, occlude_boxes, render_label, render_warning
```
→
```python
from degrade import truncate, occlude_boxes, render_label, render_warning
```
and
```python
from corpus.tools.eval_vlm import bold_accuracy, fabricated_tokens, label_field_report, recall
```
→
```python
from eval_vlm import bold_accuracy, fabricated_tokens, label_field_report, recall
```
and inside `test_vlm_does_not_fabricate_omitted_word`:
```python
    from corpus.tools.degrade import render_warning
    from corpus.tools.eval_vlm import fabricated_tokens, transcribe_warning
```
→
```python
    from degrade import render_warning
    from eval_vlm import fabricated_tokens, transcribe_warning
```

- [ ] **Step 5: Run the eval suite — expect green**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/eval && ../backend/.venv/bin/python -m pytest -q`
Expected: the `degrade`/metrics tests PASS; `test_vlm_does_not_fabricate_omitted_word` SKIPPED (no `RUN_VLM_EVAL`). If `import app` fails, confirm the backend editable `.pth` is present in `backend/.venv` (it puts `backend/` on `sys.path`).

- [ ] **Step 6: Confirm the backend suite still passes (it no longer owns test_degrade)**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/backend && .venv/bin/python -m pytest -q`
Expected: all pass / skip (fixtures still resolve — `corpus/images` is untouched until Task 2).

- [ ] **Step 7: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add eval/pyproject.toml
git commit -m "Move eval/data-gen scripts and harness into top-level eval/"
```
(The `git mv`/`git rm` are already staged; `git add` picks up the new pyproject. Commit message must not mention any AI assistant.)

---

## Task 2: Repoint eval-script data paths to `eval/data/`

These scripts computed paths relative to `backend/corpus/`; after the move they must point at `eval/data/`. Not test-gated — the grep gate (Task 5) is the backstop.

**Files:** Modify `eval/{fetch_cola,combine_panels,merge_declared,analyze_fields,eval_combined,eval_real,generate,generate_rich,generate_circular,bakeoff}.py`

- [ ] **Step 1: Repoint the dataset scripts (`parent.parent / "real"` → `parent / "data" / "real"`)**

Apply these exact replacements:

`eval/fetch_cola.py`:
```python
OUT = Path(__file__).resolve().parent.parent / "real"
```
→
```python
OUT = Path(__file__).resolve().parent / "data" / "real"
```

`eval/combine_panels.py`, `eval/analyze_fields.py`, `eval/eval_combined.py`, `eval/eval_real.py`, `eval/merge_declared.py` — each has:
```python
REAL = Path(__file__).resolve().parent.parent / "real"
```
→
```python
REAL = Path(__file__).resolve().parent / "data" / "real"
```

- [ ] **Step 2: Repoint the generators to `eval/data/`**

In `eval/generate.py`, replace:
```python
IMAGES_DIR = HERE / "images"
MANIFEST = HERE / "manifest.json"
```
with:
```python
IMAGES_DIR = HERE / "data" / "images"
MANIFEST = HERE / "data" / "manifest.json"
```
Then in `eval/generate_rich.py` and `eval/generate_circular.py`, grep for any output-dir constant that points at `images`/`manifest.json` (e.g. `HERE / "images"`, `parent / "images"`) and repoint it under `… / "data" / …` the same way. Run `grep -nE '"images"|manifest\.json|IMAGES_DIR|MANIFEST' eval/generate_rich.py eval/generate_circular.py` and fix each hit.

- [ ] **Step 3: Repoint bakeoff**

In `eval/bakeoff.py`, replace:
```python
BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "corpus"
```
with:
```python
CORPUS = Path(__file__).resolve().parent / "data"
```
(`bakeoff` then reads `CORPUS / "manifest.json"` and `CORPUS / lab["image"]` from the generated dataset under `eval/data/`.)

- [ ] **Step 4: Sanity import-check (no execution of the scripts)**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/eval && ../backend/.venv/bin/python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('*.py')]; print('all eval scripts parse OK')"`
Expected: `all eval scripts parse OK` (catches typos from the edits).

- [ ] **Step 5: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add eval/*.py
git commit -m "Repoint eval scripts at eval/data/"
```

---

## Task 3: Move fixtures, delete unused images, move the dataset

**Files:**
- Move (git mv): 3 fixtures → `backend/tests/fixtures/labels/`
- Delete (git rm): ~14 unused images; `backend/corpus/manifest.json` (becomes gitignored data)
- Move (plain mv): `backend/corpus/real` → `eval/data/real`; `backend/corpus/manifest.json` content if needed

- [ ] **Step 1: Move the 3 referenced fixtures**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
mkdir -p backend/tests/fixtures/labels
git mv backend/corpus/images/old_tom_clean.png          backend/tests/fixtures/labels/old_tom_clean.png
git mv backend/corpus/images/old_tom_rich_circular.png  backend/tests/fixtures/labels/old_tom_rich_circular.png
git mv backend/corpus/images/old_tom_rich_vertical.png  backend/tests/fixtures/labels/old_tom_rich_vertical.png
```

- [ ] **Step 2: Delete the ~14 unreferenced images**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git rm backend/corpus/images/old_tom_busy.png backend/corpus/images/old_tom_glare.png \
       backend/corpus/images/old_tom_lowlight.png backend/corpus/images/old_tom_rotated.png \
       backend/corpus/images/old_tom_rich_arc.png backend/corpus/images/old_tom_rich_blurnoise.png \
       backend/corpus/images/old_tom_rich_condensed.png backend/corpus/images/old_tom_rich_multipanel.png \
       backend/corpus/images/old_tom_rich_perelement.png backend/corpus/images/old_tom_rich_perspective.png \
       backend/corpus/images/old_tom_rich_seal.png backend/corpus/images/old_tom_rich_semicircle.png \
       backend/corpus/images/cedar_ridge_rich_arc_persp.png backend/corpus/images/cedar_ridge_rich_multipanel.png
```

- [ ] **Step 3: Move the dataset + synthetic manifest into `eval/data/` (gitignored)**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
mkdir -p eval/data
[ -d backend/corpus/real ] && mv backend/corpus/real eval/data/real          # 148M, untracked
git rm --cached backend/corpus/manifest.json 2>/dev/null || true              # stop tracking (becomes gitignored data)
[ -f backend/corpus/manifest.json ] && mv backend/corpus/manifest.json eval/data/manifest.json
# corpus/ should now be empty (images dir emptied, real moved, manifest moved)
rmdir backend/corpus/images backend/corpus 2>/dev/null || true
rmdir backend/bench 2>/dev/null || true
```

- [ ] **Step 4: Verify the corpus/bench dirs are gone and nothing tracked remains**

Run: `cd /Users/gustavohornedo/gauntlet/label-check && ls backend | grep -E "corpus|bench" || echo "corpus/bench removed"; git ls-files 'backend/corpus/*' 'backend/bench/*' | head`
Expected: `corpus/bench removed`; no tracked files listed.

- [ ] **Step 5: Do NOT commit yet**

The moves above leave the backend suite red (tests still point at `corpus/images`). Stage them but
commit together with the path edits in Task 4, so every commit leaves the suites green. The
`git mv`/`git rm`/`git rm --cached` from this task are already staged; proceed directly to Task 4.

---

## Task 4: Repoint backend test fixture paths + e2e (and commit the Task 3 moves)

**Files:** Modify `backend/tests/{test_api_applications,test_engines,test_pipeline,test_readers,test_warning_region}.py`, `frontend/e2e/submit-review.spec.ts`

- [ ] **Step 1: Replace the fixture-path constants (5 backend test files)**

Replace every occurrence of `Path(__file__).resolve().parents[1] / "corpus" / "images"` with `Path(__file__).resolve().parent / "fixtures" / "labels"`:

`backend/tests/test_api_applications.py` (lines 9 and 111), `backend/tests/test_engines.py` (19), `backend/tests/test_readers.py` (11), `backend/tests/test_warning_region.py` (152, 177, 196):
```python
... = Path(__file__).resolve().parents[1] / "corpus" / "images" / "old_tom_clean.png"
```
→
```python
... = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"
```

`backend/tests/test_pipeline.py` (line 25):
```python
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "images"
```
→
```python
CORPUS = Path(__file__).resolve().parent / "fixtures" / "labels"
```

- [ ] **Step 2: Repoint the real-corpus path in test_warning_region**

`backend/tests/test_warning_region.py` (line 121):
```python
_REAL = Path(__file__).resolve().parents[1] / "corpus" / "real" / "images"
```
→
```python
_REAL = Path(__file__).resolve().parents[2] / "eval" / "data" / "real" / "images"
```
(`skipif`-guarded; absent in CI, so it skips — unchanged behavior.)

- [ ] **Step 3: Repoint the 3 e2e image paths**

In `frontend/e2e/submit-review.spec.ts`, replace each `../backend/corpus/images/<name>.png` with `../backend/tests/fixtures/labels/<name>.png`:
```typescript
const LABEL = path.resolve("../backend/corpus/images/old_tom_rich_vertical.png");
```
→
```typescript
const LABEL = path.resolve("../backend/tests/fixtures/labels/old_tom_rich_vertical.png");
```
and the same for `old_tom_rich_circular.png` (arc test) and `old_tom_clean.png` (triage test).

- [ ] **Step 4: Run the backend suite — expect green**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/backend && .venv/bin/python -m pytest -q`
Expected: all pass / skip; fixture-dependent tests now resolve from `tests/fixtures/labels/`.

- [ ] **Step 5: Run the e2e — expect green**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/frontend && npx playwright test e2e/submit-review.spec.ts --reporter=line`
Expected: 3 passed (boots its own backend on :8000 — ensure nothing stale is bound there first: `lsof -ti tcp:8000 | xargs kill 2>/dev/null || true`).

- [ ] **Step 6: Commit (the Task 3 moves + these path edits together)**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add -A backend/tests frontend/e2e/submit-review.spec.ts backend/corpus backend/bench
git commit -m "Relocate fixtures to tests/fixtures/labels, drop unused images, repoint tests/e2e"
```
This single commit captures: the fixture moves, the 14 deletions, the manifest untrack, and the
path edits — so the backend suite is green at commit time (verified in Step 4).

---

## Task 5: Ignore/build config + grep gate

**Files:** Modify `.gitignore`, `.dockerignore`, `backend/pyproject.toml`

- [ ] **Step 1: Gitignore the dataset**

Append to `.gitignore`:
```
# Eval dataset (generated / downloaded; regenerated via eval/fetch_cola.py + eval/generate*.py)
eval/data/
```

- [ ] **Step 2: Trim the Docker build context**

In `.dockerignore`, add (the image already excludes these via the selective `COPY backend/app`; this just shrinks the context):
```
eval
backend/tests
backend/data
```

- [ ] **Step 3: Remove the now-unused vlm marker from backend pyproject**

In `backend/pyproject.toml`, under `[tool.pytest.ini_options]`, delete the line:
```toml
markers = ["vlm: live VLM eval tests; opt-in via RUN_VLM_EVAL=1 (skipped by default)"]
```
(The `vlm` marker now lives in `eval/pyproject.toml`; no backend test uses it.)

- [ ] **Step 4: Grep gate — no stray path/import references remain**

Run:
```bash
cd /Users/gustavohornedo/gauntlet/label-check
grep -rnE '"corpus"|corpus/|corpus\.tools|backend/corpus|/bench/|backend\.bench|from bench|import bench' \
  backend frontend eval --include=*.py --include=*.ts --include=*.toml --include=*.json 2>/dev/null \
  | grep -vE 'eval/data/|\.venv|node_modules'
```
Expected: **no output** for real path/import references. (Comment-only mentions like "real-corpus finding" are acceptable; if any appear, confirm they're prose, not paths/imports.)

- [ ] **Step 5: Verify git ignores the dataset**

Run: `cd /Users/gustavohornedo/gauntlet/label-check && git check-ignore eval/data && echo "dataset ignored"`
Expected: `eval/data` printed + `dataset ignored`.

- [ ] **Step 6: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add .gitignore .dockerignore backend/pyproject.toml
git commit -m "Ignore eval/data, trim docker context, move vlm marker to eval"
```

---

## Final verification

- [ ] Backend suite: `cd backend && .venv/bin/python -m pytest -q` → all pass / skip.
- [ ] Eval suite: `cd eval && ../backend/.venv/bin/python -m pytest -q` → degrade/metrics pass, vlm skipped.
- [ ] Frontend typecheck: `cd frontend && npx tsc --noEmit` → clean.
- [ ] E2e: `cd frontend && npx playwright test` → all pass.
- [ ] Grep gate (Task 5 Step 4) → no stray references.
- [ ] `git status` → clean; `du -sh backend` shows the 148 MB dataset gone from `backend/`.
