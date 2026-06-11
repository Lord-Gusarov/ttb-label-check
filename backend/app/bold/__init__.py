"""Bold-text detection for the 'GOVERNMENT WARNING' prefix (27 CFR 16.21)."""

from app.bold.detector import BoldFinding, detect_warning_bold

__all__ = ["BoldFinding", "detect_warning_bold"]
