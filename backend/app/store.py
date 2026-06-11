"""In-memory Application store (prototype; nothing sensitive persisted)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


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

    @classmethod
    def new(cls, **kw) -> "Application":
        return cls(id=uuid.uuid4().hex, created_at=time.time(), **kw)


class ApplicationStore:
    def __init__(self) -> None:
        self._items: dict[str, Application] = {}

    def add(self, app: Application) -> None:
        self._items[app.id] = app

    def get(self, app_id: str) -> Application | None:
        return self._items.get(app_id)

    def list(self) -> list[Application]:
        return list(self._items.values())


store = ApplicationStore()  # module-level singleton used by the API
