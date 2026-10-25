"""Extract orders from incoming files and validate them against master data."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .catalog import Catalog
from .documents import UnreadableDocument, read_document
from .export import export_approved
from .extract import extract_order
from .models import ExtractedOrder, ValidationResult
from .validate import DuplicateIndex, validate_order

SUPPORTED = {".eml", ".pdf", ".xlsx", ".xlsm", ".csv"}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="Read incoming files and write extracted order JSON")
    extract.add_argument("inbox", type=Path)
    extract.add_argument("--out", type=Path, required=True)

    validate = commands.add_parser("validate", help="Validate extracted order JSON files")
    validate.add_argument("orders", type=Path)
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--json", action="store_true", help="Print machine-readable results")

    review = commands.add_parser("review", help="Open the review screen in the browser")
    review.add_argument("orders", type=Path)
    review.add_argument("--inbox", type=Path, required=True, help="Folder with the original files")
    review.add_argument("--catalog", type=Path, required=True)
    review.add_argument("--approved", type=Path, default=Path("data/approved"), help="Where approved orders are saved")
    review.add_argument("--rejected", type=Path, default=Path("data/rejected"), help="Where rejected orders are saved")
    review.add_argument("--port", type=int, default=8000)

    export = commands.add_parser("export", help="Export approved orders as JSON and CSV")
    export.add_argument("approved", type=Path, help="Folder with approved orders (data/approved)")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--delimiter", default=",", help="CSV delimiter, e.g. ';' for Excel with Swiss settings")

    args = parser.parse_args()
    if args.command == "extract":
        run_extract(args.inbox, args.out)
    elif args.command == "review":
        run_review(args)
    elif args.command == "export":
        exported = export_approved(args.approved, args.out, args.delimiter)
        print(f"Exported {len(exported)} approved orders to {args.out}" + "".join(f"\n  {s}" for s in exported))
    else:
        report(run_validate(args.orders, args.catalog), as_json=args.json)


def run_extract(inbox: Path, out: Path) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(p for p in inbox.iterdir() if p.suffix.lower() in SUPPORTED):
        try:
            order = extract_order(read_document(path))
        except UnreadableDocument as error:
            print(f"SKIPPED {path.name}: {error}", file=sys.stderr)
            continue
        (out / f"{path.stem}.json").write_text(order.model_dump_json(indent=2), encoding="utf-8")
        print(f"{path.name}: {len(order.lines)} lines")


def run_validate(orders: Path, catalog_dir: Path) -> list[ValidationResult]:
    files = sorted(orders.glob("*.json"))
    if not files:
        sys.exit(f"No extracted orders in {orders}. Run 'order-intake extract' first.")
    catalog = Catalog.from_dir(catalog_dir)
    duplicates = DuplicateIndex()
    # File names start with a sequence number, so sorting keeps arrival order for duplicate detection
    return [
        validate_order(ExtractedOrder.model_validate_json(path.read_text(encoding="utf-8")), catalog, duplicates)
        for path in files
    ]


def run_review(args: argparse.Namespace) -> None:
    import uvicorn

    from .review import create_app

    app = create_app(args.orders, args.inbox, args.catalog, args.approved, args.rejected)
    print(f"Review screen: http://127.0.0.1:{args.port}")
    # Localhost only: the screen has no login and shows customer documents
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def report(results: list[ValidationResult], as_json: bool) -> None:
    if as_json:
        print(json.dumps([r.model_dump(mode="json") | {"status": r.status} for r in results], indent=2))
        return
    for result in results:
        print(f"{result.source_file}  PO {result.po_number}  {result.status.upper()}")
        for issue in result.issues:
            where = f"line {issue.line_no}: " if issue.line_no else ""
            print(f"  [{issue.severity.value}] {issue.code}  {where}{issue.message}")
    ready = sum(r.status == "ready" for r in results)
    print(f"\n{ready} of {len(results)} orders ready without correction")


if __name__ == "__main__":
    main()
