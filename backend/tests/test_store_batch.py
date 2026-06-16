from app.store import Application, ApplicationStore, Batch, SQLiteApplicationStore


def _app(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40%", net_contents="750 mL", image=b"img")
    base.update(kw)
    return Application.new(**base)


def test_application_defaults_pending_no_batch():
    a = _app()
    assert a.verify_status == "pending"
    assert a.batch_id is None
    assert a.verify_error is None


def test_batch_new_has_id_and_total():
    b = Batch.new(total=3)
    assert b.id and b.total == 3 and b.created_at > 0


def _roundtrip(store):
    b = Batch.new(total=2)
    store.add_batch(b)
    store.add(_app(batch_id=b.id))
    store.add(_app(batch_id=b.id))
    store.add(_app())  # unrelated single
    assert store.get_batch(b.id).total == 2
    assert {a.batch_id for a in store.list_by_batch(b.id)} == {b.id}
    assert len(store.list_by_batch(b.id)) == 2


def test_inmemory_batch_roundtrip():
    _roundtrip(ApplicationStore())


def test_sqlite_batch_roundtrip(tmp_path):
    _roundtrip(SQLiteApplicationStore(tmp_path / "t.db"))


def test_sqlite_persists_new_fields(tmp_path):
    s = SQLiteApplicationStore(tmp_path / "t.db")
    a = _app(verify_status="error", verify_error="boom")
    s.add(a)
    got = s.get(a.id)
    assert got.verify_status == "error" and got.verify_error == "boom"
