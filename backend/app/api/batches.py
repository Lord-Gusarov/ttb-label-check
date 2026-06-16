# backend/app/api/batches.py
"""Batch upload (manifest + images) and batch progress."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.applications import _summary
from app.batch import ManifestError, parse_manifest, row_skip_reason
from app.service import ImageError, process_one, validate_image
from app.store import Batch, store

router = APIRouter(tags=["batches"])


@router.post("/api/applications/batch", status_code=201)
async def create_batch(
    manifest: UploadFile = File(...),
    images: list[UploadFile] = File(...),
) -> dict:
    """Upload a JSON manifest plus its images. Valid rows are created and enqueued for
    background verification; invalid rows are skipped and reported (never fatal)."""
    try:
        rows = parse_manifest(await manifest.read())
    except ManifestError as e:
        raise HTTPException(400, str(e)) from e

    files: dict[str, bytes] = {}
    for im in images:
        files[im.filename or ""] = await im.read()
    image_names = set(files)

    batch = Batch.new()
    accepted = 0
    skipped: list[dict] = []
    for i, row in enumerate(rows):
        reason = row_skip_reason(row, image_names)
        if reason is None:
            try:
                validate_image(files[row["image"]])
            except ImageError as e:
                reason = str(e)
        if reason is not None:
            skipped.append({"index": i, "image": row.get("image"), "reason": reason})
            continue
        process_one(row, files[row["image"]], batch_id=batch.id)
        accepted += 1

    batch.total = accepted
    store.add_batch(batch)
    return {"batch_id": batch.id, "accepted": accepted, "skipped": skipped}


@router.get("/api/batches/{batch_id}")
def get_batch(batch_id: str) -> dict:
    b = store.get_batch(batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    items = store.list_by_batch(batch_id)
    counts = {"pending": 0, "verifying": 0, "verified": 0, "error": 0}
    for a in items:
        counts[a.verify_status] = counts.get(a.verify_status, 0) + 1
    return {"id": b.id, "total": b.total, "counts": counts,
            "items": [_summary(a) for a in items]}
