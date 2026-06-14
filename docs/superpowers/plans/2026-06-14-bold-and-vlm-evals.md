# Bold-check redesign + VLM faithfulness evals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the warning-prefix bold check robust on real layouts (multi-line/justified, tiny, low-contrast) with a VLM tiebreak on the unclear tail, and add an on-demand eval harness that measures the model reader's completeness and hallucination on the government warning.

**Architecture:** Two independent phases. Phase A reworks the local bold detector (box-based prefix/body selection + upscaling), adds a focused fail-safe VLM bold adjudicator, wires it as a tiebreak, and fixes the model-path `words=[]` bug. Phase B adds a deterministic degradation library and an on-demand VLM eval runner with exact ground truth. Phase A is independently shippable before Phase B.

**Tech Stack:** Python 3.12, OpenCV (`cv2`), NumPy, Pillow (`PIL`), OpenAI SDK (lazy), pytest. Run tests with `.venv/bin/python -m pytest` from `backend/`.

Spec: `docs/superpowers/specs/2026-06-14-bold-and-vlm-evals-design.md`

---

## File Structure

- Modify `backend/app/bold/detector.py` — box-based prefix/body stroke-width measurement + upscale/CLAHE; `is_bold ∈ {True, False, None}`.
- Modify `backend/app/escalation.py` — add `judge_warning_bold(crop)`; refactor the OpenAI call into a shared helper.
- Modify `backend/app/rules/warning.py` — `check_warning_bold` invokes the VLM tiebreak only on local `None`.
- Modify `backend/app/pipeline.py` — bold runs on local boxes/region on the model-adopted path (never `[]`).
- Create `backend/tests/test_bold.py` — detector geometry + tiebreak unit tests.
- Modify `backend/tests/test_pipeline.py` — regression for the model-path bold wiring.
- Create `backend/corpus/tools/degrade.py` — `truncate`, `occlude_boxes`, `render_warning`.
- Create `backend/corpus/tools/eval_vlm.py` — warning transcription, metrics, runner.
- Create `backend/tests/test_degrade.py` — exact-GT tests for the degradation helpers + metric functions.

---

# Phase A — Bold check

## Task A1: Box-based bold detector

**Files:**
- Modify: `backend/app/bold/detector.py`
- Test: `backend/tests/test_bold.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_bold.py`:

```python
"""Bold detector: box-based prefix/body stroke-width measurement."""

from __future__ import annotations

import cv2
import numpy as np

from app.bold.detector import detect_warning_bold
from app.readers.types import WordBox


def _canvas(h=200, w=600):
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _draw(img, text, org, scale, thickness):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness, cv2.LINE_AA)


def _wb(text, x1, y1, x2, y2):
    return WordBox(text=text, confidence=1.0, bbox=(x1, y1, x2, y2))


def test_bold_prefix_detected_across_separate_lines():
    # Prefix on its own line (thick), body on the next line (thin) — the old fixed
    # left/right slice could not handle this; box-based selection must.
    img = _canvas()
    _draw(img, "GOVERNMENT WARNING", (20, 50), 1.0, 5)   # bold prefix line
    _draw(img, "according to the surgeon general", (20, 120), 0.7, 1)  # thin body line
    words = [
        _wb("GOVERNMENT", 18, 25, 230, 60),
        _wb("WARNING", 240, 25, 400, 60),
        _wb("according to the surgeon general", 18, 95, 470, 130),
    ]
    finding = detect_warning_bold(img, words)
    assert finding.is_bold is True
    assert finding.ratio is not None and finding.ratio >= 1.2


def test_non_bold_prefix_is_not_true():
    img = _canvas()
    _draw(img, "GOVERNMENT WARNING", (20, 50), 0.7, 1)   # same weight as body
    _draw(img, "according to the surgeon general", (20, 120), 0.7, 1)
    words = [
        _wb("GOVERNMENT", 18, 30, 200, 60),
        _wb("WARNING", 210, 30, 360, 60),
        _wb("according to the surgeon general", 18, 95, 470, 130),
    ]
    finding = detect_warning_bold(img, words)
    assert finding.is_bold is not True  # False or None, never a confident bold


def test_no_prefix_box_returns_none():
    img = _canvas()
    finding = detect_warning_bold(img, [_wb("something else", 10, 10, 100, 30)])
    assert finding.is_bold is None
    assert "locate" in finding.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bold.py -v`
Expected: FAIL (current detector uses the fixed-slice logic; `test_bold_prefix_detected_across_separate_lines` fails because prefix/body are separate boxes).

- [ ] **Step 3: Rewrite the detector**

Replace the body of `backend/app/bold/detector.py` below the imports/`BoldFinding`/`_despace`/`_stroke_width` (keep those) with box-based selection:

```python
_BOLD_RATIO = 1.20      # prefix stroke width must exceed body by this factor to read as bold
_NOT_BOLD_RATIO = 1.00  # at/below this (with a confident measurement) reads as NOT bold
_MIN_GLYPH_H = 14       # below this prefix height, upscale + CLAHE before measuring
_BODY_BAND = 8          # search body words within this many prefix-heights below the prefix


def _prep(crop: np.ndarray, glyph_h: int) -> np.ndarray:
    """Upscale + contrast-normalize tiny/low-contrast crops so stroke width is measurable."""
    if glyph_h >= _MIN_GLYPH_H or crop.size == 0:
        return crop
    scale = max(1, round(_MIN_GLYPH_H / max(1, glyph_h)) + 1)
    up = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(up)


def _mean_stroke(gray: np.ndarray, boxes: list[WordBox]) -> float | None:
    """Mean stroke width across the given word boxes (each crop prepped if tiny)."""
    widths: list[float] = []
    for b in boxes:
        x1, y1, x2, y2 = b.bbox
        crop = gray[max(0, y1):y2, max(0, x1):x2]
        sw = _stroke_width(_prep(crop, y2 - y1))
        if sw is not None:
            widths.append(sw)
    return float(np.mean(widths)) if widths else None


def detect_warning_bold(image: np.ndarray, words: list[WordBox] | None) -> BoldFinding:
    """Assess whether 'GOVERNMENT WARNING' is bold relative to the warning body.

    Selects the prefix word boxes ('government'/'warning') and the body word boxes (the
    other warning-paragraph words in a band below the prefix), then compares their mean
    stroke widths. This is independent of line geometry, so justified/multi-line and
    own-line prefixes both work. Tiny/low-contrast crops are upscaled + CLAHE'd first.
    """
    gray = to_grayscale(image)
    words = words or []
    prefix = [w for w in words if "government" in _despace(w.text) or "warning" in _despace(w.text)]
    if not prefix:
        return BoldFinding(None, None, "could not locate the warning prefix to assess bold")

    anchor = min(prefix, key=lambda w: w.bbox[1])  # topmost prefix box
    ah = anchor.bbox[3] - anchor.bbox[1]
    band_bottom = anchor.bbox[1] + max(1, _BODY_BAND * ah)
    prefix_ids = {id(w) for w in prefix}
    body = [
        w for w in words
        if id(w) not in prefix_ids and anchor.bbox[1] - ah <= w.bbox[1] <= band_bottom
    ]
    if not body:
        return BoldFinding(None, None, "no body text near the warning prefix to compare against")

    pw, bw = _mean_stroke(gray, prefix), _mean_stroke(gray, body)
    if pw is None or bw is None or bw <= 0:
        return BoldFinding(None, None, "could not measure stroke width")

    ratio = pw / bw
    if ratio >= _BOLD_RATIO:
        return BoldFinding(True, ratio, f"'GOVERNMENT WARNING' is bold ({ratio:.2f}x body)")
    if ratio <= _NOT_BOLD_RATIO:
        return BoldFinding(False, ratio, f"prefix not heavier than body ({ratio:.2f}x) — verify")
    return BoldFinding(None, ratio, f"bold unclear ({ratio:.2f}x body) — verify the prefix is bold")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bold.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the broader suite (no regressions)**

Run: `.venv/bin/python -m pytest tests/test_warning.py tests/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/bold/detector.py backend/tests/test_bold.py
git commit -m "Bold check: box-based prefix/body selection with upscaling"
```

---

## Task A2: VLM bold adjudicator

**Files:**
- Modify: `backend/app/escalation.py`
- Test: `backend/tests/test_bold.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_bold.py`:

```python
from app import escalation


def test_judge_warning_bold_parses_yes(monkeypatch):
    monkeypatch.setattr(escalation, "_chat_json", lambda *a, **k: {"bold": "yes"})
    monkeypatch.setenv("WARNING_ESCALATION_MODEL", "openai:gpt-5.4-mini")
    assert escalation.judge_warning_bold(np.zeros((40, 120, 3), dtype="uint8")) == "yes"


def test_judge_warning_bold_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("WARNING_ESCALATION_MODEL", "off")
    assert escalation.judge_warning_bold(np.zeros((40, 120, 3), dtype="uint8")) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bold.py -k judge -v`
Expected: FAIL (`judge_warning_bold` / `_chat_json` do not exist).

- [ ] **Step 3: Refactor the OpenAI call into a shared helper and add the adjudicator**

In `backend/app/escalation.py`, add a shared low-level helper and the adjudicator. Add near the other helpers:

```python
def _chat_json(image: np.ndarray, model: str, prompt: str) -> dict | None:
    """One declared-blind image+text chat call returning parsed JSON, or None on any failure."""
    from openai import OpenAI  # lazy

    key = _read_key()
    if not key:
        return None
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        return None
    b64 = base64.b64encode(buf.tobytes()).decode()
    client = OpenAI(api_key=key, timeout=10)
    r = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    )
    return json.loads(r.choices[0].message.content or "{}")


_BOLD_PROMPT = (
    "Look ONLY at this cropped U.S. alcohol-label warning. Is the phrase 'GOVERNMENT WARNING' "
    "printed in bold (a visibly heavier stroke) relative to the body text that follows it? "
    "Do not guess; if you cannot tell, say unclear. Return ONLY JSON: {\"bold\": \"yes\"|\"no\"|\"unclear\"}."
)


def judge_warning_bold(crop: np.ndarray) -> str | None:
    """Best-effort VLM adjudication of prefix bold -> 'yes'|'no'|'unclear', or None when
    escalation is disabled/unavailable. Never raises (fail-safe)."""
    spec = os.environ.get("WARNING_ESCALATION_MODEL", _DEFAULT_MODEL).strip()
    if spec.lower() in _DISABLED:
        return None
    try:
        provider, _, model = spec.partition(":")
        if provider != "openai":
            return None
        data = _chat_json(crop, model or "gpt-5.4-mini", _BOLD_PROMPT)
        if not data:
            return None
        val = str(data.get("bold", "")).strip().lower()
        return val if val in {"yes", "no", "unclear"} else None
    except Exception:  # noqa: BLE001 — must degrade, never crash
        logger.warning("bold adjudication failed; ignoring", exc_info=True)
        return None
```

Then refactor `_openai_read_label` to call `_chat_json` (DRY): replace its body's client/encode block with `data = _chat_json(image, model, _LABEL_PROMPT)` and `return {k: str(data.get(k, "") or "") for k in FIELDS} if data else None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bold.py -k judge -v`
Expected: PASS.

- [ ] **Step 5: Confirm the reader refactor didn't break escalation**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/escalation.py backend/tests/test_bold.py
git commit -m "Add fail-safe VLM bold adjudicator (judge_warning_bold)"
```

---

## Task A3: Wire the tiebreak into check_warning_bold

**Files:**
- Modify: `backend/app/rules/warning.py`
- Test: `backend/tests/test_bold.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_bold.py`:

```python
from app.rules import warning as warning_rules
from app.rules.result import Verdict


def test_tiebreak_promotes_unclear_to_pass(monkeypatch):
    # Local detector unclear -> VLM says yes -> PASS.
    monkeypatch.setattr(warning_rules, "detect_warning_bold",
                        lambda img, words: __import__("app.bold.detector", fromlist=["BoldFinding"]).BoldFinding(None, 1.1, "unclear"))
    monkeypatch.setattr(warning_rules, "judge_warning_bold", lambda crop: "yes")
    fr = warning_rules.check_warning_bold(np.zeros((40, 120, 3), dtype="uint8"), [])
    assert fr.verdict is Verdict.PASS


def test_tiebreak_not_called_when_local_confident(monkeypatch):
    from app.bold.detector import BoldFinding
    monkeypatch.setattr(warning_rules, "detect_warning_bold", lambda img, words: BoldFinding(True, 1.5, "bold"))
    called = {"n": 0}
    def _spy(crop):
        called["n"] += 1
        return "no"
    monkeypatch.setattr(warning_rules, "judge_warning_bold", _spy)
    fr = warning_rules.check_warning_bold(np.zeros((40, 120, 3), dtype="uint8"), [])
    assert fr.verdict is Verdict.PASS and called["n"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bold.py -k tiebreak -v`
Expected: FAIL (`judge_warning_bold` not imported in `warning.py`; tiebreak not wired).

- [ ] **Step 3: Wire the tiebreak**

In `backend/app/rules/warning.py`, add the import and update `check_warning_bold`:

```python
from app.escalation import judge_warning_bold
```

```python
def check_warning_bold(image: np.ndarray, words: list[WordBox] | None) -> FieldResult:
    """Bold via relative stroke width; when the local measure is unclear, a fail-safe VLM
    adjudicates on the warning crop. Never a hard FAIL: confident bold -> PASS, else NEEDS_REVIEW."""
    finding = detect_warning_bold(image, words)
    verdict = Verdict.PASS if finding.is_bold is True else Verdict.NEEDS_REVIEW
    found = f"{finding.ratio:.2f}x body" if finding.ratio is not None else None
    detail = finding.detail
    if finding.is_bold is None:  # unclear -> VLM tiebreak (fail-safe; None when off/unavailable)
        vote = judge_warning_bold(image)
        if vote == "yes":
            verdict, detail = Verdict.PASS, f"{detail}; VLM confirmed bold"
        elif vote in {"no", "unclear"}:
            detail = f"{detail}; VLM bold={vote}"
    return FieldResult(
        "warning_bold", "Warning prefix bold", verdict,
        expected="bold", found=found, detail=detail,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bold.py -k tiebreak -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rules/warning.py backend/tests/test_bold.py
git commit -m "Wire VLM bold tiebreak into check_warning_bold (unclear only)"
```

---

## Task A4: Fix the model-path bold wiring

**Files:**
- Modify: `backend/app/pipeline.py:91-103` (`_model_field_results`)
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline.py`:

```python
def test_model_path_runs_bold_on_local_boxes(monkeypatch):
    """When the model is adopted, bold must use the LOCAL boxes, not an empty list."""
    import numpy as np
    from app import pipeline
    seen = {}

    def _spy_bold(image, words):
        seen["words"] = words
        from app.rules.result import FieldResult, Verdict
        return FieldResult("warning_bold", "Warning prefix bold", Verdict.PASS,
                           expected="bold", found=None, detail="stub")

    monkeypatch.setattr(pipeline, "evaluate_warning",
                        lambda image, text, words, region=None: [_spy_bold(image, words)])
    sentinel = [object()]
    pipeline._model_field_results("distilled_spirits", {}, {"government_warning": "x"},
                                  np.zeros((10, 10, 3), dtype="uint8"), warning_words=sentinel)
    assert seen["words"] is sentinel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py::test_model_path_runs_bold_on_local_boxes -v`
Expected: FAIL (`_model_field_results` has no `warning_words` parameter; currently passes `[]`).

- [ ] **Step 3: Thread local boxes through the model path**

In `backend/app/pipeline.py`, change `_model_field_results` to accept and use local warning words:

```python
def _model_field_results(
    commodity: str, application: dict, model: dict[str, str], image: np.ndarray,
    warning_words: list[FieldResult] | None = None,
) -> list[FieldResult]:
    text = " ".join(
        model.get(k, "")
        for k in ("brand_name", "class_type", "alcohol_content", "net_contents")
    )
    field_results = list(evaluate(commodity, application, text).fields)
    # Bold is VISUAL: assess it on the LOCAL boxes/image, never []. Text fields use the model read.
    warning_results = list(evaluate_warning(image, model.get("government_warning", ""), warning_words or [], None))
    return field_results + warning_results
```

And at the call site (in `verify_label`, the Tier-2 block), pass the local words:

```python
            candidate = _model_field_results(commodity, application, model, image, warning_words=read.words)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "Run bold on local boxes on the model-adopted path (not [])"
```

---

# Phase B — VLM faithfulness evals

## Task B1: Degradation library

**Files:**
- Create: `backend/corpus/tools/degrade.py`
- Test: `backend/tests/test_degrade.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_degrade.py`:

```python
"""Degradation helpers produce exact removed-token ground truth."""

from __future__ import annotations

import numpy as np

from app.readers.types import WordBox
from corpus.tools.degrade import truncate, occlude_boxes, render_warning


def _wb(text, x1, y1, x2, y2):
    return WordBox(text=text, confidence=1.0, bbox=(x1, y1, x2, y2))


def test_truncate_removes_tail_tokens():
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    words = [_wb("alpha", 0, 0, 40, 20), _wb("beta", 0, 40, 40, 60), _wb("gamma", 0, 70, 40, 90)]
    cropped, removed = truncate(img, words, at_y=65)
    assert cropped.shape[0] == 65
    assert removed == ["gamma"]


def test_occlude_boxes_removes_covered_tokens():
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    words = [_wb("alpha", 0, 0, 40, 20), _wb("beta", 50, 0, 90, 20)]
    out, removed = occlude_boxes(img, words, [1])
    assert removed == ["beta"]
    assert (out[0:20, 50:90] == 0).all()  # covered region blacked out
    assert (out[0:20, 0:40] == 255).all()  # untouched word intact


def test_render_warning_omits_tokens_and_reports_them():
    img, removed = render_warning(omit=["not"])
    assert removed == ["not"]
    assert img.ndim == 3 and img.shape[2] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_degrade.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the degradation helpers**

Create `backend/corpus/tools/degrade.py`:

```python
"""Deterministic warning-image degradations with exact removed-token ground truth.

Used by eval_vlm.py to probe the model reader for hallucination: each function returns
(image, removed_tokens) so a model that emits a removed token is provably fabricating.
"""

from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.readers.types import WordBox
from app.rules.spec.government_warning import CANONICAL_WARNING


def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def truncate(image: np.ndarray, words: list[WordBox], at_y: int) -> tuple[np.ndarray, list[str]]:
    """Crop off everything below `at_y`; removed = tokens of words starting at/after the cut."""
    removed: list[str] = []
    for w in words:
        if w.bbox[1] >= at_y:
            removed.extend(_tok(w.text))
    return image[:at_y].copy(), removed


def occlude_boxes(image: np.ndarray, words: list[WordBox], indices: list[int]) -> tuple[np.ndarray, list[str]]:
    """Black out the given word boxes; removed = their tokens."""
    out = image.copy()
    removed: list[str] = []
    for i in indices:
        x1, y1, x2, y2 = words[i].bbox
        out[max(0, y1):y2, max(0, x1):x2] = 0
        removed.extend(_tok(words[i].text))
    return out, removed


def render_warning(omit: list[str] | None = None, width: int = 900) -> tuple[np.ndarray, list[str]]:
    """Typeset the canonical warning with `omit` tokens removed; removed = those tokens."""
    omit = omit or []
    omit_set = {o.lower() for o in omit}
    kept_words = [w for w in CANONICAL_WARNING.split() if w.strip(".,():").lower() not in omit_set]
    text = " ".join(kept_words)

    img = Image.new("RGB", (width, 300), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    # naive word-wrap
    x, y, line = 10, 10, ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) > width - 20:
            draw.text((x, y), line, fill="black", font=font)
            y += 16
            line = word
        else:
            line = trial
    draw.text((x, y), line, fill="black", font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), [o.lower() for o in omit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_degrade.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/corpus/tools/degrade.py backend/tests/test_degrade.py
git commit -m "Add warning degradation helpers (truncate/occlude/render) with exact GT"
```

---

## Task B2: Metric functions + eval runner

**Files:**
- Create: `backend/corpus/tools/eval_vlm.py`
- Test: `backend/tests/test_degrade.py`

- [ ] **Step 1: Write the failing tests (metric functions)**

Append to `backend/tests/test_degrade.py`:

```python
from corpus.tools.eval_vlm import fabricated_tokens, recall


def test_fabricated_tokens_flags_emitted_removed_token():
    # model output contains 'pregnancy' which was removed -> fabrication
    assert fabricated_tokens("during pregnancy because", ["pregnancy"]) == ["pregnancy"]


def test_fabricated_tokens_none_when_absent():
    assert fabricated_tokens("according to the surgeon general", ["pregnancy"]) == []


def test_recall_counts_visible_tokens_found():
    assert recall("alpha beta", ["alpha", "beta", "gamma"]) == 2 / 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_degrade.py -k "fabricated or recall" -v`
Expected: FAIL (module/functions do not exist).

- [ ] **Step 3: Implement the runner and metrics**

Create `backend/corpus/tools/eval_vlm.py`:

```python
"""On-demand VLM faithfulness eval for the government-warning read.

Direct-to-model (Tier 1 absent): degrade warning crops/renders with KNOWN removed tokens,
transcribe each with a declared-blind warning prompt, and measure completeness (recall) and
hallucination (fabricated = model emits a removed token). Not part of the default test suite.

Usage:  python corpus/tools/eval_vlm.py
"""

from __future__ import annotations

import re

import numpy as np

from app.escalation import _chat_json
from corpus.tools.degrade import render_warning


def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def fabricated_tokens(output: str, removed: list[str]) -> list[str]:
    """Removed tokens that nonetheless appear in the model output (= hallucinated)."""
    out = set(_tok(output))
    return [t for t in removed if t.lower() in out]


def recall(output: str, visible: list[str]) -> float:
    """Fraction of visible ground-truth tokens present in the output."""
    if not visible:
        return 1.0
    out = set(_tok(output))
    return sum(1 for t in visible if t.lower() in out) / len(visible)


_WARNING_PROMPT = (
    "Transcribe the GOVERNMENT WARNING in this cropped image EXACTLY as printed. Do not infer, "
    "complete, or correct anything; if a word is missing or unreadable, leave it out. Use an empty "
    "string if no warning is present. Return ONLY JSON: {\"government_warning\": \"...\"}."
)


def transcribe_warning(crop: np.ndarray, model: str = "gpt-5.4-mini") -> str:
    data = _chat_json(crop, model, _WARNING_PROMPT)
    return str((data or {}).get("government_warning", ""))


def main() -> None:
    # Missing-words family (synthetic, exact GT): omit one required token at a time.
    cases = [render_warning(omit=[w]) for w in ("not", "pregnancy", "health")]
    fabrications = 0
    for img, removed in cases:
        out = transcribe_warning(img)
        fab = fabricated_tokens(out, removed)
        fabrications += bool(fab)
        print(f"removed={removed} fabricated={fab} :: {out[:80]!r}")
    n = len(cases)
    print(f"\nmissing-words cases: {n}  fabrication-rate: {fabrications}/{n} = {fabrications / n:.0%}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_degrade.py -k "fabricated or recall" -v`
Expected: PASS.

- [ ] **Step 5: Smoke-run the harness manually (optional, needs a key)**

Run: `.venv/bin/python corpus/tools/eval_vlm.py`
Expected: prints per-case fabrication and an aggregate fabrication-rate.

- [ ] **Step 6: Commit**

```bash
git add backend/corpus/tools/eval_vlm.py backend/tests/test_degrade.py
git commit -m "Add VLM warning-faithfulness eval runner + metrics"
```

---

## Task B3: Optional gated smoke test

**Files:**
- Modify: `backend/tests/test_degrade.py`

- [ ] **Step 1: Add a gated smoke test**

Append to `backend/tests/test_degrade.py`:

```python
import os
import pytest


@pytest.mark.vlm
@pytest.mark.skipif(
    os.environ.get("WARNING_ESCALATION_MODEL", "").lower() in {"", "off"}
    and not os.path.exists(os.path.expanduser("~/.oai_key")),
    reason="VLM eval requires a model key; set WARNING_ESCALATION_MODEL + key to run",
)
def test_vlm_does_not_fabricate_omitted_word():
    from corpus.tools.degrade import render_warning
    from corpus.tools.eval_vlm import fabricated_tokens, transcribe_warning

    img, removed = render_warning(omit=["pregnancy"])
    out = transcribe_warning(img)
    assert fabricated_tokens(out, removed) == [], f"model recited removed word: {out!r}"
```

- [ ] **Step 2: Register the marker**

In `backend/pyproject.toml`, under `[tool.pytest.ini_options]`, add (create the key if absent):

```toml
markers = ["vlm: tests that call a real VLM (skipped unless a model key is configured)"]
```

- [ ] **Step 3: Verify it is skipped by default**

Run: `WARNING_ESCALATION_MODEL=off .venv/bin/python -m pytest tests/test_degrade.py -k fabricate -v`
Expected: the smoke test is SKIPPED (others pass).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_degrade.py backend/pyproject.toml
git commit -m "Add gated VLM no-fabrication smoke test"
```

---

## Task B4: Bold-judge accuracy slice

**Files:**
- Modify: `backend/corpus/tools/eval_vlm.py`
- Test: `backend/tests/test_degrade.py`

- [ ] **Step 1: Write the failing test (accuracy helper)**

Append to `backend/tests/test_degrade.py`:

```python
from corpus.tools.eval_vlm import bold_accuracy


def test_bold_accuracy_scores_votes_against_truth():
    cases = [("yes", True), ("no", False), ("yes", False), ("unclear", True)]
    acc = bold_accuracy(cases)
    assert acc["correct"] == 2          # (yes,True) and (no,False)
    assert acc["false_yes"] == 1        # (yes,False)
    assert acc["n"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_degrade.py -k bold_accuracy -v`
Expected: FAIL (`bold_accuracy` does not exist).

- [ ] **Step 3: Add the helper and a runner slice**

In `backend/corpus/tools/eval_vlm.py`, add the pure scorer:

```python
def bold_accuracy(cases: list[tuple[str | None, bool]]) -> dict[str, int]:
    """Score (vote, is_actually_bold) pairs. correct = vote matches truth ('yes'==bold,
    'no'==not bold); false_yes = vote 'yes' on a non-bold prefix (the dangerous error)."""
    correct = false_yes = 0
    for vote, truth in cases:
        if (vote == "yes" and truth) or (vote == "no" and not truth):
            correct += 1
        if vote == "yes" and not truth:
            false_yes += 1
    return {"n": len(cases), "correct": correct, "false_yes": false_yes}
```

And add a runner helper that builds bold/non-bold prefix crops (cv2-drawn, like the detector tests) and votes on them with the real adjudicator (gated by the key):

```python
import cv2
from app.escalation import judge_warning_bold


def _prefix_crop(thickness: int) -> np.ndarray:
    img = np.full((120, 600, 3), 255, dtype=np.uint8)
    cv2.putText(img, "GOVERNMENT WARNING", (15, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), thickness, cv2.LINE_AA)
    cv2.putText(img, "according to the surgeon general consumption", (15, 95),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def run_bold_slice() -> dict[str, int]:
    cases = [(judge_warning_bold(_prefix_crop(5)), True), (judge_warning_bold(_prefix_crop(1)), False)]
    return bold_accuracy(cases)
```

Then call it from `main()` after the missing-words loop:

```python
    slice_ = run_bold_slice()
    print(f"bold-judge: {slice_['correct']}/{slice_['n']} correct, false-yes={slice_['false_yes']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_degrade.py -k bold_accuracy -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/corpus/tools/eval_vlm.py backend/tests/test_degrade.py
git commit -m "Add bold-judge accuracy slice to VLM eval"
```

---

## Final verification

- [ ] Run the full default suite: `.venv/bin/python -m pytest -q` — expect all pass, VLM smoke skipped.
- [ ] Re-run the pipeline eval on the two reported labels and confirm `warning_bold` now resolves:
  `.venv/bin/python corpus/tools/eval_combined.py` (or a targeted run) — `24142001000078` and `24268001000172` should no longer be dragged to NEEDS_REVIEW by `warning_bold`.
