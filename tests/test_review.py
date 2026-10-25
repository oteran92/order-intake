"""Review screen against the sample orders; approvals are written to a temporary folder."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from order_intake.review import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def client_and_dir(tmp_path):
    # Edits rewrite the extracted files, so work on a copy
    orders = shutil.copytree(SAMPLES / "extracted", tmp_path / "orders")
    approved = tmp_path / "approved"
    app = create_app(orders, SAMPLES / "inbox", SAMPLES / "catalog", approved)
    return TestClient(app), approved


def test_index_lists_all_orders(client_and_dir):
    client, _ = client_and_dir
    page = client.get("/").text
    assert all(name in page for name in ("001-alpenbau.eml", "002-seetal.eml", "005-neukunde.eml"))


def test_email_with_pdf_shows_document_and_marks_errors(client_and_dir):
    client, _ = client_and_dir
    page = client.get("/orders/002-seetal").text
    assert '<iframe src="/orders/002-seetal/parts/1"' in page
    assert "REF_AMBIGUOUS" in page and "KAB-3X1.5-GR, KAB-3X1.5-SW" in page
    assert "disabled>Approve order" in page
    pdf = client.get("/orders/002-seetal/parts/1")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_excel_attachment_is_rendered_as_table(client_and_dir):
    client, _ = client_and_dir
    assert "<td>DOSE-AP-1</td>" in client.get("/orders/003-jura").text


def test_order_with_errors_cannot_be_approved(client_and_dir):
    client, approved = client_and_dir
    assert client.post("/orders/002-seetal/approve").status_code == 409
    assert not list(approved.iterdir())


def test_clean_order_is_approved_with_base_quantities(client_and_dir):
    client, approved = client_and_dir
    response = client.post("/orders/001-alpenbau/approve", follow_redirects=False)
    assert response.status_code == 303
    record = json.loads((approved / "001-alpenbau.json").read_text(encoding="utf-8"))
    assert record["lines"][2]["item_no"] == "DUE-8-NY"
    assert (record["lines"][2]["quantity"], record["lines"][2]["order_unit"]) == (300, "Karton")
    assert "approved" in client.get("/orders/001-alpenbau").text


def test_fixing_ambiguous_reference_saves_correction_and_revalidates(client_and_dir):
    client, approved = client_and_dir
    response = client.post("/orders/002-seetal/lines/1", follow_redirects=False,
                           data={"customer_ref": "KAB-3X1.5-GR", "description": "Kabel 3x1.5", "quantity": "2",
                                 "unit": "Rollen", "unit_price": "89.00"})
    assert response.headers["location"] == "/orders/002-seetal?notice=saved"
    page = client.get("/orders/002-seetal").text
    assert "REF_AMBIGUOUS" not in page and "200 MTR" in page and "Corrections (1)" in page
    saved = json.loads((approved.parent / "orders" / "002-seetal.json").read_text(encoding="utf-8"))
    assert saved["lines"][0]["customer_ref"] == "KAB-3X1.5-GR"
    assert saved["corrections"][0] | {"at": None} == {"line_no": 1, "field": "customer_ref", "old": "KAB-3x1.5",
                                                       "new": "KAB-3X1.5-GR", "at": None}


def test_header_and_line_fixes_make_order_approvable(client_and_dir):
    client, approved = client_and_dir
    client.post("/orders/003-jura/header", data={"po_number": "JH-4501", "order_date": "2026-10-21",
                                                 "delivery_date": "2026-11-10", "ship_to": ""})
    client.post("/orders/003-jura/lines/2", data={"customer_ref": "DOSE-AP-1", "description": "Abzweigdose",
                                                  "quantity": "25", "unit": "Stk", "unit_price": "4,20"})
    assert client.post("/orders/003-jura/approve", follow_redirects=False).status_code == 303
    record = json.loads((approved / "003-jura.json").read_text(encoding="utf-8"))
    assert record["delivery_date"] == "2026-11-10" and record["lines"][1]["quantity"] == 25
    assert {c["field"] for c in record["corrections"]} == {"delivery_date", "quantity"}


def test_invalid_number_is_rejected_without_saving(client_and_dir):
    client, approved = client_and_dir
    response = client.post("/orders/002-seetal/lines/2", follow_redirects=False,
                           data={"customer_ref": "KAB-5X2.5-GR", "quantity": "viele", "unit": "m"})
    assert "error=" in response.headers["location"]
    saved = json.loads((approved.parent / "orders" / "002-seetal.json").read_text(encoding="utf-8"))
    assert saved["lines"][1]["quantity"] == 150 and not saved.get("corrections")


def test_approved_order_cannot_be_edited(client_and_dir):
    client, _ = client_and_dir
    client.post("/orders/001-alpenbau/approve")
    response = client.post("/orders/001-alpenbau/lines/1", data={"customer_ref": "AB-4711", "quantity": "1"})
    assert response.status_code == 409


def test_reject_keeps_corrections_and_open_issues(client_and_dir):
    client, approved = client_and_dir
    client.post("/orders/002-seetal/lines/1", data={"customer_ref": "KAB-3X1.5-GR", "description": "Kabel 3x1.5",
                                                    "quantity": "2", "unit": "Rollen", "unit_price": "89.00"})
    response = client.post("/orders/002-seetal/reject", data={"reason": "WAGO clamp not in our range"},
                           follow_redirects=False)
    assert response.headers["location"] == "/orders/002-seetal?notice=rejected"
    record = json.loads((approved.parent / "rejected" / "002-seetal.json").read_text(encoding="utf-8"))
    assert record["reason"] == "WAGO clamp not in our range" and record["rejected_at"]
    assert [c["field"] for c in record["corrections"]] == ["customer_ref"]
    assert {i["code"] for i in record["open_issues"]} == {"UNIT_CONVERTED", "UNIT_NOT_CONVERTIBLE", "REF_UNKNOWN"}
    page = client.get("/orders/002-seetal").text
    assert "badge rejected" in page and "WAGO clamp not in our range" in page
    assert "Edit line" not in page and "Approve order" not in page and "Reject order" not in page
    assert "badge rejected" in client.get("/").text


def test_rejected_order_cannot_be_edited_or_approved(client_and_dir):
    client, approved = client_and_dir
    client.post("/orders/001-alpenbau/reject")
    assert client.post("/orders/001-alpenbau/lines/1", data={"customer_ref": "AB-4711", "quantity": "1"}).status_code == 409
    assert client.post("/orders/001-alpenbau/header", data={"po_number": "X"}).status_code == 409
    assert client.post("/orders/001-alpenbau/approve").status_code == 409
    assert not (approved / "001-alpenbau.json").exists()
    saved = json.loads((approved.parent / "orders" / "001-alpenbau.json").read_text(encoding="utf-8"))
    assert saved["lines"][0]["quantity"] == 500


def test_approved_order_cannot_be_rejected(client_and_dir):
    client, approved = client_and_dir
    client.post("/orders/001-alpenbau/approve")
    assert client.post("/orders/001-alpenbau/reject", data={"reason": "late"}).status_code == 409
    assert not (approved.parent / "rejected" / "001-alpenbau.json").exists()


def test_reject_without_reason_is_final(client_and_dir):
    client, approved = client_and_dir
    client.post("/orders/005-neukunde/reject")
    client.post("/orders/005-neukunde/reject", data={"reason": "second try"})
    record = json.loads((approved.parent / "rejected" / "005-neukunde.json").read_text(encoding="utf-8"))
    assert record["reason"] is None


def test_unknown_order_returns_404(client_and_dir):
    client, _ = client_and_dir
    assert client.get("/orders/../../etc/passwd").status_code == 404
