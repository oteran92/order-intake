"""Export runs on orders approved through the review screen, including one corrected before approval."""

import csv
import io
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from order_intake.export import CSV_COLUMNS, SCHEMA, export_approved
from order_intake.review import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def approved_orders(tmp_path):
    orders = shutil.copytree(SAMPLES / "extracted", tmp_path / "orders")
    approved = tmp_path / "approved"
    client = TestClient(create_app(orders, SAMPLES / "inbox", SAMPLES / "catalog", approved))
    client.post("/orders/001-alpenbau/approve")
    # Jura needs a delivery date and a whole quantity before it can be approved
    client.post("/orders/003-jura/header", data={"po_number": "JH-4501", "order_date": "2026-10-21",
                                                 "delivery_date": "2026-11-10", "ship_to": ""})
    client.post("/orders/003-jura/lines/2", data={"customer_ref": "DOSE-AP-1", "description": "Abzweigdose",
                                                  "quantity": "25", "unit": "Stk", "unit_price": "4.20"})
    client.post("/orders/003-jura/approve")
    client.post("/orders/005-neukunde/reject", data={"reason": "unknown customer"})
    return client, approved, tmp_path / "export"


def test_only_approved_orders_are_exported(approved_orders):
    _, approved, out = approved_orders
    assert export_approved(approved, out) == ["001-alpenbau", "003-jura"]
    assert sorted(p.name for p in out.iterdir()) == ["001-alpenbau.csv", "001-alpenbau.json",
                                                      "003-jura.csv", "003-jura.json"]


def test_json_has_header_final_lines_and_corrections(approved_orders):
    _, approved, out = approved_orders
    export_approved(approved, out)
    doc = json.loads((out / "003-jura.json").read_text(encoding="utf-8"))
    assert doc["schema"] == SCHEMA and doc["customer_id"] == "C300" and doc["po_number"] == "JH-4501"
    assert doc["delivery_date"] == "2026-11-10" and doc["approved_at"]
    dose = doc["lines"][1]
    assert (dose["item_no"], dose["quantity"], dose["unit"], dose["unit_price"], dose["line_total"]) == \
        ("DOSE-AP-1", 25, "PCE", 4.2, 105.0)
    assert dose["corrected_fields"] == ["quantity"]
    cable = doc["lines"][0]
    assert (cable["quantity"], cable["unit"], cable["order_quantity"], cable["order_unit"]) == (100, "MTR", 2, "Rolle")
    assert doc["lines"][2]["unit_price"] is None and doc["lines"][2]["line_total"] is None
    assert {(c["line_no"], c["field"], c["old"], c["new"]) for c in doc["corrections"]} == \
        {(None, "delivery_date", None, "2026-11-10"), (2, "quantity", "2.5", "25.0")}


def test_csv_is_one_row_per_line_with_header_repeated(approved_orders):
    _, approved, out = approved_orders
    export_approved(approved, out, delimiter=";")
    rows = list(csv.DictReader(io.StringIO((out / "001-alpenbau.csv").read_text(encoding="utf-8")), delimiter=";"))
    assert list(rows[0]) == CSV_COLUMNS and len(rows) == 3
    assert {r["po_number"] for r in rows} == {"AB-2026-0815"}
    assert (rows[2]["item_no"], rows[2]["quantity"], rows[2]["unit"], rows[2]["line_total"]) == \
        ("DUE-8-NY", "300.0", "PCE", "28.5")
    assert rows[0]["delivery_date"] == "" and rows[0]["corrected_fields"] == ""


def test_download_links_only_for_approved_orders(approved_orders):
    client, _, _ = approved_orders
    assert "/orders/001-alpenbau/export.csv" in client.get("/orders/001-alpenbau").text
    response = client.get("/orders/003-jura/export.json")
    assert response.status_code == 200 and response.json()["lines"][1]["quantity"] == 25
    assert client.get("/orders/003-jura/export.csv").headers["content-type"].startswith("text/csv")
    assert client.get("/orders/002-seetal/export.json").status_code == 404
    assert client.get("/orders/005-neukunde/export.csv").status_code == 404
    assert client.get("/orders/001-alpenbau/export.xml").status_code == 404
