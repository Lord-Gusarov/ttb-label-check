"""Application submit/list/review/decide endpoints."""
from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.pipeline import verify_label
from app.serialize import serialize_verification
from app.store import Application, store

router = APIRouter(prefix="/api/applications", tags=["applications"])

_DECISIONS = {"approved", "rejected", "needs_correction"}


class Decision(BaseModel):
    decision: str
    note: str | None = None


def _summary(a: Application) -> dict:
    return {"id": a.id, "brand_name": a.brand_name, "commodity_type": a.commodity_type,
            "status": a.status, "created_at": a.created_at}


def _detail(a: Application) -> dict:
    return {**_summary(a), "class_type": a.class_type,
            "alcohol_content": a.alcohol_content, "net_contents": a.net_contents,
            "decision_note": a.decision_note, "verification": a.verification}


@router.post("", status_code=201)
async def create(
    commodity_type: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    raw = await image.read()
    if cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) is None:
        raise HTTPException(400, "image is not a readable JPEG/PNG")
    a = Application.new(commodity_type=commodity_type, brand_name=brand_name,
                        class_type=class_type, alcohol_content=alcohol_content,
                        net_contents=net_contents, image=raw)
    store.add(a)
    return {"id": a.id, "status": a.status}


@router.get("")
def list_applications() -> list[dict]:
    return [_summary(a) for a in store.list()]


@router.get("/{app_id}")
def get_application(app_id: str) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    if a.verification is None and a.image:
        img = cv2.imdecode(np.frombuffer(a.image, np.uint8), cv2.IMREAD_COLOR)
        application = {"brand_name": a.brand_name, "class_type": a.class_type,
                       "alcohol_content": a.alcohol_content, "net_contents": a.net_contents}
        a.verification = serialize_verification(
            verify_label(img, a.commodity_type, application))
    return _detail(a)


@router.post("/{app_id}/decision")
def decide(app_id: str, body: Decision) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    if body.decision not in _DECISIONS:
        raise HTTPException(422, f"decision must be one of {sorted(_DECISIONS)}")
    a.status = body.decision
    a.decision_note = body.note
    return _detail(a)
