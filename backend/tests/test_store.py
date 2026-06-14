from app.store import Application, ApplicationStore, SQLiteApplicationStore


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


# --- SQLite persistence -----------------------------------------------------------


def test_sqlite_persists_across_store_instances(tmp_path):
    db = tmp_path / "app.db"
    a = _app()
    SQLiteApplicationStore(db).add(a)

    got = SQLiteApplicationStore(db).get(a.id)  # fresh instance = "after restart"
    assert got is not None
    assert got.brand_name == "OLD TOM DISTILLERY"
    assert got.image == b"\x89PNG"
    assert got.status == "submitted"
    assert got.created_at == a.created_at


def test_sqlite_update_persists_decision_and_verification(tmp_path):
    db = tmp_path / "app.db"
    s = SQLiteApplicationStore(db)
    a = _app()
    s.add(a)

    a.status = "approved"
    a.decision_note = "looks compliant"
    a.verification = {"overall": "pass", "fields": []}
    s.update(a)

    got = SQLiteApplicationStore(db).get(a.id)
    assert got is not None
    assert got.status == "approved"
    assert got.decision_note == "looks compliant"
    assert got.verification == {"overall": "pass", "fields": []}


def test_sqlite_list_and_missing(tmp_path):
    db = tmp_path / "app.db"
    s = SQLiteApplicationStore(db)
    first, second = _app(), _app(brand_name="STONE'S THROW")
    s.add(first)
    s.add(second)
    assert {x.id for x in s.list()} == {first.id, second.id}
    assert s.get("missing") is None
