"""Application submit/list/review/decide endpoints."""
from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.pipeline import verify_label
from app.rules import RULESETS
from app.serialize import serialize_verification
from app.store import Application, store

router = APIRouter(prefix="/api/applications", tags=["applications"])

_DECISIONS = {"approved", "rejected", "needs_correction"}


class Decision(BaseModel):
    decision: str
    note: str | None = None


def _summary(a: Application) -> dict:
    # `overall` lets the queue triage clear vs needs-attention without fetching each detail.
    # It's whatever the cached verification found (None until the app has been verified).
    overall = a.verification.get("overall") if a.verification else None
    return {"id": a.id, "brand_name": a.brand_name, "commodity_type": a.commodity_type,
            "status": a.status, "created_at": a.created_at, "overall": overall}


def _detail(a: Application) -> dict:
    return {**_summary(a), "class_type": a.class_type,
            "alcohol_content": a.alcohol_content, "net_contents": a.net_contents,
            "decision_note": a.decision_note, "verification": a.verification}


def _decode_or_400(raw: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "image is not a readable JPEG/PNG")
    return img


@router.post("/preview")
async def preview(
    commodity_type: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    """Verify a label WITHOUT persisting it — the submit-time self-check.

    The applicant sees this feedback and decides whether to submit as-is or adjust;
    nothing reaches the agent review queue until they confirm via POST /api/applications.
    """
    if commodity_type not in RULESETS:
        raise HTTPException(400, f"unsupported commodity '{commodity_type}'")
    img = _decode_or_400(await image.read())
    application = {"brand_name": brand_name, "class_type": class_type,
                   "alcohol_content": alcohol_content, "net_contents": net_contents}
    return serialize_verification(verify_label(img, commodity_type, application))


@router.post("", status_code=201)
async def create(
    commodity_type: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    if commodity_type not in RULESETS:
        raise HTTPException(400, f"unsupported commodity '{commodity_type}'")
    raw = await image.read()
    _decode_or_400(raw)
    a = Application.new(commodity_type=commodity_type, brand_name=brand_name,
                        class_type=class_type, alcohol_content=alcohol_content,
                        net_contents=net_contents, image=raw)
    store.add(a)
    return {"id": a.id, "status": a.status}


@router.get("")
def list_applications() -> list[dict]:
    return [_summary(a) for a in store.list()]


def _ensure_verification(a: Application, *, force: bool = False) -> None:
    """Run (and cache) verification for an application; `force` re-runs even if cached."""
    if not a.image or (a.verification is not None and not force):
        return
    img = cv2.imdecode(np.frombuffer(a.image, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "stored image could not be decoded")
    application = {"brand_name": a.brand_name, "class_type": a.class_type,
                   "alcohol_content": a.alcohol_content, "net_contents": a.net_contents}
    a.verification = serialize_verification(verify_label(img, a.commodity_type, application))
    store.update(a)


@router.get("/{app_id}")
def get_application(app_id: str) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    _ensure_verification(a)
    return _detail(a)


@router.post("/{app_id}/reverify")
def reverify(app_id: str) -> dict:
    """Re-run verification on demand (a dev/QA aid; the UI exposes it only in dev builds)."""
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    _ensure_verification(a, force=True)
    return _detail(a)


@router.get("/{app_id}/image")
def get_image(app_id: str) -> Response:
    a = store.get(app_id)
    if a is None or not a.image:
        raise HTTPException(404, "image not found")
    media = "image/png" if a.image[:8].startswith(b"\x89PNG") else \
        "image/jpeg" if a.image[:2] == b"\xff\xd8" else "application/octet-stream"
    return Response(content=a.image, media_type=media)


@router.post("/{app_id}/decision")
def decide(app_id: str, body: Decision) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    if body.decision not in _DECISIONS:
        raise HTTPException(422, f"decision must be one of {sorted(_DECISIONS)}")
    a.status = body.decision
    a.decision_note = body.note
    store.update(a)
    return _detail(a)
