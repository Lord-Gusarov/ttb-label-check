"""Pluggable reading layer.

Importing this package registers every adapter (each is decorated with `@register`).
Adapters whose dependencies are missing still import — they just report
`available() == False` and are skipped by the bench and the runtime.
"""

from app.config import settings
from app.readers.base import (
    Reader,
    available_readers,
    get_reader,
    registered_names,
)
from app.readers.types import ReadResult, WordBox

# Side-effect imports: register the adapters.
from app.readers import (  # noqa: E402,F401
    easyocr_reader,
    paddle_reader,
    rapidocr_reader,
)


def build_reader() -> Reader:
    """Construct the configured runtime reader (hot path; swap via `LABELCHECK_READER`)."""
    return get_reader(settings.default_reader)


__all__ = [
    "Reader",
    "ReadResult",
    "WordBox",
    "build_reader",
    "get_reader",
    "registered_names",
    "available_readers",
]
