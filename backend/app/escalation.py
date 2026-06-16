"""Tier-2 escalation: re-read the WHOLE label with a MODEL when local OCR can't verify it.

OFF by default (opt-in) and strictly FAIL-SAFE. The pipeline is fully local and air-gapped
unless an operator explicitly opts in — escalation sends the label image off-host to an
external provider, so it is never enabled implicitly. When on and the key, network, or API is
unavailable, slow, or errors, this returns ``None`` and the pipeline keeps its deterministic
``NEEDS_REVIEW``, leaving the call to a human. A model is never *required*; it only ever
*helps*. Nothing here can stop or crash a verification.

It only ever READS — it returns transcribed field text that the deterministic checks then
judge. It never renders the verdict, and it is **blind to the declared application values**
(it only sees the image), so it cannot "helpfully" output whatever would match.

Enable with env ``WARNING_ESCALATION_MODEL`` — e.g. set it to ``"openai:gpt-5.4-mini"`` (the
recommended model, see below). Leaving it unset (or ``"off"``) keeps escalation DISABLED and
the pipeline fully local. Point it at another provider/endpoint (e.g. Azure OpenAI in a
FedRAMP boundary, or a local server) to swap the reader — the verdict logic is unchanged. The
OpenAI key is read from ``$OPENAI_API_KEY`` or ``~/.oai_key``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Default when WARNING_ESCALATION_MODEL is unset: escalation disabled (fully local/air-gapped).
#: Tier 2 is opt-in because escalation sends the label image off-host. Recommended value when
#: enabling is "openai:gpt-5.4-mini": benchmarked at 1.00 warning-recovery on the hard labels at
#: ~2s (gpt-4.1-mini ties it; 5.4-mini is marginally faster / fewer tokens; gpt-4o-mini matched
#: accuracy but ~20x the tokens).
_DEFAULT_SPEC = "off"
_DISABLED = {"", "off", "none", "disabled", "0", "false"}

#: The fields the model transcribes. It is given the IMAGE only — never the declared values.
FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents",
          "responsible_party", "country_of_origin", "government_warning")
_LABEL_PROMPT = (
    "Read this U.S. alcohol label and transcribe these fields EXACTLY as printed — do not "
    "paraphrase, infer, or correct anything. Return ONLY JSON with keys: brand_name, "
    "class_type, alcohol_content, net_contents, responsible_party, country_of_origin, "
    "government_warning. For responsible_party, transcribe the bottler/producer name & address "
    "statement (e.g. 'Bottled by ACME, City, ST'); for country_of_origin, the origin statement "
    "if any (e.g. 'Product of France'). For government_warning, transcribe the full Government "
    "Warning paragraph verbatim. Use an empty string for any field not present or not readable."
)


def _read_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key.strip()
    p = Path(os.path.expanduser("~/.oai_key"))
    return p.read_text().strip() if p.exists() else None


def _chat_json(image: np.ndarray, model: str, prompt: str) -> dict | None:
    """One declared-blind image+text chat call returning parsed JSON, or None on any failure
    (missing key, encode/network/API error, empty or unparseable response). Never raises."""
    try:
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
        if not r.choices:
            return None
        return json.loads(r.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 — fail-safe: any failure degrades to None, never crashes
        logger.warning("chat_json call failed; returning None", exc_info=True)
        return None


_BOLD_PROMPT = (
    "Look ONLY at this cropped U.S. alcohol-label warning. Is the phrase 'GOVERNMENT WARNING' "
    "printed in bold (a visibly heavier stroke) relative to the body text that follows it? "
    "Do not guess; if you cannot tell, say unclear. Return ONLY JSON: {\"bold\": \"yes\"|\"no\"|\"unclear\"}."
)


def judge_warning_bold(crop: np.ndarray) -> str | None:
    """Best-effort VLM adjudication of prefix bold -> 'yes'|'no'|'unclear', or None when
    escalation is disabled/unavailable. Never raises (fail-safe)."""
    spec = os.environ.get("WARNING_ESCALATION_MODEL", _DEFAULT_SPEC).strip()
    if spec.lower() in _DISABLED:
        return None
    try:
        provider, _, model = spec.partition(":")
        if provider != "openai":
            logger.warning("unknown escalation provider %r — skipping bold judge", provider)
            return None
        data = _chat_json(crop, model or "gpt-5.4-mini", _BOLD_PROMPT)
        if not data:
            return None
        val = str(data.get("bold", "")).strip().lower()
        return val if val in {"yes", "no", "unclear"} else None
    except Exception:  # noqa: BLE001 — must degrade, never crash
        logger.warning("bold adjudication failed; ignoring", exc_info=True)
        return None


def _openai_read_label(image: np.ndarray, model: str) -> dict[str, str] | None:
    data = _chat_json(image, model, _LABEL_PROMPT)
    return {k: str(data.get(k, "") or "") for k in FIELDS} if data else None


def escalate_label_read(image: np.ndarray) -> dict[str, str] | None:
    """Best-effort model re-read of the whole label → {field: transcribed text}, or None when
    escalation is disabled/unavailable (caller keeps its local verdict). Never raises."""
    spec = os.environ.get("WARNING_ESCALATION_MODEL", _DEFAULT_SPEC).strip()
    if spec.lower() in _DISABLED:
        return None  # disabled by default (air-gapped) unless opted in → fully local, fail-safe
    try:
        provider, _, model = spec.partition(":")
        if provider == "openai":
            return _openai_read_label(image, model or "gpt-5.4-mini")
        logger.warning("unknown escalation provider %r — skipping", provider)
    except Exception:  # noqa: BLE001 — any failure must degrade to human review, never crash
        logger.warning("label escalation failed; keeping local verdict", exc_info=True)
    return None
