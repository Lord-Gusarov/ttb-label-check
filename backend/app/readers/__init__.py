"""Pluggable reading layer.

Importing this package registers every adapter (each is decorated with `@register`).
Adapters whose dependencies are missing still import — they just report
`available() == False` and are skipped by the bench and the runtime.
"""

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
    tesseract_reader,
    vlm_reader,
)
from app.readers.composite import FallbackReader, build_reader  # noqa: E402

__all__ = [
    "Reader",
    "ReadResult",
    "WordBox",
    "FallbackReader",
    "build_reader",
    "get_reader",
    "registered_names",
    "available_readers",
]
