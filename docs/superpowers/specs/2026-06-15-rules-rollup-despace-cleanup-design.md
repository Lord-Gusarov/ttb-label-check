# Rules engine cleanup: single rollup, despace consolidation, dead-FAIL removal

**Date:** 2026-06-15
**Status:** Approved (design)
**Scope:** Behavior-preserving refactor. No verdict that the system produces today changes.

## Problem

The rules layer accreted two structural smells while being iterated:

1. **The label verdict is set in two places.** `engine.evaluate` computes `overall = worst(fields)`
   (`engine.py:43`), and `pipeline.verify_label` independently recomputes `overall` and hand-builds a
   `LabelResult` over the combined field list (`pipeline.py:200-201`). Both call `worst()`, so the
   *logic* isn't duplicated — but `overall` can be set inconsistently with `fields`, and "what is a
   label's verdict?" is answered in two files.

2. **Five copies of the `despace` text-cleaner that have drifted.** The canonical
   `normalize.despace` (`[a-z0-9]`, strips accents) has been copy-pasted into four more files
   (`serialize.py:26`, `government_warning.py:28`, `warning_region.py:41`, `bold/detector.py:40`)
   with **three different regexes** — some keep digits, some drop them; none of the copies strip
   accents. The differences are accidental drift, not intentional per-field policy, and are a latent
   source of silent mismatches.

3. **A dead `Verdict.FAIL`.** No code path ever produces `Verdict.FAIL`. The system is deliberately
   designed never to auto-fail (uncertain → `NEEDS_REVIEW` → a human decides). The enum member,
   its severity entry, and a sentinel use in `_wt_severity` are the only references; it implies an
   auto-reject capability that does not exist.

4. **A lying docstring.** `normalize.py` claims `normalize()` is "used where case matters (the
   warning's caps check)". The caps check (`warning.py:75`) operates on raw text and never calls it;
   `normalize()` has no external callers (only `fold` uses it internally).

Not in scope: the field comparators (`match_abv`, `match_text`, …) are legitimately per-field and
stay as they are. The warning checks are *not* converted into `FieldPolicy` rows — `check_warning_bold`
needs image pixels (not a text-only comparator signature), and the pipeline re-runs the warning checks
iteratively during OCR escalation. They are a fixed legal constant, correctly distinct from the
per-commodity field table.

## Design

### Part 1 — One rollup authority

Add a factory that is the single place `overall` is derived from `fields`:

```python
# result.py
@classmethod
def from_fields(cls, commodity: str, fields: list[FieldResult]) -> "LabelResult":
    return cls(commodity=commodity, overall=worst([f.verdict for f in fields]), fields=fields)
```

- `engine.evaluate` returns `LabelResult.from_fields(commodity, results)`.
- `pipeline.verify_label` replaces the manual `worst(...)` + `LabelResult(...)` at lines 200-201 with
  `LabelResult.from_fields(commodity, fields)` over the combined (declared + warning) list.
- The plain dataclass constructor stays available (a test fixture builds a `LabelResult` with an
  explicit verdict); the two production sites go through the factory.
- Document the split of responsibility: **the engine scores declared-value fields; the pipeline
  assembles declared + mandatory-warning fields, and `from_fields` rolls up the label verdict once.**

Behavior identical (same `worst()` over the same lists). Invariant gained: a `LabelResult` built via
the factory cannot have an `overall` that disagrees with its `fields`.

### Part 2 — Consolidate `despace`

One implementation in `normalize.py`, with the per-site differences made explicit via flags:

```python
def despace(text: str | None, *, keep_digits: bool = True, strip_accents: bool = True) -> str:
    ...
```

Delete the four copies; each call site passes flags that **exactly preserve** today's behavior:

| Call site | Current regex / behavior | Replacement call |
|---|---|---|
| `warning_region.py` | `[^a-z]` (drops digits, drops accents) | `despace(x, keep_digits=False, strip_accents=False)` |
| `bold/detector.py`  | `[^a-z]` (drops digits, drops accents) | `despace(x, keep_digits=False, strip_accents=False)` |
| `serialize.py`      | `[^a-z0-9]`, accepts `None`            | `despace(x, keep_digits=True, strip_accents=False)` |
| `government_warning.py` | `[^a-z0-9]`                       | `despace(x, keep_digits=True, strip_accents=False)` |

`strip_accents=False` reproduces the copies' behavior on accented input (`[^a-z]`/`[^a-z0-9]` delete
an accented char entirely rather than folding it to ASCII). The existing `normalize.despace` default
behavior (`keep_digits=True, strip_accents=True`) is preserved for any of its own callers.

Drift risk eliminated (one implementation); the digit/accent differences become visible, reviewable
flags. A follow-up could *deliberately* unify the digit/accent policy — that would be a behavior
change and is explicitly out of scope here.

### Part 3 — Delete the dead `FAIL` verdict

- `result.py`: remove `Verdict.FAIL` and its `_SEVERITY` entry; update the severity-order docstring to
  `PASS < WARN < NEEDS_REVIEW`.
- `pipeline.py:88` `_wt_severity` uses `severity(Verdict.FAIL)` as the "no warning_text field present →
  treat as worst" sentinel. Replace with `severity(Verdict.NEEDS_REVIEW) + 1`, which keeps the
  line-177 comparison (`_wt_severity(f1) < _wt_severity(current)`) behaving identically: a missing
  field still sorts worse than any real verdict, so any recovered read is still adopted.
- Mechanical test updates (intent unchanged):
  - `test_rules.py:44-45` — `absent_verdict=Verdict.FAIL` → `Verdict.WARN` (the test verifies
    `absent_verdict` is honored; any verdict serves).
  - `test_pipeline.py:68-69` — `assert ... is not Verdict.FAIL` → assert the verdict is one of
    `{PASS, WARN, NEEDS_REVIEW}` (same intent: automated checks never auto-reject).
  - `test_warning.py:49` — `in (Verdict.FAIL, Verdict.NEEDS_REVIEW)` → `is Verdict.NEEDS_REVIEW`.
  - `test_api_applications.py:69` — drop `"fail"` from the expected-overall tuple.
- Frontend: remove `"fail"` from the `Verdict` union (`types.ts:1`) and the `fail:` entry in the
  `VERDICT` map (`ui.tsx:8`). The backend never emits `"fail"`, so this removes dead UI surface with
  no behavior change. The `"rejected"` *status* styling (`ui.tsx:15`) is a different concept and is
  left untouched.
- Docstrings that reference `FAIL` as a live verdict option are corrected; descriptive English
  ("fail-safe", "never a hard FAIL" meaning "never auto-rejects") is left as-is where still accurate.

**This does not change the ability to reject a label.** Rejection is a human decision via
`POST /api/applications/{id}/decision` (`status = "rejected"`), entirely separate from the automated
`Verdict`, and is not touched.

### Part 4 — Fix the `normalize()` docstring

Correct the module docstring: `normalize()` is an internal helper of `fold`, not used by the caps
check. If nothing outside the module imports it, rename to `_normalize` (confirm during planning).

## Testing

The refactor is behavior-preserving, so the **existing suite (124 passing) is the safety net.** Work
part-by-part; run the full backend suite after each part. Only the mechanical FAIL-reference test
edits should change; everything else must stay green. Frontend: `tsc --noEmit` must stay clean.

Two small unit tests are added to lock the new surfaces:
- `despace` flag matrix — digits kept/dropped and accents folded/dropped per the flags.
- `LabelResult.from_fields` invariant — `overall == worst(field verdicts)`.

## Risks

- Low overall (no intended behavior change). The highest-attention spot is `_wt_severity`'s sentinel
  replacement (Part 3); the `+1` keeps the comparison identical and is covered by the existing
  tier-1 rescue tests.
- The `despace` consolidation is byte-for-byte preserving by construction (flags chosen per site);
  the new flag-matrix test guards against a regex mistake in the shared implementation.
