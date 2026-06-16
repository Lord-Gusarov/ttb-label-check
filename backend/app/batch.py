"""Batch manifest parsing and per-row validation.

A manifest is a JSON array of canonical application payloads, each naming its image file.
Validation is per-row: a bad row is SKIPPED with a reason, never failing the whole batch.
Only a structurally invalid manifest (not JSON / not an array / oversize) is fatal."""
from __future__ import annotations

import json

from app.rules import RULESETS

#: Required declared fields plus the image reference. responsible_party is optional and
#: country_of_origin is conditional (imports only), matching the single-submit form.
REQUIRED = ("commodity_type", "brand_name", "class_type", "alcohol_content",
            "net_contents", "image")

#: Cap items per batch — an unauthenticated endpoint guard, far above any real batch.
MAX_BATCH_ITEMS = 500


class ManifestError(ValueError):
    """The manifest itself is unusable (not JSON, not an array, or over the item cap)."""


def parse_manifest(raw: bytes) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise ManifestError("manifest must be a JSON array of applications")
    if len(data) > MAX_BATCH_ITEMS:
        raise ManifestError(f"manifest exceeds the {MAX_BATCH_ITEMS}-item limit")
    if not all(isinstance(r, dict) for r in data):
        raise ManifestError("each manifest entry must be a JSON object")
    return data


def row_skip_reason(row: dict, image_names: set[str]) -> str | None:
    """Return why this row can't be processed, or None if it's valid."""
    missing = [k for k in REQUIRED if not str(row.get(k, "")).strip()]
    if missing:
        return f"missing required field(s): {', '.join(missing)}"
    if row["commodity_type"] not in RULESETS:
        return f"unsupported commodity '{row['commodity_type']}'"
    if row["image"] not in image_names:
        return f"image '{row['image']}' not found in upload"
    return None
