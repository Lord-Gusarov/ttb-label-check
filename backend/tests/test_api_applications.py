from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store

CLEAN = Path(__file__).resolve().parents[1] / "corpus" / "images" / "old_tom_clean.png"
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_store():
    store.clear()
    yield
    store.clear()


def _submit(**overrides):
    fields = dict(commodity_type="distilled_spirits", brand_name="OLD TOM DISTILLERY",
                  class_type="Kentucky Straight Bourbon Whiskey",
                  alcohol_content="45% Alc./Vol. (90 Proof)", net_contents="750 mL")
    fields.update(overrides)
    with open(CLEAN, "rb") as fh:
        return client.post("/api/applications", data=fields,
                           files={"image": ("label.png", fh, "image/png")})


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_submit_then_list():
    r = _submit()
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    listing = client.get("/api/applications").json()
    assert any(a["id"] == app_id and a["status"] == "submitted" for a in listing)


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_list_includes_overall_for_triage():
    # The queue triages "clear / recommend approve" vs "needs attention", so the list
    # summary carries each app's overall verdict (from its cached verification).
    app_id = _submit().json()["id"]
    client.get(f"/api/applications/{app_id}")  # triggers + caches verification
    summary = next(a for a in client.get("/api/applications").json() if a["id"] == app_id)
    assert summary["overall"] in ("pass", "warn", "needs_review")


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_detail_runs_verification_clean_label_passes():
    app_id = _submit().json()["id"]
    detail = client.get(f"/api/applications/{app_id}").json()
    assert detail["verification"]["overall"] in ("pass", "warn", "needs_review")
    fields = {f["field"]: f for f in detail["verification"]["fields"]}
    assert fields["brand_name"]["verdict"] == "pass"
    assert fields["alcohol_content"]["verdict"] == "pass"


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_preview_verifies_without_persisting():
    fields = dict(commodity_type="distilled_spirits", brand_name="OLD TOM DISTILLERY",
                  class_type="Kentucky Straight Bourbon Whiskey",
                  alcohol_content="45% Alc./Vol. (90 Proof)", net_contents="750 mL")
    before = len(client.get("/api/applications").json())
    with open(CLEAN, "rb") as fh:
        r = client.post("/api/applications/preview", data=fields,
                        files={"image": ("label.png", fh, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["overall"] in ("pass", "warn", "needs_review", "fail")
    after = len(client.get("/api/applications").json())
    assert after == before  # preview must NOT create a queue item


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_wrong_abv_flags_review():
    app_id = _submit(alcohol_content="40% Alc./Vol.").json()["id"]
    detail = client.get(f"/api/applications/{app_id}").json()
    fields = {f["field"]: f for f in detail["verification"]["fields"]}
    # Flagged for the agent (NEEDS_REVIEW), not auto-rejected — only the agent's decision rejects.
    assert fields["alcohol_content"]["verdict"] == "needs_review"


def test_decision_updates_status():
    from app.store import Application
    a = Application.new(commodity_type="distilled_spirits", brand_name="X", class_type="Y",
                        alcohol_content="40%", net_contents="750 mL", image=b"")
    store.add(a)
    r = client.post(f"/api/applications/{a.id}/decision",
                    json={"decision": "approved", "note": "looks good"})
    assert r.status_code == 200
    assert client.get(f"/api/applications/{a.id}").json()["status"] == "approved"


def test_unknown_id_404():
    assert client.get("/api/applications/nope").status_code == 404


def test_bad_decision_rejected():
    from app.store import Application
    a = Application.new(commodity_type="distilled_spirits", brand_name="X", class_type="Y",
                        alcohol_content="40%", net_contents="750 mL", image=b"")
    store.add(a)
    assert client.post(f"/api/applications/{a.id}/decision",
                       json={"decision": "banana"}).status_code == 422


def test_unsupported_commodity_rejected():
    from app.store import store as _s
    _s.clear()
    from pathlib import Path
    clean = Path(__file__).resolve().parents[1] / "corpus" / "images" / "old_tom_clean.png"
    if not clean.exists():
        import pytest
        pytest.skip("seed corpus not generated")
    with open(clean, "rb") as fh:
        r = client.post("/api/applications",
                        data=dict(commodity_type="cider", brand_name="X", class_type="Y",
                                  alcohol_content="13%", net_contents="750 mL"),
                        files={"image": ("l.png", fh, "image/png")})
    assert r.status_code == 400
    # All three supported commodities are accepted (wine/malt rulesets are wired).
    for commodity in ("wine", "malt_beverage"):
        with open(clean, "rb") as fh:
            r = client.post("/api/applications",
                            data=dict(commodity_type=commodity, brand_name="X",
                                      class_type="Y", alcohol_content="13%",
                                      net_contents="750 mL"),
                            files={"image": ("l.png", fh, "image/png")})
        assert r.status_code == 201, commodity


@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_reverify_reruns_and_keeps_status():
    app_id = _submit().json()["id"]
    client.get(f"/api/applications/{app_id}")  # initial verification cached
    client.post(f"/api/applications/{app_id}/decision", json={"decision": "approved"})
    r = client.post(f"/api/applications/{app_id}/reverify")
    assert r.status_code == 200
    assert r.json()["verification"]["overall"] in ("pass", "warn", "needs_review")
    assert r.json()["status"] == "approved"  # re-running the read doesn't undo the decision


def test_reverify_unknown_id_404():
    assert client.post("/api/applications/none/reverify").status_code == 404
