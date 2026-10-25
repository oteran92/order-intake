"""Document reading runs on the real sample files. The model call is replaced by a stub."""

from pathlib import Path
from types import SimpleNamespace

from order_intake.documents import read_document
from order_intake.extract import _Line, _Order, extract_order

INBOX = Path(__file__).resolve().parent.parent / "samples" / "inbox"


def test_email_with_pdf_attachment_includes_table_text():
    document = read_document(INBOX / "002-seetal.eml")
    assert document.sender == "einkauf@seetal-elektro.example"
    assert "SE-77120" in document.text and "WAGO 221-413" in document.text


def test_email_with_excel_attachment_keeps_rows():
    document = read_document(INBOX / "003-jura.eml")
    assert "DOSE-AP-1\tAbzweigdose\t2.5\tStk" in document.text


class StubClient:
    def __init__(self, order: _Order):
        self.responses = SimpleNamespace(parse=lambda **kwargs: SimpleNamespace(output_parsed=order))


def test_header_sender_wins_and_lines_are_numbered():
    stub = _Order(sender_email="other@example.com", po_number="AB-2026-0815", order_date="2026-10-20",
                  delivery_date=None, ship_to=None,
                  lines=[_Line(customer_ref="AB-4711", description=None, quantity=500, unit="Stk", unit_price=0.12)] * 2)
    order = extract_order(read_document(INBOX / "001-alpenbau.eml"), client=StubClient(stub))
    assert order.sender == "einkauf@alpenbau.example"
    assert [l.line_no for l in order.lines] == [1, 2]
    assert str(order.order_date) == "2026-10-20"
