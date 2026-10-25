"""Generic export of approved orders: a JSON document per order plus a flat CSV most ERPs can import."""

import csv
import io
import json
from pathlib import Path

SCHEMA = "order-intake/export/v1"

# One row per order line; header fields repeat so each row can be imported on its own
CSV_COLUMNS = [
    "order_id", "po_number", "customer_id", "order_date", "delivery_date", "ship_to",
    "line_no", "item_no", "quantity", "unit", "order_quantity", "order_unit", "unit_price", "line_total",
    "corrected_fields",
]


def export_document(record: dict, order_id: str) -> dict:
    """Shape an approval record into the export document. Values are the final ones after review."""
    corrections = record.get("corrections", [])
    lines = []
    for line in record["lines"]:
        price = line["unit_price"]
        lines.append({
            "line_no": line["line_no"],
            "item_no": line["item_no"],
            "quantity": line["quantity"],
            "unit": line["unit"],
            "order_quantity": line["order_quantity"],
            "order_unit": line["order_unit"],
            "unit_price": price,  # per order unit, as the customer stated it
            "line_total": None if price is None else round(line["order_quantity"] * price, 2),
            "corrected_fields": sorted({c["field"] for c in corrections if c["line_no"] == line["line_no"]}),
        })
    return {
        "schema": SCHEMA,
        "order_id": order_id,
        "source_file": record["source_file"],
        "sender": record["sender"],
        "customer_id": record["customer_id"],
        "po_number": record["po_number"],
        "order_date": record["order_date"],
        "delivery_date": record["delivery_date"],
        "ship_to": record["ship_to"],
        "approved_at": record["approved_at"],
        "confirmed_warnings": record.get("confirmed_warnings", []),
        "lines": lines,
        "corrections": corrections,
    }


def to_json(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False)


def to_csv(document: dict, delimiter: str = ",") -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, delimiter=delimiter, lineterminator="\n")
    writer.writeheader()
    header = {name: document[name] for name in CSV_COLUMNS[:6]}
    for line in document["lines"]:
        row = header | {k: v for k, v in line.items() if k != "corrected_fields"}
        row["corrected_fields"] = "|".join(line["corrected_fields"])
        writer.writerow({k: "" if v is None else v for k, v in row.items()})
    return buffer.getvalue()


def export_approved(approved_dir: Path, out_dir: Path, delimiter: str = ",") -> list[str]:
    """Write <order>.json and <order>.csv for every approved order. Re-running overwrites with the same content."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exported = []
    for path in sorted(approved_dir.glob("*.json")):
        document = export_document(json.loads(path.read_text(encoding="utf-8")), path.stem)
        (out_dir / f"{path.stem}.json").write_text(to_json(document), encoding="utf-8")
        (out_dir / f"{path.stem}.csv").write_text(to_csv(document, delimiter), encoding="utf-8")
        exported.append(path.stem)
    return exported
