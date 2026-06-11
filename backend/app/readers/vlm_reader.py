"""Local vision-language model adapter (optional fallback entrant).

Default target: Microsoft Florence-2 (tiny, strong OCR + region grounding), which can
supply word boxes for both the overlay and the bold-crop step. Runs fully locally via
transformers — no egress at inference time. It is OFF unless explicitly enabled, because
torch + model weights are heavy and a CPU read can be slow; it earns its place only as a
confidence-gated fallback for messy/photographed labels.

Enable by installing torch+transformers and setting:
    LABELCHECK_VLM_MODEL=microsoft/Florence-2-base
"""

from __future__ import annotations

import os
import re

import numpy as np

from app.readers.base import Reader, register
from app.readers.types import WordBox

_TASK = "<OCR_WITH_REGION>"
# Florence-2's region OCR leaves special/sentinel tokens (BOS/EOS and <loc_*>
# location markers) embedded in the decoded labels; strip them so word text is clean.
_SPECIAL_RE = re.compile(r"</?s>|<pad>|<loc_\d+>|<[A-Z_]+>")


@register
class VlmReader(Reader):
    name = "vlm"

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._model_id = os.getenv("LABELCHECK_VLM_MODEL", "")

    def available(self) -> bool:
        # Opt-in only: needs a configured model id AND the heavy deps present.
        if not self._model_id:
            return False
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401

            return True
        except Exception:
            return False

    def _ensure_model(self):  # pragma: no cover - requires heavy optional deps
        if self._model is None:
            from transformers import AutoModelForCausalLM, AutoProcessor

            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_id, trust_remote_code=True
            ).eval()
            self._processor = AutoProcessor.from_pretrained(
                self._model_id, trust_remote_code=True
            )
        return self._model, self._processor

    def _read(self, image: np.ndarray) -> list[WordBox]:  # pragma: no cover - heavy deps
        import cv2
        from PIL import Image

        model, processor = self._ensure_model()
        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        inputs = processor(text=_TASK, images=pil, return_tensors="pt")
        generated = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=1024,
            num_beams=3,
        )
        decoded = processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = processor.post_process_generation(
            decoded, task=_TASK, image_size=(pil.width, pil.height)
        ).get(_TASK, {})

        words: list[WordBox] = []
        quads = parsed.get("quad_boxes", [])
        labels = parsed.get("labels", [])
        for quad, label in zip(quads, labels):
            text = _SPECIAL_RE.sub("", str(label)).strip()
            if not text:
                continue
            xs = quad[0::2]
            ys = quad[1::2]
            bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            # Florence-2 doesn't emit per-region scores for this task; report a
            # neutral-high confidence so downstream mean-confidence stays meaningful.
            words.append(WordBox(text=text, confidence=1.0, bbox=bbox))
        return words
