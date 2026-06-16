"""Tier-2 escalation: re-read the WHOLE label with a MODEL when local OCR can't verify it.

ON by default and strictly FAIL-SAFE — the pluggable semantic-validation layer of the hybrid
pipeline. If the key, network, or API is unavailable, slow, or errors, this returns ``None``
and the pipeline keeps its deterministic ``NEEDS_REVIEW``, leaving the call to a human. A model
is never *required*; it only ever *helps*. Nothing here can stop or crash a verification.

It only ever READS — it returns transcribed field text that the deterministic checks then
judge. It never renders the verdict, and it is **blind to the declared application values**
(it only sees the image), so it cannot "helpfully" output whatever would match.

The layer is **decoupled**: this prototype uses the OpenAI API over HTTPS for ease of
demonstration, but the client is swappable — for production it can point at an Azure OpenAI
deployment inside an agency FedRAMP boundary, or an internal inference enclave (e.g. vLLM on
government servers) with no outbound internet — without changing the verdict logic. Configure
via env ``WARNING_ESCALATION_MODEL`` (default ``openai:gpt-5.4-mini``; set ``"off"`` to
disable). The OpenAI key is read from ``$OPENAI_API_KEY`` or ``~/.oai_key``.
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

#: Default model when WARNING_ESCALATION_MODEL is unset: Tier 2 is ON by default. Set the env
#: to "off" to disable, or point it at another provider/endpoint (Azure OpenAI in a FedRAMP
#: boundary, an internal vLLM enclave, …). Benchmarked: gpt-5.4-mini hits 1.00 warning-recovery
#: on the hard labels at ~2s (gpt-4.1-mini ties it; gpt-4o-mini matched accuracy but ~20x tokens).
_DEFAULT_SPEC = "openai:gpt-5.4-mini"
_DISABLED = {"", "off", "none", "disabled", "0", "false"}

#: The fields the model transcribes. It is given the IMAGE only — never the declared values.
FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents",
          "responsible_party", "country_of_origin", "government_warning")
_LABEL_PROMPT = (
    "Read this U.S. alcohol label and transcribe these fields EXACTLY as printed — do not "
    "paraphrase, infer, or correct anything. Return ONLY JSON with keys: brand_name, "
    "class_type, alcohol_content, net_contents, responsible_party, country_of_origin, "
    "government_warning, government_warning_bold. For responsible_party, transcribe the "
    "bottler/producer name & address statement (e.g. 'Bottled by ACME, City, ST'); for "
    "country_of_origin, the origin statement if any (e.g. 'Product of France'). For "
    "government_warning, transcribe the full Government Warning paragraph verbatim. For "
    "government_warning_bold, judge whether the phrase 'GOVERNMENT WARNING' is printed in bold "
    "(a visibly heavier stroke than the body text that follows) — answer exactly 'yes', 'no', "
    "or 'unclear'. Use an empty string for any text field not present or not readable."
)
#: The model's bold verdict rides on the same label read (no separate call); not a text field.
_BOLD_KEY = "government_warning_bold"


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


def _openai_read_label(image: np.ndarray, model: str) -> dict[str, str] | None:
    data = _chat_json(image, model, _LABEL_PROMPT)
    if not data:
        return None
    out = {k: str(data.get(k, "") or "") for k in FIELDS}
    out[_BOLD_KEY] = str(data.get(_BOLD_KEY, "") or "").strip().lower()  # 'yes'|'no'|'unclear'|''
    return out


def escalate_label_read(image: np.ndarray) -> dict[str, str] | None:
    """Best-effort model re-read of the whole label → {field: transcribed text}, or None when
    escalation is disabled/unavailable (caller keeps its local verdict). Never raises."""
    spec = os.environ.get("WARNING_ESCALATION_MODEL", _DEFAULT_SPEC).strip()
    if spec.lower() in _DISABLED:
        return None  # explicitly disabled via env → local-only; fail-safe
    try:
        provider, _, model = spec.partition(":")
        if provider == "openai":
            return _openai_read_label(image, model or "gpt-5.4-mini")
        logger.warning("unknown escalation provider %r — skipping", provider)
    except Exception:  # noqa: BLE001 — any failure must degrade to human review, never crash
        logger.warning("label escalation failed; keeping local verdict", exc_info=True)
    return None
