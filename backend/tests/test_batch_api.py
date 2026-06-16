# backend/tests/test_batch_api.py
import io
import json

import numpy as np
import cv2
import pytest
from fastapi.testclient import TestClient

from app import service, store as store_mod
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_store():
    store_mod.store.clear()
    yield
    store_mod.store.clear()


def _png(text: bytes = b"x") -> bytes:
    img = np.full((40, 120, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def _row(image, **kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40% Alc./Vol.", net_contents="750 mL", image=image)
    base.update(kw)
    return base


def _upload(client, rows, images):
    files = [("manifest", ("m.json", json.dumps(rows).encode(), "application/json"))]
    for name, data in images.items():
        files.append(("images", (name, data, "image/png")))
    return client.post("/api/applications/batch", files=files)


def test_batch_accepts_valid_and_skips_bad():
    client = TestClient(app)
    rows = [_row("a.png"), _row("missing.png"), _row("b.png", commodity_type="mead")]
    r = _upload(client, rows, {"a.png": _png(), "b.png": _png()})
    assert r.status_code == 201
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["skipped"]) == 2
    assert {s["index"] for s in body["skipped"]} == {1, 2}


def test_batch_progress_counts():
    client = TestClient(app)
    r = _upload(client, [_row("a.png")], {"a.png": _png()})
    batch_id = r.json()["batch_id"]
    prog = client.get(f"/api/batches/{batch_id}").json()
    assert prog["total"] == 1
    # worker dormant in tests -> item stays pending until first GET detail
    assert prog["counts"]["pending"] + prog["counts"]["verified"] == 1
    assert len(prog["items"]) == 1


def test_bad_manifest_is_400():
    client = TestClient(app)
    files = [("manifest", ("m.json", b"{not json", "application/json")),
             ("images", ("a.png", _png(), "image/png"))]
    assert client.post("/api/applications/batch", files=files).status_code == 400


def test_unknown_batch_is_404():
    assert TestClient(app).get("/api/batches/nope").status_code == 404
