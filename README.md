# order-intake

Orders still arrive by email, PDF and Excel. Someone types them into the ERP, looks up the customer's article numbers and fixes quantities and units.

order-intake reads those orders, checks them against your master data and prepares them for approval. Unclear lines are flagged. Nothing reaches the ERP without a person approving it.

## Status

v0.1, early. The full path from email to export works: extraction, validation, review and export. Connectors to a specific ERP or mailbox are not part of this repository.

| Step | State |
|---|---|
| Extraction (email with PDF, Excel or CSV attachments) | working, text-based PDFs only |
| Validation against master data | working |
| Review screen (approve, reject, inline corrections) | working |
| Export (generic JSON/CSV) | working |

## What the validator catches

- Customer article numbers, mapped through a cross-reference table per customer
- Own item numbers and EAN codes
- Partial or ambiguous references (`KAB-3x1.5` matches two cable colours)
- Unknown and inactive items
- Units in the customer's words (`Rolle`, `Karton`, `Stk.`) converted to the base unit
- Missing required fields per customer (PO number, delivery date, ship-to)
- Fractional quantities for items sold by the piece
- Orders sent twice, by PO number or by identical content

## Try it

Requires Python 3.11+.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest

# Validate the pre-extracted samples (no API key needed)
.venv/bin/order-intake validate samples/extracted --catalog samples/catalog

# Full run: copy .env.example to .env and set OPENAI_API_KEY first
.venv/bin/order-intake extract samples/inbox --out data/extracted
.venv/bin/order-intake validate data/extracted --catalog samples/catalog

# Review screen at http://127.0.0.1:8000 (use samples/extracted to try it without an API key)
.venv/bin/order-intake review data/extracted --inbox samples/inbox --catalog samples/catalog
```

The review screen shows the original email, PDF or Excel next to the extracted lines and marks every exception. Header fields and lines can be corrected inline: each correction is written back to the extracted order with the old and new value, and the order is validated again.

Each order ends with one decision, and both are final:

- **Approve:** saved to `data/approved/` for export. Orders with errors cannot be approved; warnings must be confirmed.
- **Reject:** saved to `data/rejected/` with an optional reason, the corrections and the open issues, so the decision can be traced. Orders with errors can be rejected.

It listens on localhost only and has no login.

Extraction copies values exactly as written. Matching, unit conversion and every correction happen in validation, where the rules are visible and testable. Requests are sent with `store=False`. Scanned PDFs without a text layer are skipped for now.

## Export

```bash
.venv/bin/order-intake export data/approved --out data/export            # add --delimiter ";" for Excel
```

Every approved order becomes two files with the final values after review:

- `<order>.json` (schema `order-intake/export/v1`): header, lines and the full corrections log. Use it for API imports and as the audit record.
- `<order>.csv`: one row per line with the header repeated, for ERP file imports.

Lines carry the item number and quantity in the base unit, the quantity, unit and price as ordered, the line total and the fields a reviewer corrected. Approved orders can also be downloaded as JSON or CSV from the review screen.

## Master data

Export these from the ERP as CSV (see `samples/catalog`):

| File | Content |
|---|---|
| `items.csv` | item number, description, base unit, EAN, active |
| `customers.csv` | customer, email domain, required fields |
| `cross_refs.csv` | customer article number to own item number |
| `units.csv` | unit spellings to unit codes |
| `conversions.csv` | per item factor from order unit to base unit |

## Samples

All companies, people and articles in `samples/` are fictitious. `scripts/make_samples.py` regenerates the sample emails with PDF and Excel attachments. Real customer documents go in `data/`, which is ignored by git.

## Integration

Connecting to a specific ERP, mailbox and approval process is done per company. Get in touch: [prietoteran.com](https://prietoteran.com).

## License

[Apache License 2.0](LICENSE)
