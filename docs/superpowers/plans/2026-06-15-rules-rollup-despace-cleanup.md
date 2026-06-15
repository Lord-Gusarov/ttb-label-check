# Rules Engine Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Behavior-preserving cleanup of the rules layer: one authoritative label-verdict rollup, a single `despace` helper, removal of the dead `FAIL` verdict, and a corrected `normalize` docstring.

**Architecture:** No verdict the system produces today changes. The existing backend suite (124 passing) is the safety net — run it after every task; only the explicitly-listed mechanical test edits should change. Two small new unit tests lock the new surfaces.

**Tech Stack:** Python 3.12, FastAPI, pytest (run via `uv run pytest`), OpenCV/numpy. Frontend: React + TypeScript (Vite), checked with `npx tsc --noEmit`.

**Working directory for backend commands:** `/Users/gustavohornedo/gauntlet/label-check/backend`
**Working directory for frontend commands:** `/Users/gustavohornedo/gauntlet/label-check/frontend`

---

## Baseline check (do this first)

- [ ] **Step 0: Confirm the suite is green before any change**

Run (from `backend/`): `uv run pytest -q`
Expected: `124 passed, 3 skipped`

---

## Task 1: Single rollup authority (`LabelResult.from_fields`)

**Files:**
- Test: `backend/tests/test_result.py` (create)
- Modify: `backend/app/rules/result.py` (add classmethod)
- Modify: `backend/app/rules/engine.py:43-44`
- Modify: `backend/app/pipeline.py:200-201` and its import on line 40

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_result.py`:

```python
from app.rules.result import FieldResult, LabelResult, Verdict


def _fr(verdict: Verdict) -> FieldResult:
    return FieldResult("f", "F", verdict, expected=None, found=None, detail="")


def test_from_fields_overall_is_worst():
    fields = [_fr(Verdict.PASS), _fr(Verdict.NEEDS_REVIEW), _fr(Verdict.WARN)]
    lr = LabelResult.from_fields("distilled_spirits", fields)
    assert lr.overall is Verdict.NEEDS_REVIEW
    assert lr.fields == fields
    assert lr.commodity == "distilled_spirits"


def test_from_fields_empty_is_needs_review():
    assert LabelResult.from_fields("wine", []).overall is Verdict.NEEDS_REVIEW
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_result.py -q`
Expected: FAIL — `AttributeError: type object 'LabelResult' has no attribute 'from_fields'`

- [ ] **Step 3: Add the factory to `result.py`**

In `backend/app/rules/result.py`, replace the `LabelResult` class (currently lines 51-57) with:

```python
@dataclass(frozen=True)
class LabelResult:
    """Aggregated result for a whole label."""

    commodity: str
    overall: Verdict
    fields: list[FieldResult] = field(default_factory=list)

    @classmethod
    def from_fields(cls, commodity: str, fields: list[FieldResult]) -> "LabelResult":
        """The single place a label verdict is derived: overall = the worst field verdict.

        Building results through this factory makes it impossible for `overall` to disagree
        with `fields`. `worst([])` is NEEDS_REVIEW, so an empty field list rolls up safely.
        """
        return cls(commodity=commodity, overall=worst([f.verdict for f in fields]), fields=fields)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_result.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Route the engine through the factory**

In `backend/app/rules/engine.py`, replace lines 43-44:

```python
    overall = worst([r.verdict for r in results]) if results else Verdict.NEEDS_REVIEW
    return LabelResult(commodity=commodity, overall=overall, fields=results)
```

with:

```python
    return LabelResult.from_fields(commodity, results)
```

Then fix the now-unused imports on line 10. Change:

```python
from app.rules.result import FieldResult, LabelResult, Verdict, worst
```

to:

```python
from app.rules.result import FieldResult, LabelResult
```

(`Verdict` and `worst` are no longer referenced in `engine.py` — `from_fields` owns the rollup.)

- [ ] **Step 6: Route the pipeline through the factory**

In `backend/app/pipeline.py`, replace lines 200-201:

```python
    overall = worst([f.verdict for f in fields])
    merged = LabelResult(commodity=commodity, overall=overall, fields=fields)
```

with:

```python
    merged = LabelResult.from_fields(commodity, fields)
```

Then remove the now-unused `worst` from the import on line 40. Change:

```python
from app.rules.result import FieldResult, Verdict, severity, worst
```

to:

```python
from app.rules.result import FieldResult, Verdict, severity
```

(`severity` and `Verdict` are still used by `_wt_severity` and the escalation gate; `worst` is not.)

- [ ] **Step 7: Run the full suite to verify nothing changed**

Run: `uv run pytest -q`
Expected: `126 passed, 3 skipped` (124 baseline + 2 new). No failures.

- [ ] **Step 8: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add backend/app/rules/result.py backend/app/rules/engine.py backend/app/pipeline.py backend/tests/test_result.py
git commit -m "rules: single label-verdict rollup via LabelResult.from_fields"
```

---

## Task 2: Consolidate `despace` into one flagged helper

**Files:**
- Test: `backend/tests/test_normalize.py` (create)
- Modify: `backend/app/rules/normalize.py` (extend `despace` signature)
- Modify: `backend/app/serialize.py` (drop local copy, call shared)
- Modify: `backend/app/rules/spec/government_warning.py` (drop local copy)
- Modify: `backend/app/bold/detector.py` (drop local copy + unused `re`)
- Modify: `backend/app/rules/warning_region.py` (drop local copy + unused `re`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_normalize.py`:

```python
from app.rules.normalize import despace


def test_default_keeps_digits_and_folds_accents():
    assert despace("750 mL") == "750ml"
    assert despace("Séléné") == "selene"  # accents folded to ASCII


def test_drop_digits():
    assert despace("war2ning", keep_digits=False) == "warning"


def test_no_strip_accents_drops_accented_char():
    # legacy [^a-z0-9] behavior: an accented char is removed, not folded
    assert despace("café", strip_accents=False) == "caf"


def test_drop_digits_no_accents_matches_legacy_alpha_only():
    assert despace("A1 b-2 C", keep_digits=False, strip_accents=False) == "abc"


def test_none_is_empty():
    assert despace(None) == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_normalize.py -q`
Expected: FAIL — `TypeError` on the `keep_digits`/`strip_accents` keywords (current `despace` takes only `text`), and `despace(None)` raises `AttributeError`.

- [ ] **Step 3: Extend `despace` in `normalize.py`**

In `backend/app/rules/normalize.py`, add a second compiled pattern next to `_NON_ALNUM` (after line 19 `_NON_ALNUM = re.compile(r"[^a-z0-9]+")`):

```python
_NON_ALPHA = re.compile(r"[^a-z]+")
```

Then replace the existing `despace` (currently the last function in the file):

```python
def despace(text: str) -> str:
    """Lowercase, keep only [a-z0-9] — robust to spacing/granularity (750 mL ~ 750mL)."""
    return _NON_ALNUM.sub("", _strip_diacritics(text).lower())
```

with:

```python
def despace(text: str | None, *, keep_digits: bool = True, strip_accents: bool = True) -> str:
    """Strip text to bare characters for spacing-tolerant matching ("750 mL" ~ "750mL").

    keep_digits=False also drops 0-9 (the warning-geometry call sites match digit-free
    anchors). strip_accents folds é→e before stripping (default); strip_accents=False
    drops the accented char entirely, matching the legacy `[^a-z]`/`[^a-z0-9]` behavior.
    """
    s = _strip_diacritics(text or "") if strip_accents else (text or "")
    pattern = _NON_ALNUM if keep_digits else _NON_ALPHA
    return pattern.sub("", s.lower())
```

This is byte-for-byte identical to the old `despace` at the default flags (`keep_digits=True, strip_accents=True`), so the existing `comparators.py` callers are unaffected.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_normalize.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Swap `serialize.py` onto the shared helper**

In `backend/app/serialize.py`:

a) Add the import next to the other `app.rules` imports (after line 8 `from app.rules.result import FieldResult`):

```python
from app.rules.normalize import despace
```

b) Delete the local helper (lines 26-28):

```python
def _despace(text: str | None) -> str:
    """Lowercase, alphanumeric-only — collapses OCR space differences."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())
```

c) Update the two call sites. Change `target = _despace(field.found or field.expected)` to:

```python
    target = despace(field.found or field.expected, strip_accents=False)
```

and change `wt = _despace(w.text)` to:

```python
        wt = despace(w.text, strip_accents=False)
```

Leave `import re` — it is still used by `_tokens`.

- [ ] **Step 6: Swap `government_warning.py` onto the shared helper**

In `backend/app/rules/spec/government_warning.py`:

a) Add an import after the existing `import re` (line 8):

```python
from app.rules.normalize import despace
```

b) Delete the local helper (lines 28-29):

```python
def _despace(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
```

c) Update its call site (`despaced = _despace(candidate)`) to:

```python
    despaced = despace(candidate, strip_accents=False)
```

Leave `import re` — still used by `_tokens`.

- [ ] **Step 7: Swap `bold/detector.py` onto the shared helper**

In `backend/app/bold/detector.py`:

a) Remove the line `import re` (it is used *only* by the local `_despace`).

b) Add an import for the shared helper (with the other imports, e.g. after the numpy import):

```python
from app.rules.normalize import despace
```

c) Delete the local helper (lines 40-41):

```python
def _despace(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())
```

d) Update its call site. Change:

```python
    prefix = [w for w in words if "government" in _despace(w.text) or "warning" in _despace(w.text)]
```

to:

```python
    prefix = [w for w in words if "government" in despace(w.text, keep_digits=False, strip_accents=False)
              or "warning" in despace(w.text, keep_digits=False, strip_accents=False)]
```

- [ ] **Step 8: Swap `warning_region.py` onto the shared helper**

In `backend/app/rules/warning_region.py`:

a) Remove the line `import re` (used *only* by the local `_despace`).

b) Add an import for the shared helper (with the other `app.` imports):

```python
from app.rules.normalize import despace
```

c) Delete the local helper (lines 41-42):

```python
def _despace(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())
```

d) Update both call sites. Change:

```python
    anchors = [w for w in words if "governmentwarning" in _despace(w.text)]
```

to:

```python
    anchors = [w for w in words if "governmentwarning" in despace(w.text, keep_digits=False, strip_accents=False)]
```

and change:

```python
            if "warning" in _despace(w.text) or "surgeongeneral" in _despace(w.text)
```

to:

```python
            if "warning" in despace(w.text, keep_digits=False, strip_accents=False)
            or "surgeongeneral" in despace(w.text, keep_digits=False, strip_accents=False)
```

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: `131 passed, 3 skipped` (126 + 5 new despace tests). No failures — the swaps are behavior-preserving.

- [ ] **Step 10: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add backend/app/rules/normalize.py backend/app/serialize.py backend/app/rules/spec/government_warning.py backend/app/bold/detector.py backend/app/rules/warning_region.py backend/tests/test_normalize.py
git commit -m "rules: consolidate despace into one helper with explicit keep_digits/strip_accents flags"
```

---

## Task 3: Delete the dead `FAIL` verdict (backend)

**Files:**
- Modify: `backend/app/rules/result.py:13-31` (enum + severity + docstring)
- Modify: `backend/app/pipeline.py:88` (sentinel) and docstring line 8
- Modify: `backend/app/rules/warning_region.py` docstring line 12
- Modify: `backend/tests/test_rules.py:43-45`
- Modify: `backend/tests/test_pipeline.py:62-69`
- Modify: `backend/tests/test_warning.py:48-49`
- Modify: `backend/tests/test_api_applications.py:69`

- [ ] **Step 1: Remove `FAIL` from the `Verdict` enum and severity map**

In `backend/app/rules/result.py`, update the docstring and members. Replace lines 13-27:

```python
class Verdict(str, Enum):
    """Outcome of a single check or the whole label.

    Severity order (low → high): PASS < WARN < NEEDS_REVIEW < FAIL.
    We hard-FAIL only what we're certain of; anything we can't determine confidently
    is NEEDS_REVIEW — a human decides. (Avoids false-fails that erode agent trust.)
    """

    PASS = "pass"
    WARN = "warn"
    NEEDS_REVIEW = "needs_review"
    FAIL = "fail"


_SEVERITY = {Verdict.PASS: 0, Verdict.WARN: 1, Verdict.NEEDS_REVIEW: 2, Verdict.FAIL: 3}
```

with:

```python
class Verdict(str, Enum):
    """Outcome of a single check or the whole label.

    Severity order (low → high): PASS < WARN < NEEDS_REVIEW.
    The automated checks never auto-reject: anything not confidently determined is
    NEEDS_REVIEW and a human makes the call. (Avoids false-fails that erode agent trust.)
    """

    PASS = "pass"
    WARN = "warn"
    NEEDS_REVIEW = "needs_review"


_SEVERITY = {Verdict.PASS: 0, Verdict.WARN: 1, Verdict.NEEDS_REVIEW: 2}
```

- [ ] **Step 2: Replace the `FAIL` sentinel in `_wt_severity`**

In `backend/app/pipeline.py`, change line 88:

```python
    return severity(f.verdict) if f else severity(Verdict.FAIL)
```

to:

```python
    # No warning_text field present → treat as worse than any real verdict, so any
    # recovered re-read is adopted (preserves the prior FAIL-sentinel comparison).
    return severity(f.verdict) if f else severity(Verdict.NEEDS_REVIEW) + 1
```

- [ ] **Step 3: Fix docstrings that name `FAIL` as a live verdict**

In `backend/app/pipeline.py`, change line 8:

```
*unverified* (NEEDS_REVIEW / FAIL):
```

to:

```
*unverified* (NEEDS_REVIEW):
```

In `backend/app/rules/warning_region.py`, change line 12:

```
original full-image text (which will FAIL / flag a genuinely-missing warning).
```

to:

```
original full-image text (which will flag a genuinely-missing warning).
```

- [ ] **Step 4: Update the tests that referenced `FAIL`**

In `backend/tests/test_rules.py`, replace lines 43-45:

```python
def test_brand_absent_fails():
    v, _, _ = match_text("Nonexistent Brand", OLD_TOM_TEXT, absent_verdict=Verdict.FAIL)
    assert v is Verdict.FAIL
```

with:

```python
def test_brand_absent_uses_absent_verdict():
    v, _, _ = match_text("Nonexistent Brand", OLD_TOM_TEXT, absent_verdict=Verdict.NEEDS_REVIEW)
    assert v is Verdict.NEEDS_REVIEW
```

In `backend/tests/test_pipeline.py`, replace lines 62-69:

```python
def test_automated_verdict_is_never_terminal_fail():
    # Even with a wrong field, NO automated field verdict — and not the overall — is FAIL.
    bad_app = dict(APP, alcohol_content="40% Alc./Vol.", brand_name="NOT THE BRAND")
    out = verify_label(load_image(CLEAN), "distilled_spirits", bad_app)
    assert out.result.overall is not Verdict.FAIL
    assert all(f.verdict is not Verdict.FAIL for f in out.result.fields)
```

with:

```python
def test_automated_verdict_is_never_terminal_fail():
    # Automated checks never auto-reject: every verdict is one of the three review tiers.
    _ALLOWED = (Verdict.PASS, Verdict.WARN, Verdict.NEEDS_REVIEW)
    bad_app = dict(APP, alcohol_content="40% Alc./Vol.", brand_name="NOT THE BRAND")
    out = verify_label(load_image(CLEAN), "distilled_spirits", bad_app)
    assert out.result.overall in _ALLOWED
    assert all(f.verdict in _ALLOWED for f in out.result.fields)
```

In `backend/tests/test_warning.py`, replace lines 48-49:

```python
    r = check_warning_text("BRAND " + reworded)
    assert r.verdict in (Verdict.FAIL, Verdict.NEEDS_REVIEW)
```

with:

```python
    r = check_warning_text("BRAND " + reworded)
    assert r.verdict is Verdict.NEEDS_REVIEW
```

In `backend/tests/test_api_applications.py`, change line 69:

```python
    assert r.json()["overall"] in ("pass", "warn", "needs_review", "fail")
```

to:

```python
    assert r.json()["overall"] in ("pass", "warn", "needs_review")
```

- [ ] **Step 5: Confirm no stray `Verdict.FAIL` / `"fail"` remains in backend**

Run (from repo root): `grep -rn "Verdict.FAIL\|\"fail\"" backend/`
Expected: no matches. (Descriptive phrases like "fail-safe" or "never a hard FAIL" in prose are fine and out of scope; the grep above only matches the verdict.)

- [ ] **Step 6: Run the full suite**

Run (from `backend/`): `uv run pytest -q`
Expected: `131 passed, 3 skipped`. No failures.

- [ ] **Step 7: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add backend/app/rules/result.py backend/app/pipeline.py backend/app/rules/warning_region.py backend/tests/test_rules.py backend/tests/test_pipeline.py backend/tests/test_warning.py backend/tests/test_api_applications.py
git commit -m "rules: remove the unused FAIL verdict tier"
```

---

## Task 4: Remove the dead `"fail"` verdict from the frontend

**Files:**
- Modify: `frontend/src/types.ts:1`
- Modify: `frontend/src/ui.tsx:8`

- [ ] **Step 1: Remove `"fail"` from the `Verdict` union**

In `frontend/src/types.ts`, change line 1:

```typescript
export type Verdict = "pass" | "warn" | "needs_review" | "fail";
```

to:

```typescript
export type Verdict = "pass" | "warn" | "needs_review";
```

- [ ] **Step 2: Remove the `fail` entry from the `VERDICT` map**

In `frontend/src/ui.tsx`, delete line 8:

```typescript
  fail: { label: "Fail", cls: "text-fail bg-fail-soft", hex: "#b42318" },
```

Leave the `rejected:` status entry (line 15) untouched — that is a decision *status*, not a verdict.

- [ ] **Step 3: Typecheck**

Run (from `frontend/`): `npx tsc -p tsconfig.app.json --noEmit`
Expected: clean (no output, exit 0). The `VERDICT` map is `Record<Verdict, …>`; after removing `"fail"` from both the union and the map they remain consistent. If tsc complains that a verdict key is missing, the map is missing `pass`/`warn`/`needs_review` — add it; if it complains `"fail"` is not in `Verdict`, the map line was not removed.

- [ ] **Step 4: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add frontend/src/types.ts frontend/src/ui.tsx
git commit -m "ui: drop the unused fail verdict the backend never emits"
```

---

## Task 5: Fix the `normalize()` docstring (and make it private)

**Files:**
- Modify: `backend/app/rules/normalize.py` (rename `normalize` → `_normalize`, fix docstring)

Confirmed during planning: `normalize()` has no callers outside this module (only `fold` uses it). Safe to make private.

- [ ] **Step 1: Confirm there are still no external callers**

Run (from `backend/`): `grep -rn "normalize(" app/ tests/ | grep -v "unicodedata\|_normalize\|def normalize\|NFK"`
Expected: only the call inside `fold` (in `normalize.py`) and the import line in `comparators.py` (which imports `despace, fold`, not `normalize`). No other call sites.

- [ ] **Step 2: Rename the function and its one caller**

In `backend/app/rules/normalize.py`, change the definition:

```python
def normalize(text: str) -> str:
```

to:

```python
def _normalize(text: str) -> str:
```

and inside `fold`, change line 37:

```python
    text = _strip_diacritics(normalize(text)).lower()
```

to:

```python
    text = _strip_diacritics(_normalize(text)).lower()
```

- [ ] **Step 3: Correct the module docstring**

In `backend/app/rules/normalize.py`, replace the docstring's first bullet:

```
- `normalize`: light cleanup (Unicode NFKC, straighten curly quotes, collapse spaces) —
  preserves case, used where case matters (e.g. the warning's caps check, step 4).
```

with:

```
- `_normalize`: internal helper for `fold` — light cleanup (Unicode NFKC, straighten
  curly quotes, collapse spaces), preserving case.
```

- [ ] **Step 4: Run the full suite**

Run (from `backend/`): `uv run pytest -q`
Expected: `131 passed, 3 skipped`. No failures.

- [ ] **Step 5: Commit**

```bash
cd /Users/gustavohornedo/gauntlet/label-check
git add backend/app/rules/normalize.py
git commit -m "rules: make normalize a private helper and fix its docstring"
```

---

## Final verification

- [ ] **Backend suite green:** from `backend/`, `uv run pytest -q` → `131 passed, 3 skipped`.
- [ ] **Frontend typechecks:** from `frontend/`, `npx tsc -p tsconfig.app.json --noEmit` → clean.
- [ ] **No FAIL verdict anywhere:** from repo root, `grep -rn "Verdict.FAIL\|\"fail\"" backend/ frontend/src/` → no matches.
- [ ] **One despace:** from repo root, `grep -rn "def _despace" backend/` → no matches (only `def despace` in `normalize.py`).

## Notes on what is intentionally NOT done

- The per-site digit/accent differences are *preserved* via flags, not unified. Actually unifying the
  digit/accent policy would change verdicts and is a deliberate follow-up, out of scope here.
- The warning checks are not converted into `FieldPolicy` rows (they need image pixels and run
  iteratively during OCR escalation; they are a fixed legal constant, correctly distinct from the
  per-commodity field table).
- The ability to reject a label (human decision via `POST /api/applications/{id}/decision`,
  `status="rejected"`) is untouched.
