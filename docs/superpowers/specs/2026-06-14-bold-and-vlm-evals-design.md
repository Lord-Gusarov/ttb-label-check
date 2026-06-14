# Bold-check redesign + VLM faithfulness evals — design

Date: 2026-06-14
Status: approved (sections 1–3), pending written-spec review

## Problem

Manual testing of the warning **prefix-bold** check fails on real labels even when the
warning *text* passes. Two confirmed examples (combined corpus):

- `24142001000078` (Mr November Cabernet): T2 model **adopted** (`warning_tier=2`), `warning_text`
  PASS, but `warning_bold` → NEEDS_REVIEW → overall NEEDS_REVIEW.
- `24268001000172` (Savannah Vodka): T2 model **invoked but not adopted** (`warning_tier=1`),
  `warning_text` PASS, `warning_bold` → NEEDS_REVIEW.

### Root causes

The bold check (`app/bold/detector.py`) is a relative stroke-width measurement. It assumes a
single OCR box spans the whole warning and slices it into a fixed **left-18% (prefix)** vs
**right-30%+ (body)**. That assumption breaks:

1. **Multi-line / justified warnings** (Savannah): "GOVERNMENT WARNING:" flows inline with the
   body and wraps across lines; OCR returns one box per line. The fixed column split compares
   bold-to-bold (or noise), not prefix-to-body.
2. **Tiny / low-contrast warnings** (Mr November): light text on a dark panel, a few pixels tall;
   stroke width on such glyphs is noise.
3. **Model-path blanking** (wiring bug): when the model tier is adopted, `pipeline.py` calls
   `evaluate_warning(image, model_text, [], None)` with an **empty word list**. Bold is a *visual*
   check that needs OCR boxes to locate the prefix, so on the model path it always returns
   NEEDS_REVIEW by construction. **Escalation makes bold strictly worse.**

The LLM is **not** the cause of the bold failures — it transcribes text and never assesses font
weight. Separately, the LLM reader carries a real faithfulness risk we currently do not measure:
when a warning is partial/illegible, a model that knows the canonical 27 CFR 16.21 wording by
heart may "repair" it from memory, making a non-compliant label look compliant.

## Goals

- **Stream A:** make the prefix-bold check robust on real layouts (multi-line/justified, tiny,
  low-contrast) and fix the model-path wiring; keep it local-first and auditable, with a VLM
  tiebreak only on the genuinely unclear tail.
- **Stream B:** build an on-demand eval harness for the model reader that measures, in a
  direct-to-model setting (Tier 1 absent), **completeness** ("get all legible text") and
  **anti-hallucination** ("never invent removed/illegible wording from memory").

Non-goals: changing the verdict contract (checks recommend NEEDS_REVIEW, never hard FAIL; the
agent decides), reworking Tier-1/Tier-2 sequencing, or adding model calls to the default test run.

## Decisions (from brainstorming)

- **Bold authority: hybrid** — improved local deterministic measurement primary; VLM adjudicates
  only when local is `unclear`.
- **Eval substrate: synthetic degradation + real spot-checks**, with exact ground truth.
- **Hallucination probes:** truncation, box-driven occlusion, and missing-words (gaps) — all three.

---

## Stream A — Bold check redesign

### A1. Local measurement (`app/bold/detector.py`)

Replace the fixed-column slice with **box-based prefix/body selection**:

- **Prefix glyphs** = the word box(es) whose folded text matches `government` / `warning`.
- **Body glyphs** = the other warning-paragraph boxes (spatially below/after the prefix, within
  the warning region).
- Measure mean stroke width (existing distance-transform method) of the prefix crop(s) vs the
  body crop(s). Compare prefix glyphs to body glyphs directly — independent of line geometry, so
  justified/multi-line layouts work.

**Tiny / low-contrast handling:** when prefix glyph height is below a threshold, **upscale** the
crop (~3×) and **contrast-normalize** (CLAHE) before measuring. If the region is still too small
or low-contrast to measure confidently, return `unclear` (do not guess).

Return `BoldFinding(is_bold ∈ {True, False, None}, ratio, detail)`:
- `True` when `ratio >= _BOLD_RATIO` (confident bold) → PASS.
- `False` when `ratio` is confidently below threshold (measured, but not bold).
- `None` when unmeasurable → triggers the VLM tiebreak.

### A2. VLM tiebreak (`app/escalation.py` + `app/rules/warning.py`)

- New focused, fail-safe function `judge_warning_bold(crop) → "yes" | "no" | "unclear"`, separate
  from `escalate_label_read`, reusing the OpenAI plumbing and env gating (`WARNING_ESCALATION_MODEL`;
  `off` disables). It is sent **only the warning-region crop** and asks a narrow question: "Is the
  phrase 'GOVERNMENT WARNING' printed in bold (heavier stroke) relative to the body text? Answer
  yes, no, or unclear. Do not guess." Any failure/unavailability → `None`-equivalent, never raises.
- `check_warning_bold` calls the tiebreak **only** when the local detector returns `None` and
  escalation is enabled. Adopt PASS only on a confident "yes"; otherwise NEEDS_REVIEW (today's
  behavior). The tiebreak fires on the unclear tail only, so latency/egress impact is small.

### A3. Wiring fix (`app/pipeline.py`)

On the model-adopted path, run the bold check on the **local** OCR boxes / region crop
(`read.words` or the anchored `region`), never `[]`. Bold does not depend on the model's text.

### A4. Verdict contract

Unchanged: confident bold → PASS; everything else → NEEDS_REVIEW; never a hard FAIL.

---

## Stream B — VLM faithfulness eval harness

### B1. Degradation library (`corpus/tools/degrade.py`)

Pure, deterministic functions, each returning `(degraded_image, removed_tokens)` (or visible GT):

- `truncate(crop, words, at)` — crop off the tail; removed = tokens after the cut. Real crops.
- `occlude_boxes(crop, word_boxes)` — draw opaque rectangles over chosen word boxes; removed =
  those tokens. Real crops; exact GT from box geometry.
- `render_warning(omit=[...], style)` — typeset the canonical warning with chosen tokens omitted
  (gap is real, not pixel-covered); removed = omitted tokens. Synthetic; supports the
  missing-words / compliance-defect case. Also usable to render clean controls and bold/non-bold
  prefixes for the bold-judge slice.

Legible-but-hard variants for the completeness axis (`blur`, `downscale`, `low_contrast`) remove
nothing → GT = full canonical.

### B2. Eval runner (`corpus/tools/eval_vlm.py`)

Builds cases from real warning crops (via `app.rules.warning_region`) + synthetic renders, and
runs a **warning-focused transcription** on each crop — a dedicated, declared-blind prompt
("transcribe the GOVERNMENT WARNING exactly as printed; empty string if absent/illegible; do not
infer or complete") that reuses the `app/escalation.py` OpenAI plumbing and env gating. (We do not
reuse the full-label `escalate_label_read` prompt, which expects a whole label, not a crop.)
Reports per family and aggregate:

- **token recall** vs visible GT (completeness),
- **token precision** vs visible GT,
- **fabrication rate** = % of content-removed cases whose output contains ≥1 removed/omitted
  canonical token (the headline anti-hallucination metric),
- **bold-judge accuracy** + false-"yes" rate on known bold/non-bold prefix crops.

Token comparison reuses the canonical-token machinery in `app/rules/spec/government_warning.py`
(de-spaced, order-aware) so OCR-style join/split noise does not count as fabrication. Output:
console summary + JSONL under `corpus/real/` (or `corpus/vlm_eval/`).

### B3. Placement / execution

On-demand harness, **not** in the default `pytest` run (nondeterministic, needs egress + key).
One optional `@pytest.mark.vlm` smoke test, skipped unless a key/env is present, asserts
fabrication rate stays under a threshold so regressions are catchable in CI when enabled.

---

## Testing

- **TDD, deterministic, default suite:**
  - `degrade.py` — exact-GT assertions for `truncate` / `occlude_boxes` / `render_warning(omit)`.
  - `app/bold/detector.py` — box-based prefix/body split + upscale path on synthetic images
    (known bold vs non-bold), including a multi-line/justified case and a tiny-glyph case.
  - `app/rules/warning.py` — `check_warning_bold` tiebreak invoked only on local `None`
    (model layer stubbed/monkeypatched; no real egress).
  - `app/pipeline.py` — bold runs on local boxes on the model-adopted path (regression for A3).
- **Measured on-demand (gated):** the `eval_vlm.py` metrics; optional `@pytest.mark.vlm` smoke.

## Risks

- Box-based selection depends on the warning prefix being detected by OCR at all; when it is not,
  bold stays `unclear` → tiebreak (or NEEDS_REVIEW). Acceptable — same fail-safe as today.
- Synthetic degradations may not perfectly mirror real failure modes; the real corpus spot-checks
  and the legible-but-hard family mitigate over-fitting.
- VLM tiebreak adds egress on the unclear tail; gated by `WARNING_ESCALATION_MODEL` and fail-safe,
  so the air-gapped configuration is unaffected.

## Deliverables

- Stream A: revised `app/bold/detector.py`, `app/escalation.py` (`judge_warning_bold`),
  `app/rules/warning.py`, `app/pipeline.py` wiring fix; deterministic tests.
- Stream B: `corpus/tools/degrade.py`, `corpus/tools/eval_vlm.py`; deterministic tests for
  `degrade.py`; optional gated smoke test.
