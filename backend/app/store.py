"""Application store: SQLite-backed by default (survives restarts), with the original
in-memory store kept for tests. Images are stored as BLOBs (label artwork is <=1.5MB)
and the serialized verification as JSON text — one file, no server, fits the
single-container deployment."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List

@dataclass
class Application:
    id: str
    commodity_type: str
    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    image: bytes
    created_at: float
    status: str = "submitted"          # submitted | approved | rejected | needs_correction
    decision_note: str | None = None
    verification: dict | None = None   # cached serialized verification result
    source: str = ""                   # "" | domestic | imported (gates country-of-origin)
    country_of_origin: str = ""        # declared country (imports)
    responsible_party: str = ""        # declared bottler/producer name & address
    batch_id: str | None = None       # groups batch-uploaded items; None for single submits
    verify_status: str = "pending"    # pending | verifying | verified | error
    verify_error: str | None = None   # message when verify_status == "error"

    @classmethod
    def new(cls, **kw) -> "Application":
        return cls(id=uuid.uuid4().hex, created_at=time.time(), **kw)


@dataclass
class Batch:
    id: str
    created_at: float
    total: int = 0

    @classmethod
    def new(cls, *, total: int = 0) -> "Batch":
        return cls(id=uuid.uuid4().hex, created_at=time.time(), total=total)


class ApplicationStore:
    def __init__(self) -> None:
        self._items: dict[str, Application] = {}
        self._batches: dict[str, Batch] = {}

    def add(self, app: Application) -> None:
        self._items[app.id] = app

    def update(self, app: Application) -> None:
        self._items[app.id] = app  # objects are shared, so this is interface parity

    def clear(self) -> None:
        self._items.clear()
        self._batches.clear()

    def get(self, app_id: str) -> Application | None:
        return self._items.get(app_id)

    def list(self) -> list[Application]:
        return list(self._items.values())

    def add_batch(self, batch: Batch) -> None:
        self._batches[batch.id] = batch

    def get_batch(self, batch_id: str) -> Batch | None:
        return self._batches.get(batch_id)

    # List[...] not list[...]: the `list` method shadows the builtin in annotations
    def list_by_batch(self, batch_id: str) -> List[Application]:
        return [a for a in self._items.values() if a.batch_id == batch_id]


class SQLiteApplicationStore:
    """Same interface as ApplicationStore plus update(); one connection per call
    (cheap for this workload) so it is safe under FastAPI's threadpool."""

    _COLS = ("id", "commodity_type", "brand_name", "class_type", "alcohol_content",
             "net_contents", "image", "created_at", "status", "decision_note",
             "verification", "source", "country_of_origin", "responsible_party",
             "batch_id", "verify_status", "verify_error")

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS applications (
                       id TEXT PRIMARY KEY,
                       commodity_type TEXT NOT NULL,
                       brand_name TEXT NOT NULL,
                       class_type TEXT NOT NULL,
                       alcohol_content TEXT NOT NULL,
                       net_contents TEXT NOT NULL,
                       image BLOB NOT NULL,
                       created_at REAL NOT NULL,
                       status TEXT NOT NULL,
                       decision_note TEXT,
                       verification TEXT,
                       source TEXT NOT NULL DEFAULT '',
                       country_of_origin TEXT NOT NULL DEFAULT '',
                       responsible_party TEXT NOT NULL DEFAULT '',
                       batch_id TEXT,
                       verify_status TEXT NOT NULL DEFAULT 'pending',
                       verify_error TEXT
                   )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS batches (
                       id TEXT PRIMARY KEY,
                       created_at REAL NOT NULL,
                       total INTEGER NOT NULL
                   )"""
            )
            # Forward migration: add new columns to existing databases that predate
            # the batch-upload feature.  SQLite has no ADD COLUMN IF NOT EXISTS, so
            # we probe via PRAGMA and skip columns that are already present.
            existing = {row[1] for row in c.execute("PRAGMA table_info(applications)")}
            _new_cols = {
                "batch_id": "ALTER TABLE applications ADD COLUMN batch_id TEXT",
                "verify_status": "ALTER TABLE applications ADD COLUMN verify_status TEXT NOT NULL DEFAULT 'pending'",
                "verify_error": "ALTER TABLE applications ADD COLUMN verify_error TEXT",
            }
            for col, ddl in _new_cols.items():
                if col not in existing:
                    c.execute(ddl)
            # Backfill: rows that already have a verification result were verified before
            # verify_status was introduced. Stamp them 'verified' so the worker's re-enqueue
            # loop on startup doesn't re-run OCR on every legacy row.  The UPDATE is
            # idempotent — it's a no-op when no such rows exist (normal operation).
            c.execute(
                "UPDATE applications SET verify_status='verified' "
                "WHERE verification IS NOT NULL AND verify_status='pending'"
            )

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _row(self, a: Application) -> tuple:
        return (a.id, a.commodity_type, a.brand_name, a.class_type, a.alcohol_content,
                a.net_contents, a.image, a.created_at, a.status, a.decision_note,
                json.dumps(a.verification) if a.verification is not None else None,
                a.source, a.country_of_origin, a.responsible_party,
                a.batch_id, a.verify_status, a.verify_error)

    @staticmethod
    def _app(row: tuple) -> Application:
        return Application(
            id=row[0], commodity_type=row[1], brand_name=row[2], class_type=row[3],
            alcohol_content=row[4], net_contents=row[5], image=row[6], created_at=row[7],
            status=row[8], decision_note=row[9],
            verification=json.loads(row[10]) if row[10] is not None else None,
            source=row[11], country_of_origin=row[12], responsible_party=row[13],
            batch_id=row[14], verify_status=row[15], verify_error=row[16],
        )

    def add(self, app: Application) -> None:
        with self._conn() as c:
            c.execute(
                f"INSERT INTO applications ({','.join(self._COLS)}) "
                f"VALUES ({','.join('?' * len(self._COLS))})", self._row(app))

    def update(self, app: Application) -> None:
        assigns = ",".join(f"{col}=?" for col in self._COLS[1:])
        with self._conn() as c:
            c.execute(f"UPDATE applications SET {assigns} WHERE id=?",
                      self._row(app)[1:] + (app.id,))

    def get(self, app_id: str) -> Application | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        return self._app(row) if row else None

    def list(self) -> list[Application]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM applications ORDER BY created_at").fetchall()
        return [self._app(r) for r in rows]

    def clear(self) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM applications")
            c.execute("DELETE FROM batches")

    def add_batch(self, batch: Batch) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO batches (id, created_at, total) VALUES (?,?,?)",
                      (batch.id, batch.created_at, batch.total))

    def get_batch(self, batch_id: str) -> Batch | None:
        with self._conn() as c:
            row = c.execute("SELECT id, created_at, total FROM batches WHERE id=?",
                            (batch_id,)).fetchone()
        return Batch(id=row[0], created_at=row[1], total=row[2]) if row else None

    def list_by_batch(self, batch_id: str) -> List[Application]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM applications WHERE batch_id=? ORDER BY created_at",
                             (batch_id,)).fetchall()
        return [self._app(r) for r in rows]


def _default_db_path() -> str:
    # backend/data/app.db unless overridden (tests / containers set LABEL_CHECK_DB).
    return os.environ.get(
        "LABEL_CHECK_DB", str(Path(__file__).resolve().parent.parent / "data" / "app.db"))


store = SQLiteApplicationStore(_default_db_path())  # module-level singleton used by the API
