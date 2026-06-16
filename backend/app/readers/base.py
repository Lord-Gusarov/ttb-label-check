"""Reader interface + registry.

A `Reader` turns a label image into a normalized `ReadResult`. The whole point of
the interface is swappability: RapidOCR, EasyOCR, and PaddleOCR all implement the
same `extract()`, and the bake-off picks the hot-path engine by
measured latency + accuracy. Engines whose dependencies aren't installed simply report
`available() == False` and are skipped.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter

import numpy as np

from app.readers.types import ReadResult, WordBox


class Reader(ABC):
    """Base class for all readers. Subclasses implement `_read` and `available`."""

    #: Stable short name used in config, the registry, and bench output.
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """True if this engine's dependencies are importable/usable on this host."""

    @abstractmethod
    def _read(self, image: np.ndarray) -> list[WordBox]:
        """Engine-specific recognition. Returns words in reading order."""

    def extract(self, image: np.ndarray) -> ReadResult:
        """Run recognition and wrap it in a timed, normalized `ReadResult`.

        Timing wraps the whole engine call (including any preprocessing the adapter
        does) so the bench measures the real end-to-end read latency.
        """
        start = perf_counter()
        words = self._read(image)
        elapsed_ms = (perf_counter() - start) * 1000.0

        text = " ".join(w.text for w in words)
        confidence = float(np.mean([w.confidence for w in words])) if words else 0.0
        return ReadResult(
            text=text,
            words=words,
            confidence=confidence,
            engine=self.name,
            elapsed_ms=elapsed_ms,
        )


# --- Registry -----------------------------------------------------------------
# Lazy singletons so importing the package doesn't construct heavy engines.
_REGISTRY: dict[str, type[Reader]] = {}
_INSTANCES: dict[str, Reader] = {}


def register(reader_cls: type[Reader]) -> type[Reader]:
    """Class decorator to register a reader under its `name`."""
    _REGISTRY[reader_cls.name] = reader_cls
    return reader_cls


def get_reader(name: str) -> Reader:
    """Return a (cached) instance of the named reader."""
    if name not in _REGISTRY:
        raise KeyError(f"unknown reader '{name}'. known: {sorted(_REGISTRY)}")
    if name not in _INSTANCES:
        _INSTANCES[name] = _REGISTRY[name]()
    return _INSTANCES[name]


def registered_names() -> list[str]:
    return sorted(_REGISTRY)


def available_readers() -> list[Reader]:
    """All registered readers whose dependencies are present on this host."""
    out: list[Reader] = []
    for name in registered_names():
        reader = get_reader(name)
        if reader.available():
            out.append(reader)
    return out
