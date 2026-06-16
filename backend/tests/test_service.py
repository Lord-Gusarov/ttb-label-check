# backend/tests/test_service.py
import numpy as np
import pytest

from app import service
from app.service import ImageError, process_one, validate_image, verify_application
from app.store import Application, ApplicationStore


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    s = ApplicationStore()
    monkeypatch.setattr(service, "store", s)
    return s


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch):
    # process_one calls worker.enqueue via late import; stub it so no threads start.
    import app.worker as worker
    monkeypatch.setattr(worker, "enqueue", lambda app_id: None)


def _payload(**kw):
    # process_one takes image_bytes separately — the payload carries declared fields only.
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40%", net_contents="750 mL")
    base.update(kw)
    return base


def test_validate_image_rejects_garbage():
    with pytest.raises(ImageError):
        validate_image(b"not an image")


def test_process_one_creates_pending_app(_store):
    a = process_one(_payload(), b"imgbytes", batch_id="batch1")
    assert isinstance(a, Application)
    assert a.verify_status == "pending"
    assert a.batch_id == "batch1"
    assert _store.get(a.id) is not None


def test_verify_application_success(monkeypatch, _store):
    a = process_one(_payload(), b"imgbytes")
    monkeypatch.setattr(service, "_decode", lambda raw: np.zeros((4, 4, 3), np.uint8))
    monkeypatch.setattr(service, "verify_label", lambda *a, **k: object())
    monkeypatch.setattr(service, "serialize_verification", lambda vr: {"overall": "pass"})
    verify_application(a)
    assert a.verify_status == "verified"
    assert a.verification == {"overall": "pass"}
    assert a.verify_error is None


def test_verify_application_failsafe(monkeypatch, _store):
    a = process_one(_payload(), b"imgbytes")
    def _boom(raw): raise ValueError("decode failed")
    monkeypatch.setattr(service, "_decode", _boom)
    verify_application(a)
    assert a.verify_status == "error"
    assert "decode failed" in a.verify_error
