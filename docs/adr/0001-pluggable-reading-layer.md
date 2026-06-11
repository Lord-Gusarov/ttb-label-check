# ADR 0001 — Local-first pluggable reading layer (RapidOCR hot-path, VLM fallback)

- **Status:** Accepted (2026-06-11)
- **Deciders:** engineering
- **Related:** `docs/evaluation.md` (the living bench data), `app/readers/`, `app/config.py`

## Context

The tool must read alcohol-beverage label images and extract text for the rules engine.
Constraints from the stakeholder interviews and the TTB domain:

1. **< 5 s per label** — the prior vendor died at 30–40 s; adoption requires speed.
2. **No cloud egress** — the agency firewall blocks outbound ML endpoints, so the reader
   must run **fully local** (this killed the prior vendor's cloud features).
3. **Auditability** — compliance verdicts must be deterministic; a model may *read* the
   label, but rules (not a model) decide pass/fail.
4. **Real-world variation** — real labels have intra-label rotation, curved/arced text,
   vertical text, perspective warp, condensed type, and multi-panel layouts. A reader that
   only handles clean flat text is not enough.

No single reader is best on all axes, and the right choice may change with hardware (CPU vs
GPU) or as inputs shift toward photographed bottles. So the decision must be **revisitable**.

## Decision

A **pluggable reading layer**: one interface `Reader.extract(image) -> {text, word_boxes,
confidence}` (`app/readers/base.py`) with interchangeable local adapters — `tesseract`,
`rapidocr`, `easyocr`, `paddleocr`, and a local VLM `vlm` (Florence-2). Adapters whose deps
aren't installed report `available() == False` and are skipped.

The hot-path reader is **chosen by a bake-off, not by reputation** (`bench/bakeoff.py`),
measured on a corpus that includes realistic intra-label variation. The selection rule is
**best field accuracy within the 5 s budget**.

- **Hot path: `rapidocr`** — best accuracy among engines that fit the budget.
- **Fallback: `vlm`** — confidence-gated (`FallbackReader`); most accurate overall but too
  slow on CPU for the hot path. Becomes viable as primary on a GPU host (one env-var swap).
- **Warning/bold checks read with `tesseract` internally** — it gives word-level boxes
  (needed to isolate "GOVERNMENT WARNING" and crop it) on flat artwork, regardless of the
  primary reader.

Configuration is env-driven (`app/config.py`): `LABELCHECK_READER`,
`LABELCHECK_FALLBACK_READER`, `LABELCHECK_FALLBACK_CONFIDENCE`.

## Bench snapshot (2026-06-11, CPU; full + per-variant data in `docs/evaluation.md`)

| Engine | Field accuracy | p50 latency | Notes |
|---|---|---|---|
| `vlm` (Florence-2) | 96% | 5684 ms | Most accurate; **over the 5 s budget on CPU** → fallback |
| `paddleocr` 3.7 (PP-OCRv5) | 91% | 7518 ms | Over budget on CPU |
| **`rapidocr`** | 87% | **404 ms** | **Chosen** — best accuracy within budget |
| `easyocr` | 85% | 2018 ms | Under budget but slower + less accurate |
| `tesseract` | 75% | 390 ms | Fast; brittle to angle/perspective (reads it confidently-but-wrong) |

Key findings: on clean uniform labels the engines tie; they **diverge on intra-label
variation**, where Tesseract collapses (per-element 40%, vertical 40%, perspective 60%).
Curved-rim "seal" text is hard for *every* engine (~60%). The VLM is the accuracy ceiling
but hardware-bound.

## Consequences

- **Switching engines is one env var** (`LABELCHECK_READER=paddleocr`, etc.); no code change.
- **Adding an engine**: write an adapter implementing `Reader`, decorate with `@register`,
  import it in `app/readers/__init__.py` — it auto-enters `available_readers()` and the bake-off.
- **Re-deciding is reproducible**: drop new/real labels into `corpus/`, re-run
  `python -m bench.bakeoff`; the decision rule re-selects from data and rewrites `evaluation.md`.
- **GPU deployment** would likely promote the VLM (or PaddleOCR) to the hot path — the
  pluggable layer makes that a config change, not a rewrite.
- Cost: maintaining several adapters and their (optional) heavy deps. Mitigated by keeping
  the default install lightweight (Tesseract + RapidOCR) and the rest as optional extras.

## Alternatives considered

- **Tesseract-only** (simplest, fastest, tiny): rejected — collapses on real-world angle/
  perspective and reads rotated text *confidently wrong*, so it can't even be a safe
  fallback-gated primary.
- **Cloud OCR/LLM API** (a hosted multimodal vision service): rejected outright — the firewall
  blocks ML endpoints; this is the exact failure mode of the prior vendor pilot.
- **VLM as primary**: rejected on CPU (5.7 s > budget); reconsider on GPU.
- **Single fixed engine, no abstraction**: rejected — the best choice depends on hardware and
  input mix, both of which can change; locking it in early is premature.
