"""Tier-2 escalation: re-read the WHOLE label with a MODEL when local OCR can't verify it.

ON by default (gpt-5.4-mini) and strictly FAIL-SAFE. If the key, network, or API is
unavailable, slow, or errors, this returns ``None`` and the pipeline keeps its deterministic
``NEEDS_REVIEW``, leaving the call to a human. A model is never *required*; it only ever
*helps*. Nothing here can stop or crash a verification.

It only ever READS — it returns transcribed field text that the deterministic checks then
judge. It never renders the verdict, and it is **blind to the declared application values**
(it only sees the image), so it cannot "helpfully" output whatever would match.

Configure with env ``WARNING_ESCALATION_MODEL``. Set it to ``"off"`` to DISABLE escalation
entirely (the air-gapped deployment) so the pipeline is fully local. Point it at another
provider/endpoint (e.g. Azure OpenAI in a FedRAMP boundary, or a local server) to swap the
reader — the verdict logic is unchanged. The OpenAI key is read from ``$OPENAI_API_KEY`` or
``~/.oai_key``.
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

#: Tier 2 is ON by default. Set env WARNING_ESCALATION_MODEL="off" to disable (air-gapped),
#: or point it at another provider/model. Benchmarked: gpt-5.4-mini and gpt-4.1-mini both hit
#: 1.00 warning-recovery on the hard labels at ~2s; 5.4-mini is marginally faster / fewer
#: tokens (per-token price likely higher). gpt-4o-mini matched accuracy but ~20x the tokens.
_DEFAULT_MODEL = "openai:gpt-5.4-mini"
_DISABLED = {"", "off", "none", "disabled", "0", "false"}

#: The fields the model transcribes. It is given the IMAGE only — never the declared values.
FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents", "government_warning")
_LABEL_PROMPT = (
    "Read this U.S. alcohol label and transcribe these fields EXACTLY as printed — do not "
    "paraphrase, infer, or correct anything. Return ONLY JSON with keys: brand_name, "
    "class_type, alcohol_content, net_contents, government_warning. For government_warning, "
    "transcribe the full Government Warning paragraph verbatim. Use an empty string for any "
    "field that is not present or not readable."
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
    spec = os.environ.get("WARNING_ESCALATION_MODEL", _DEFAULT_MODEL).strip()
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
    spec = os.environ.get("WARNING_ESCALATION_MODEL", _DEFAULT_MODEL).strip()
    if spec.lower() in _DISABLED:
        return None  # explicitly disabled (e.g. air-gapped) → fully local, fail-safe
    try:
        provider, _, model = spec.partition(":")
        if provider == "openai":
            return _openai_read_label(image, model or "gpt-5.4-mini")
        logger.warning("unknown escalation provider %r — skipping", provider)
    except Exception:  # noqa: BLE001 — any failure must degrade to human review, never crash
        logger.warning("label escalation failed; keeping local verdict", exc_info=True)
    return None
