from app.store import Application, ApplicationStore


def _app(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="OLD TOM DISTILLERY",
                class_type="Kentucky Straight Bourbon Whiskey",
                alcohol_content="45% Alc./Vol.", net_contents="750 mL", image=b"\x89PNG")
    base.update(kw)
    return Application.new(**base)


def test_new_application_has_id_status_and_timestamp():
    app = _app()
    assert app.id and isinstance(app.id, str)
    assert app.status == "submitted"
    assert app.created_at > 0
    assert app.verification is None


def test_store_add_get_list_roundtrip():
    store = ApplicationStore()
    a, b = _app(), _app(brand_name="STONE'S THROW")
    store.add(a)
    store.add(b)
    assert store.get(a.id) is a
    assert {x.id for x in store.list()} == {a.id, b.id}
    assert store.get("missing") is None
