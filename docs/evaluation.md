# Reader Bake-Off

Empirical comparison of OCR engines on the test corpus — clean labels plus realistic hard cases with **intra-label variation** (per-element rotation, arced/curved text, vertical text, perspective warp, condensed type, multi-panel, and a second commodity). The hot-path reader is chosen from this data; other engines remain one-line swaps; a local VLM enters as a low-confidence fallback.

> Corpus is synthetic but models real-world label variation; step 8 can add real / AI-generated photographed labels by dropping them in `corpus/`.

> **Note (2026-06-15):** the `vlm` (Florence-2) and `tesseract` rows are retained as bake-off
> evidence, but those adapters are **no longer in the codebase** — `vlm` was over the 5 s budget
> on CPU and never activated; the active reader is `rapidocr`.

## Summary

| Engine | Field accuracy | p50 latency | p95 latency |
|---|---|---|---|
| `vlm` | 96% | 5684 ms | 7026 ms |
| `paddleocr` | 91% | 7518 ms | 8154 ms |
| `rapidocr` | 87% | 404 ms | 452 ms |
| `easyocr` | 85% | 2018 ms | 3563 ms |
| `tesseract` | 75% | 390 ms | 432 ms |

## Decision

**Hot-path reader: `rapidocr`** — best field accuracy within the 5s budget (87% @ 404 ms p50). Kept as swappable alternatives / low-confidence fallbacks: `easyocr`, `paddleocr`, `tesseract`, `vlm`, plus a local VLM for messy photos.

_Finding: on clean uniform labels the engines tie, but on the realistic intra-label variants they diverge sharply — Tesseract collapses on per-element rotation / vertical / perspective text (and reads it confidently-but-wrong, so it can't be trusted as a primary), while the angle-robust engine stays accurate. This is why the reader is swappable and why robustness, not raw speed, wins the hot path. Remaining limitation: still synthetic, not photographed bottles — step 8 can add real labels to `corpus/`._

## Per-variant field accuracy

| Engine | clean | rotated | lowlight | glare | busy | rich_arc_brand | rich_per_element_rotation | rich_vertical_text | rich_condensed | rich_perspective | rich_multipanel | rich_blur_noise | rich_wine_arc_perspective | rich_wine_multipanel | rich_circular_brand | rich_semicircle_brand | rich_seal_medallion |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `vlm` | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 80% | 100% | 60% |
| `paddleocr` | 100% | 100% | 100% | 100% | 100% | 80% | 100% | 80% | 100% | 100% | 100% | 100% | 80% | 100% | 80% | 60% | 60% |
| `rapidocr` | 80% | 100% | 100% | 100% | 80% | 60% | 100% | 100% | 80% | 100% | 100% | 100% | 80% | 100% | 80% | 60% | 60% |
| `easyocr` | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 80% | 80% | 100% | 80% | 80% | 80% | 60% | 60% | 60% | 60% |
| `tesseract` | 100% | 100% | 100% | 80% | 100% | 80% | 40% | 40% | 100% | 60% | 80% | 100% | 20% | 80% | 80% | 60% | 60% |

## Per-variant latency (ms, median)

| Engine | clean | rotated | lowlight | glare | busy | rich_arc_brand | rich_per_element_rotation | rich_vertical_text | rich_condensed | rich_perspective | rich_multipanel | rich_blur_noise | rich_wine_arc_perspective | rich_wine_multipanel | rich_circular_brand | rich_semicircle_brand | rich_seal_medallion |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tesseract` | 388 | 404 | 390 | 385 | 419 | 388 | 381 | 390 | 389 | 366 | 443 | 348 | 374 | 429 | 395 | 392 | 395 |
| `rapidocr` | 486 | 421 | 408 | 397 | 419 | 358 | 404 | 388 | 400 | 344 | 443 | 411 | 318 | 405 | 418 | 361 | 384 |
| `easyocr` | 1581 | 3272 | 1921 | 1678 | 3372 | 2796 | 2918 | 1544 | 1464 | 1447 | 2878 | 1917 | 2018 | 4324 | 3161 | 1148 | 2745 |
| `vlm` | 5702 | 5716 | 5710 | 5725 | 5765 | 5660 | 5510 | 5508 | 5511 | 5496 | 6980 | 5485 | 5654 | 7206 | 5684 | 6358 | 5489 |
| `paddleocr` | 7635 | 8133 | 7549 | 7518 | 8237 | 6050 | 6883 | 7029 | 6862 | 6149 | 7869 | 7319 | 5585 | 7694 | 7778 | 6963 | 7531 |
