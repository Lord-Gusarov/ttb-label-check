"""Eval the TWO production model prompts with REAL LLM calls.

Hammers the model (not the regex): how well does the Tier-2 model READ, and is it safe
(no fabrication, no false-bold, faithful to the printed warning)?

Sets:
  A — 10 hand-verified REAL COLA labels (eval/golden.jsonl)        [hard, realistic]
  B — 10 synthetic Old Tom variants (eval/data/manifest.json)      [easy, EXACT truth]

Checks:
  1. _LABEL_PROMPT per-field READ accuracy (token recall) over A and B
  2. _LABEL_PROMPT no-fabrication: omit a field from the image -> model must not invent it
  3. _BOLD_PROMPT: bold vs not-bold -> no false-yes
  4. precision: a warning with a dropped legal word -> model must NOT re-insert it

Needs a key ($OPENAI_API_KEY or ~/.oai_key). Override model via LLM_EVAL_MODEL.
Usage:  cd backend && uv run python ../eval/eval_model_prompts.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("WARNING_ESCALATION_MODEL", os.environ.get("LLM_EVAL_MODEL", "openai:gpt-5.4-mini"))

from app.escalation import escalate_label_read  # noqa: E402
from app.readers.preprocess import load_image  # noqa: E402
from app.rules.spec.government_warning import CANONICAL_WARNING  # noqa: E402

from degrade import render_warning  # noqa: E402
from eval_vlm import (  # noqa: E402
    fabricated_tokens, recall, run_bold_slice, run_label_eval, transcribe_warning,
)

HERE = Path(__file__).resolve().parent
COMBINED = HERE / "data" / "real" / "combined"
IMAGES = HERE / "data" / "images"
# 10 synthetic variants (skip the two hardest — multipanel/blurnoise).
SYNTH_SKIP = {"old_tom_rich_multipanel", "old_tom_rich_blurnoise"}


def _truth_a() -> list[tuple[str, str, dict]]:
    rows = []
    for line in (HERE / "golden.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        a = r["app"]
        truth = {k: a[k] for k in ("brand_name", "class_type", "alcohol_content",
                                   "net_contents", "responsible_party", "country_of_origin") if a.get(k)}
        truth["government_warning"] = CANONICAL_WARNING
        rows.append((r["ttbid"], str(COMBINED / f"{r['ttbid']}.png"), truth))
    return rows


def _truth_b() -> list[tuple[str, str, dict]]:
    m = json.loads((HERE / "data" / "manifest.json").read_text())
    rows = []
    for lab in m["labels"]:
        if not lab["id"].startswith("old_tom") or lab["id"] in SYNTH_SKIP:
            continue
        f = lab["fields"]
        truth = {k: f[k] for k in ("brand_name", "class_type", "alcohol_content", "net_contents")}
        truth["government_warning"] = m["canonical_warning"]
        rows.append((lab["id"], str(HERE / "data" / lab["image"]), truth))
    return rows


def field_recall(rows: list[tuple[str, str, dict]]) -> dict[str, list[float]]:
    """Per-field token recall of the model's read against truth, across the row set."""
    scores: dict[str, list[float]] = {}
    for _id, path, truth in rows:
        model = escalate_label_read(load_image(path)) or {}
        for field, value in truth.items():
            scores.setdefault(field, []).append(recall(model.get(field) or "", _toks(value)))
    return scores


def _toks(text: str) -> list[str]:
    import re
    return re.findall(r"[a-z0-9]+", text.lower())


def _report(name: str, scores: dict[str, list[float]]) -> None:
    print(f"\n-- {name}: _LABEL_PROMPT per-field read accuracy (token recall) --")
    for field in sorted(scores):
        vs = scores[field]
        print(f"   {field:20} mean recall {sum(vs) / len(vs):.2f}  (n={len(vs)})")


def main() -> None:
    a, b = _truth_a(), _truth_b()
    print(f"set A (real): {len(a)}   set B (synthetic): {len(b)}   model: {os.environ['WARNING_ESCALATION_MODEL']}")

    _report("A (real/hard)", field_recall(a))
    _report("B (synthetic/easy, EXACT truth)", field_recall(b))

    # 2. no-fabrication on the production reader (synthetic; omit one field at a time).
    print("\n-- no-fabrication (_LABEL_PROMPT): omit a field -> model must NOT invent it --")
    fabs = 0
    for omitted, report in run_label_eval():
        bad = {f: r["fabricated"] for f, r in report.items() if r.get("omitted") and r.get("fabricated")}
        fabs += len(bad)
        print(f"   omit={omitted:18} {'FABRICATED ' + str(bad) if bad else 'clean'}")
    print(f"   => fabrications: {fabs} (want 0)")

    # 3. bold prompt.
    bold = run_bold_slice()
    print(f"\n-- _BOLD_PROMPT: {bold['correct']}/{bold['n']} correct, false-yes={bold['false_yes']} (want 0) --")

    # 4. precision: a warning missing a legal word -> model must not re-insert it.
    print("\n-- precision (_WARNING_PROMPT): dropped legal word must NOT be re-inserted --")
    pre_fail = 0
    for word in ("not", "pregnancy", "health"):
        crop, removed = render_warning(omit=[word])
        out = transcribe_warning(crop)
        fab = fabricated_tokens(out, removed)
        pre_fail += bool(fab)
        print(f"   dropped {word!r:12} re-inserted={fab if fab else 'no'}")
    print(f"   => precision failures: {pre_fail} (want 0)")


if __name__ == "__main__":
    main()
