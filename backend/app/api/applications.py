"""Application submit/list/review/decide endpoints."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.pipeline import verify_label
from app.rules import RULESETS
from app.serialize import serialize_verification
from app.service import ImageError, MAX_PIXELS, MAX_UPLOAD_BYTES, process_one, validate_image, verify_application
from app.store import Application, store

router = APIRouter(prefix="/api/applications", tags=["applications"])

_DECISIONS = {"approved", "rejected", "needs_correction"}


def _summary(a: Application) -> dict:
    # `overall` lets the queue triage clear vs needs-attention without fetching each detail.
    # It's whatever the cached verification found (None until the app has been verified).
    overall = a.verification.get("overall") if a.verification else None
    return {"id": a.id, "brand_name": a.brand_name, "commodity_type": a.commodity_type,
            "status": a.status, "created_at": a.created_at, "overall": overall,
            "verify_status": a.verify_status, "verify_error": a.verify_error}


def _detail(a: Application) -> dict:
    return {**_summary(a), "class_type": a.class_type,
            "alcohol_content": a.alcohol_content, "net_contents": a.net_contents,
            "decision_note": a.decision_note, "verification": a.verification}


class Decision(BaseModel):
    decision: str
    note: str | None = None


@router.post("/preview")
async def preview(
    commodity_type: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    source: str = Form(default=""),
    country_of_origin: str = Form(default=""),
    responsible_party: str = Form(default=""),
    image: UploadFile = File(...),
) -> dict:
    """Verify a label WITHOUT persisting it — the submit-time self-check.

    The applicant sees this feedback and decides whether to submit as-is or adjust;
    nothing reaches the agent review queue until they confirm via POST /api/applications.
    """
    if commodity_type not in RULESETS:
        raise HTTPException(400, f"unsupported commodity '{commodity_type}'")
    raw = await image.read()
    try:
        img = validate_image(raw)
    except ImageError as e:
        raise HTTPException(413 if "limit" in str(e) else 400, str(e)) from e
    application = {"brand_name": brand_name, "class_type": class_type,
                   "alcohol_content": alcohol_content, "net_contents": net_contents,
                   "source": source, "country_of_origin": country_of_origin,
                   "responsible_party": responsible_party}
    return serialize_verification(verify_label(img, commodity_type, application))


@router.post("", status_code=201)
async def create(
    commodity_type: str = Form(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    source: str = Form(default=""),
    country_of_origin: str = Form(default=""),
    responsible_party: str = Form(default=""),
    image: UploadFile = File(...),
) -> dict:
    if commodity_type not in RULESETS:
        raise HTTPException(400, f"unsupported commodity '{commodity_type}'")
    raw = await image.read()
    try:
        validate_image(raw)
    except ImageError as e:
        raise HTTPException(413 if "limit" in str(e) else 400, str(e)) from e
    payload = {"commodity_type": commodity_type, "brand_name": brand_name,
               "class_type": class_type, "alcohol_content": alcohol_content,
               "net_contents": net_contents, "source": source,
               "country_of_origin": country_of_origin, "responsible_party": responsible_party}
    a = process_one(payload, raw)
    return {"id": a.id, "status": a.status}


@router.get("")
def list_applications() -> list[dict]:
    return [_summary(a) for a in store.list()]


@router.get("/{app_id}")
def get_application(app_id: str) -> dict:
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    # Synchronous fallback for the worker-dormant case (e.g. tests): verify items the
    # worker hasn't taken yet. Errored items are NOT retried here — use /reverify for that.
    if a.verify_status == "pending":
        verify_application(a)
    return _detail(a)


@router.post("/{app_id}/reverify")
def reverify(app_id: str) -> dict:
    """Re-run verification on demand (a dev/QA aid; the UI exposes it only in dev builds)."""
    a = store.get(app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    verify_application(a)
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
