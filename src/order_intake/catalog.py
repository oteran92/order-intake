"""Master data the validator checks orders against, loaded from CSV exports of the ERP."""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


def normalize_ref(value: str) -> str:
    """Compare references ignoring case, spaces and separators: 'kab-3x1.5' == 'KAB 3X15'."""
    return re.sub(r"[\s\-_./]", "", value.upper())


def normalize_unit(value: str) -> str:
    return value.strip().lower().rstrip(".")


@dataclass(frozen=True)
class Item:
    item_no: str
    description: str
    base_unit: str
    ean: str
    active: bool


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    email_domain: str
    required_fields: tuple[str, ...]


@dataclass
class Catalog:
    items: dict[str, Item] = field(default_factory=dict)  # by normalized item_no
    items_by_ean: dict[str, Item] = field(default_factory=dict)
    customers_by_domain: dict[str, Customer] = field(default_factory=dict)
    cross_refs: dict[tuple[str, str], str] = field(default_factory=dict)  # (customer, normalized ref) -> item_no
    unit_aliases: dict[str, str] = field(default_factory=dict)
    conversions: dict[tuple[str, str], float] = field(default_factory=dict)  # (item_no, unit) -> factor

    @classmethod
    def from_dir(cls, path: Path) -> "Catalog":
        catalog = cls()
        for row in _rows(path / "items.csv"):
            item = Item(row["item_no"], row["description"], row["base_unit"], row["ean"], row["active"] == "true")
            catalog.items[normalize_ref(item.item_no)] = item
            if item.ean:
                catalog.items_by_ean[item.ean] = item
        for row in _rows(path / "customers.csv"):
            customer = Customer(
                row["customer_id"], row["name"], row["email_domain"].lower(),
                tuple(f for f in row["required_fields"].split("|") if f),
            )
            catalog.customers_by_domain[customer.email_domain] = customer
        for row in _rows(path / "cross_refs.csv"):
            catalog.cross_refs[(row["customer_id"], normalize_ref(row["customer_ref"]))] = row["item_no"]
        for row in _rows(path / "units.csv"):
            catalog.unit_aliases[normalize_unit(row["alias"])] = row["unit"]
        for row in _rows(path / "conversions.csv"):
            catalog.conversions[(row["item_no"], row["from_unit"])] = float(row["factor_to_base"])
        return catalog

    def customer_for(self, sender: str) -> Customer | None:
        return self.customers_by_domain.get(sender.rsplit("@", 1)[-1].lower())

    def item(self, item_no: str) -> Item:
        return self.items[normalize_ref(item_no)]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
