"""Each sample order covers one real-world failure the validator must catch."""

from pathlib import Path

import pytest

from order_intake.catalog import Catalog
from order_intake.models import ExtractedOrder
from order_intake.validate import DuplicateIndex, validate_order

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="module")
def results():
    catalog = Catalog.from_dir(SAMPLES / "catalog")
    duplicates = DuplicateIndex()
    return {
        path.stem: validate_order(ExtractedOrder.model_validate_json(path.read_text(encoding="utf-8")),
                                  catalog, duplicates)
        for path in sorted((SAMPLES / "extracted").glob("*.json"))
    }


def codes(result):
    return {(issue.code, issue.line_no) for issue in result.issues}


def test_clean_order_with_cross_refs_and_box_conversion(results):
    result = results["001-alpenbau"]
    assert result.status == "ready"
    assert [l.item_no for l in result.lines] == ["SCH-M6X20-VZ", "SCH-M8X30-VZ", "DUE-8-NY"]
    assert result.lines[2].quantity == 300
    assert codes(result) == {("UNIT_CONVERTED", 3)}


def test_ambiguous_unknown_and_unconvertible_lines(results):
    result = results["002-seetal"]
    assert result.status == "needs_review"
    assert codes(result) == {("REF_AMBIGUOUS", 1), ("UNIT_NOT_CONVERTIBLE", 3), ("REF_UNKNOWN", 4)}
    ambiguous = next(i for i in result.issues if i.code == "REF_AMBIGUOUS")
    assert ambiguous.candidates == ["KAB-3X1.5-GR", "KAB-3X1.5-SW"]
    assert result.lines[1].quantity == 150


def test_missing_required_field_fractional_pieces_and_ean_match(results):
    result = results["003-jura"]
    assert codes(result) == {("MISSING_FIELD", None), ("UNIT_CONVERTED", 1), ("QTY_NOT_INTEGER", 2)}
    assert result.lines[0].quantity == 100
    assert result.lines[2].item_no == "SCH-M6X20-VZ"


def test_resent_order_is_flagged_as_duplicate(results):
    assert ("DUPLICATE_PO", None) in codes(results["004-jura-nochmals"])


def test_unknown_customer_and_inactive_item(results):
    assert codes(results["005-neukunde"]) == {("CUSTOMER_UNKNOWN", None), ("ITEM_INACTIVE", 1)}
