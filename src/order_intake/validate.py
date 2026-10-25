"""Check an extracted order against master data and flag everything a person must decide."""

from .catalog import Catalog, Customer, Item, normalize_ref, normalize_unit
from .models import ExtractedLine, ExtractedOrder, Issue, Severity, ValidatedLine, ValidationResult

DEFAULT_REQUIRED_FIELDS = ("po_number",)
MIN_PARTIAL_REF_LENGTH = 4  # shorter fragments match too many items to be useful


class DuplicateIndex:
    """Remembers orders already received, including ones still under review."""

    def __init__(self) -> None:
        self._po_numbers: dict[tuple[str, str], str] = {}
        self._contents: dict[tuple[str, frozenset], str] = {}

    def check(self, key: str, po_number: str | None, lines: list[ValidatedLine], source: str) -> list[Issue]:
        issues = []
        if po_number:
            previous = self._po_numbers.setdefault((key, normalize_ref(po_number)), source)
            if previous != source:
                issues.append(Issue(code="DUPLICATE_PO", severity=Severity.ERROR,
                                    message=f"PO {po_number} was already received in {previous}"))
        content = frozenset((l.item_no, l.quantity) for l in lines if l.item_no)
        if content:
            previous = self._contents.setdefault((key, content), source)
            if previous != source and not issues:
                issues.append(Issue(code="DUPLICATE_CONTENT", severity=Severity.WARNING,
                                    message=f"Same lines as {previous} under a different PO"))
        return issues


def validate_order(order: ExtractedOrder, catalog: Catalog, duplicates: DuplicateIndex) -> ValidationResult:
    customer = catalog.customer_for(order.sender)
    issues: list[Issue] = []
    if customer is None:
        issues.append(Issue(code="CUSTOMER_UNKNOWN", severity=Severity.ERROR,
                            message=f"No customer registered for sender {order.sender}"))

    required = customer.required_fields if customer else DEFAULT_REQUIRED_FIELDS
    for name in required:
        if getattr(order, name, None) in (None, ""):
            issues.append(Issue(code="MISSING_FIELD", severity=Severity.ERROR, message=f"{name} is required"))

    lines = []
    for line in order.lines:
        validated, line_issues = _validate_line(line, customer, catalog)
        lines.append(validated)
        issues.extend(line_issues)

    key = customer.customer_id if customer else order.sender.rsplit("@", 1)[-1].lower()
    issues.extend(duplicates.check(key, order.po_number, lines, order.source_file))
    return ValidationResult(source_file=order.source_file, customer_id=customer.customer_id if customer else None,
                            po_number=order.po_number, lines=lines, issues=issues)


def _validate_line(line: ExtractedLine, customer: Customer | None,
                   catalog: Catalog) -> tuple[ValidatedLine, list[Issue]]:
    result = ValidatedLine(line_no=line.line_no, customer_ref=line.customer_ref)
    item, issues = _match_item(line, customer, catalog)
    if item is None:
        return result, issues
    result.item_no = item.item_no
    if not item.active:
        issues.append(_line_issue(line, "ITEM_INACTIVE", Severity.ERROR, f"{item.item_no} is no longer active"))

    quantity, unit_issues = _to_base_unit(line, item, catalog)
    issues.extend(unit_issues)
    if quantity is None:
        return result, issues
    result.quantity, result.unit = quantity, item.base_unit
    if quantity <= 0:
        issues.append(_line_issue(line, "QTY_INVALID", Severity.ERROR, f"Quantity {quantity} must be positive"))
    elif item.base_unit == "PCE" and not float(quantity).is_integer():
        issues.append(_line_issue(line, "QTY_NOT_INTEGER", Severity.ERROR,
                                  f"{quantity} pieces is not a whole number"))
    return result, issues


def _match_item(line: ExtractedLine, customer: Customer | None,
                catalog: Catalog) -> tuple[Item | None, list[Issue]]:
    """Match by customer cross-reference, own item number, EAN, then unique partial number."""
    ref = normalize_ref(line.customer_ref)
    if customer and (item_no := catalog.cross_refs.get((customer.customer_id, ref))):
        return catalog.item(item_no), []
    if item := catalog.items.get(ref) or catalog.items_by_ean.get(ref):
        return item, []

    candidates = [i for key, i in catalog.items.items() if len(ref) >= MIN_PARTIAL_REF_LENGTH and key.startswith(ref)]
    if len(candidates) == 1:
        item = candidates[0]
        return item, [_line_issue(line, "REF_PARTIAL_MATCH", Severity.WARNING,
                                  f"'{line.customer_ref}' read as {item.item_no}", [item.item_no])]
    if candidates:
        return None, [_line_issue(line, "REF_AMBIGUOUS", Severity.ERROR,
                                  f"'{line.customer_ref}' matches {len(candidates)} items",
                                  [i.item_no for i in candidates])]
    return None, [_line_issue(line, "REF_UNKNOWN", Severity.ERROR, f"'{line.customer_ref}' not found")]


def _to_base_unit(line: ExtractedLine, item: Item, catalog: Catalog) -> tuple[float | None, list[Issue]]:
    if not line.unit:
        return line.quantity, [_line_issue(line, "UNIT_MISSING", Severity.WARNING,
                                           f"No unit given, assumed {item.base_unit}")]
    unit = catalog.unit_aliases.get(normalize_unit(line.unit))
    if unit is None:
        return None, [_line_issue(line, "UNIT_UNKNOWN", Severity.ERROR, f"Unit '{line.unit}' is not known")]
    if unit == item.base_unit:
        return line.quantity, []
    factor = catalog.conversions.get((item.item_no, unit))
    if factor is None:
        return None, [_line_issue(line, "UNIT_NOT_CONVERTIBLE", Severity.ERROR,
                                  f"No conversion from {unit} to {item.base_unit} for {item.item_no}")]
    quantity = line.quantity * factor
    return quantity, [_line_issue(line, "UNIT_CONVERTED", Severity.INFO,
                                  f"{line.quantity:g} {unit} = {quantity:g} {item.base_unit}")]


def _line_issue(line: ExtractedLine, code: str, severity: Severity, message: str,
                candidates: list[str] | None = None) -> Issue:
    return Issue(code=code, severity=severity, message=message, line_no=line.line_no, candidates=candidates or [])
