"""Data shapes shared by extraction, validation and review."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class ExtractedLine(BaseModel):
    """One order line as read from the document, before any matching."""

    line_no: int
    customer_ref: str
    description: str | None = None
    quantity: float
    unit: str | None = None
    unit_price: float | None = None  # price per order unit as written, currency not converted


class Correction(BaseModel):
    """A field changed by a reviewer. Kept so every value can be traced back to the document or a person."""

    line_no: int | None  # None for header fields
    field: str
    old: str | None
    new: str | None
    at: datetime


class ExtractedOrder(BaseModel):
    """Extractor output. Fields stay None when the document does not contain them."""

    source_file: str
    sender: str
    po_number: str | None = None
    order_date: date | None = None
    delivery_date: date | None = None
    ship_to: str | None = None
    lines: list[ExtractedLine]
    corrections: list[Correction] = Field(default_factory=list)


class Severity(str, Enum):
    ERROR = "error"  # blocks approval until a person fixes it
    WARNING = "warning"  # a person must confirm before approval
    INFO = "info"  # recorded for the reviewer, does not block


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str
    line_no: int | None = None
    candidates: list[str] = Field(default_factory=list)


class ValidatedLine(BaseModel):
    line_no: int
    customer_ref: str
    item_no: str | None = None
    quantity: float | None = None
    unit: str | None = None


class ValidationResult(BaseModel):
    source_file: str
    customer_id: str | None
    po_number: str | None
    lines: list[ValidatedLine]
    issues: list[Issue]

    @property
    def status(self) -> str:
        blocking = any(i.severity is not Severity.INFO for i in self.issues)
        return "needs_review" if blocking else "ready"
