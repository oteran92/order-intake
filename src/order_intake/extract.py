"""Read order fields from document text with an LLM, exactly as written. Matching happens later."""

import os

from openai import OpenAI
from pydantic import BaseModel

from .documents import Document
from .models import ExtractedLine, ExtractedOrder

DEFAULT_MODEL = "gpt-5.4-mini"

INSTRUCTIONS = """You read purchase orders sent to a technical distributor in Switzerland.
Orders may be in German, French, Italian or English.
Copy values exactly as written. Do not map, correct, convert or invent anything:
- customer_ref: the article code as the customer wrote it (their code, our code or an EAN).
  Use an empty string if a line has only a description.
- quantity: a number. Read Swiss and German notation (1'000 = 1000, 2,5 = 2.5).
- unit: the unit as written (Stk, Rolle, m, Karton), or null if none.
- unit_price: the price per unit as a number, same notation rules, or null if no price is given.
  If only a line total is given, leave unit_price null.
- Dates as YYYY-MM-DD, or null if not stated. Use the email date as order_date only if no other date is given.
- sender_email: an email address of the ordering company found in the document, or null.
Return null for any header field that is not in the document."""


class _Line(BaseModel):
    customer_ref: str
    description: str | None
    quantity: float
    unit: str | None
    unit_price: float | None


class _Order(BaseModel):
    """Schema sent to the model. Every field is required and nullable, as strict mode expects."""

    sender_email: str | None
    po_number: str | None
    order_date: str | None
    delivery_date: str | None
    ship_to: str | None
    lines: list[_Line]


def extract_order(document: Document, client: OpenAI | None = None) -> ExtractedOrder:
    client = client or OpenAI()  # reads OPENAI_API_KEY from the environment
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        instructions=INSTRUCTIONS,
        input=document.text,
        text_format=_Order,
        store=False,  # customer documents should not be retained by the provider
    )
    parsed = response.output_parsed
    if parsed is None:
        raise ValueError(f"{document.source_file}: the model returned no order")
    sender = document.sender or parsed.sender_email or ""
    return ExtractedOrder(
        source_file=document.source_file,
        sender=sender,
        po_number=parsed.po_number,
        order_date=parsed.order_date,
        delivery_date=parsed.delivery_date,
        ship_to=parsed.ship_to,
        lines=[ExtractedLine(line_no=n, **line.model_dump()) for n, line in enumerate(parsed.lines, start=1)],
    )
