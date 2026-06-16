import pytest

from app import service, worker
from app.store import ApplicationStore


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    s = ApplicationStore()
    monkeypatch.setattr(service, "store", s)
    monkeypatch.setattr(worker, "store", s)
    return s


@pytest.fixture(autouse=True)
def _stub_verify(monkeypatch):
    # Replace real OCR with a fast stub that marks the item verified.
    def fake(a):
        a.verify_status = "verified"
        a.verification = {"overall": "pass"}
        service.store.update(a)
    monkeypatch.setattr(worker, "verify_application", fake)


def _app(_store):
    from app.store import Application
    a = Application.new(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                        alcohol_content="40%", net_contents="750 mL", image=b"x")
    _store.add(a)
    return a


def test_enqueue_is_noop_when_dormant(_store):
    a = _app(_store)
    worker.enqueue(a.id)  # not started -> nothing happens
    assert _store.get(a.id).verify_status == "pending"


def test_started_worker_processes(_store):
    a = _app(_store)
    worker.start()
    try:
        worker.enqueue(a.id)
        worker.shutdown(wait=True)
    finally:
        worker._executor = None
    assert _store.get(a.id).verify_status == "verified"


def test_start_reenqueues_stranded(_store):
    a = _app(_store)  # status pending
    worker.start()    # should re-enqueue the pending item
    try:
        worker.shutdown(wait=True)
    finally:
        worker._executor = None
    assert _store.get(a.id).verify_status == "verified"
