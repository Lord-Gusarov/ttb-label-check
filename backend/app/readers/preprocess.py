"""OpenCV preprocessing helpers shared by readers.

Kept deliberately small and *optional* — different engines prefer different inputs
(RapidOCR/EasyOCR have their own internal handling), so adapters opt into what helps
them rather than forcing one pipeline on everyone.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def load_image(path: str | Path) -> np.ndarray:
    """Load an image from disk as a BGR uint8 array (OpenCV convention)."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"could not read image: {path}")
    return img


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
