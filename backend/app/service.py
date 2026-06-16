# backend/app/service.py
"""Shared application processing: image validation, creation, and verification.

One path for both single submit and batch upload. `process_one` creates a pending
Application and enqueues it; the worker (or a GET fallback) calls `verify_application`,
which runs the existing pipeline FAIL-SAFE — any failure becomes verify_status='error'
plus a human review, never a crash."""
from __future__ import annotations

import logging

import cv2
import numpy as np

from app.pipeline import verify_label
from app.serialize import serialize_verification
from app.store import Application, store

log = logging.getLogger(__name__)

#: Upload guards (single source; the API imports these). A real label is far under both.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB — memory-exhaustion guard
MAX_PIXELS = 50_000_000               # 50 MP — decompression/pixel-bomb guard


class ImageError(ValueError):
    """An uploaded image is too large, unreadable, or over the pixel cap."""


def _decode(raw: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ImageError("image is not a readable JPEG/PNG")
    return img


def validate_image(raw: bytes) -> np.ndarray:
    """Raise ImageError if `raw` is too big, unreadable, or over the pixel cap.

    Returns the decoded image array so callers can reuse it without a second decode."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError(f"image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")
    img = _decode(raw)
    h, w = img.shape[:2]
    if h * w > MAX_PIXELS:
        raise ImageError(f"image resolution exceeds the {MAX_PIXELS // 1_000_000}MP limit")
    return img


def process_one(payload: dict, image_bytes: bytes, *, batch_id: str | None = None) -> Application:
    """Create a pending Application from a canonical payload and enqueue it for verification."""
    from app.worker import enqueue  # late import breaks the worker<->service cycle

    a = Application.new(
        commodity_type=payload["commodity_type"], brand_name=payload["brand_name"],
        class_type=payload["class_type"], alcohol_content=payload["alcohol_content"],
        net_contents=payload["net_contents"], source=payload.get("source", ""),
        country_of_origin=payload.get("country_of_origin", ""),
        responsible_party=payload.get("responsible_party", ""),
        image=image_bytes, batch_id=batch_id,
    )
    store.add(a)
    enqueue(a.id)
    return a


def _application_dict(a: Application) -> dict:
    """Build the pipeline's declared-fields dict from a stored Application."""
    return {"brand_name": a.brand_name, "class_type": a.class_type,
            "alcohol_content": a.alcohol_content, "net_contents": a.net_contents,
            "source": a.source, "country_of_origin": a.country_of_origin,
            "responsible_party": a.responsible_party}


def verify_application(a: Application) -> None:
    """Run (and persist) verification for one application. FAIL-SAFE: on any error,
    records verify_status='error' so the item degrades to human review, never a crash."""
    a.verify_status = "verifying"
    store.update(a)
    try:
        img = _decode(a.image)
        a.verification = serialize_verification(verify_label(img, a.commodity_type, _application_dict(a)))
        a.verify_status = "verified"
        a.verify_error = None
    except Exception as e:  # noqa: BLE001 — verification must never crash the worker/request
        log.exception("verification failed for %s", a.id)
        a.verify_status = "error"
        a.verify_error = str(e)
    store.update(a)
