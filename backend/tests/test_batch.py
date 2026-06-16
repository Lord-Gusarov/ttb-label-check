import json

import pytest

from app.batch import MAX_BATCH_ITEMS, ManifestError, parse_manifest, row_skip_reason


def _row(**kw):
    base = dict(commodity_type="distilled_spirits", brand_name="B", class_type="C",
                alcohol_content="40%", net_contents="750 mL", image="a.png")
    base.update(kw)
    return base


def test_parse_rejects_non_json():
    with pytest.raises(ManifestError):
        parse_manifest(b"{not json")


def test_parse_rejects_non_array():
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps({"image": "a.png"}).encode())


def test_parse_rejects_oversize():
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps([_row()] * (MAX_BATCH_ITEMS + 1)).encode())


def test_parse_returns_rows():
    rows = parse_manifest(json.dumps([_row(), _row()]).encode())
    assert len(rows) == 2 and rows[0]["image"] == "a.png"


def test_skip_reason_missing_field():
    assert "required" in row_skip_reason(_row(brand_name=""), {"a.png"})


def test_skip_reason_bad_commodity():
    assert "commodity" in row_skip_reason(_row(commodity_type="mead"), {"a.png"})


def test_skip_reason_image_not_uploaded():
    assert "not found" in row_skip_reason(_row(image="missing.png"), {"a.png"})


def test_skip_reason_none_when_valid():
    assert row_skip_reason(_row(), {"a.png"}) is None
