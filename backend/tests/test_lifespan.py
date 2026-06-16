from fastapi.testclient import TestClient

from app import worker
from app.main import app


def test_worker_starts_and_stops_with_lifespan():
    assert worker._executor is None
    with TestClient(app):           # enters lifespan -> start()
        assert worker._executor is not None
    assert worker._executor is None  # exits lifespan -> shutdown()
