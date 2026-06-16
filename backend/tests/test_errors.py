from fastapi.testclient import TestClient

from app.main import app


def test_unhandled_error_returns_clean_json(monkeypatch):
    from app import store as store_mod

    def boom(_id):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(store_mod.store, "get", boom)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/applications/anything")
    assert r.status_code == 500
    assert r.json()["detail"] == "internal error"
    assert r.json()["path"] == "/api/applications/anything"
