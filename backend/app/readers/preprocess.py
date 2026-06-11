"""OpenCV preprocessing helpers shared by readers.

Kept deliberately small and *optional* — different engines prefer different inputs
(Tesseract likes clean grayscale; RapidOCR/EasyOCR have their own internal handling),
so adapters opt into what helps them rather than forcing one pipeline on everyone.
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


def deskew(gray: np.ndarray) -> np.ndarray:
    """Estimate and correct small skew angles using the text's minimum-area rect.

    Returns the input unchanged if no text pixels are found. Conservative: only
    corrects meaningful skew so already-straight labels are left alone.
    """
    inverted = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    # minAreaRect's angle convention varies by OpenCV version (it can return ~90 for
    # axis-aligned text). Fold into [-45, 45] so a straight label deskews to ~0°, never 90°.
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90
    if abs(angle) < 0.5:
        return gray

    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def prepare_for_tesseract(image: np.ndarray, *, do_deskew: bool = True) -> np.ndarray:
    """Grayscale (+ optional deskew) — the input Tesseract reads most reliably."""
    gray = to_grayscale(image)
    if do_deskew:
        gray = deskew(gray)
    return gray
