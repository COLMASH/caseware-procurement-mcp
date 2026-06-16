"""Deterministic parsers for the clean digital Northwind PDFs.

These are consistent templates, so a small per-type parser is more reliable,
auditable and cheaper than an LLM. pdfplumber gives clean line text; we parse
labelled fields and the product tables with anchored regex.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

# product row: "<id> <name...> <qty> <unit_price>"  (name never ends in a number)
_PRODUCT_RE = re.compile(r"^(\d+)\s+(.+?)\s+(\d+)\s+(\d+(?:\.\d+)?)$")
# inventory row: "<name...> <units_sold> <units_in_stock> <unit_price>"
_INV_RE = re.compile(r"^(.+?)\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)$")


def _lines(path: Path) -> list[str]:
    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for ln in (page.extract_text() or "").splitlines():
                if ln.strip():
                    out.append(ln.strip())
    return out


def _field(lines: list[str], label: str) -> str | None:
    """First line that starts with '<label>:' -> its value."""
    pre = f"{label}:"
    for ln in lines:
        if ln.startswith(pre):
            return ln[len(pre):].strip()
    return None


def parse_invoice(path: Path) -> dict:
    lines = _lines(path)
    items, in_products = [], False
    total = None
    for ln in lines:
        if ln.startswith("Product ID"):
            in_products = True
            continue
        if ln.startswith("TotalPrice"):
            m = re.search(r"([\d.]+)", ln)
            total = float(m.group(1)) if m else None
            in_products = False
            continue
        if in_products:
            m = _PRODUCT_RE.match(ln)
            if m:
                items.append({
                    "product_id": int(m.group(1)), "product_name": m.group(2),
                    "quantity": float(m.group(3)), "unit_price": float(m.group(4)),
                })
    oid = _field(lines, "Order ID")
    return {
        "order_id": int(oid) if oid else None,
        "customer_id": _field(lines, "Customer ID"),
        "contact_name": _field(lines, "Contact Name"),
        "order_date": _field(lines, "Order Date"),
        "city": _field(lines, "City"),
        "country": _field(lines, "Country"),
        "total_price": total,
        "items": items,
    }


def parse_purchase_order(path: Path) -> dict:
    lines = _lines(path)
    order_id = order_date = customer_name = None
    items, in_products = [], False
    for i, ln in enumerate(lines):
        if ln.startswith("Order ID") and "Order Date" in ln:
            # the header row; the next line holds the values
            if i + 1 < len(lines):
                m = re.match(r"^(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(.+)$", lines[i + 1])
                if m:
                    order_id, order_date, customer_name = int(m.group(1)), m.group(2), m.group(3)
            continue
        if ln.startswith("Product ID"):
            in_products = True
            continue
        if ln.startswith("Page"):
            in_products = False
            continue
        if in_products:
            m = _PRODUCT_RE.match(ln)
            if m:
                items.append({
                    "product_id": int(m.group(1)), "product_name": m.group(2),
                    "quantity": float(m.group(3)), "unit_price": float(m.group(4)),
                })
    return {"order_id": order_id, "order_date": order_date,
            "customer_name": customer_name, "items": items}


def parse_shipping_order(path: Path) -> dict:
    lines = _lines(path)
    items: list[dict] = []
    cur: dict = {}
    for ln in lines:
        if ln.startswith("Product:"):
            cur = {"product_name": ln[len("Product:"):].strip()}
        elif ln.startswith("Quantity:"):
            cur["quantity"] = _num(ln)
        elif ln.startswith("Unit Price:"):
            cur["unit_price"] = _num(ln)
        elif ln.startswith("Total:"):
            cur["total"] = _num(ln)
            if cur.get("product_name"):
                items.append(cur)
            cur = {}
    oid = _field(lines, "Order ID")
    return {
        "order_id": int(oid) if oid else None,
        "ship_name": _field(lines, "Ship Name"),
        "ship_city": _field(lines, "Ship City"),
        "ship_region": _field(lines, "Ship Region"),
        "ship_country": _field(lines, "Ship Country"),
        "customer_id": _field(lines, "Customer ID"),
        "customer_name": _field(lines, "Customer Name"),
        "employee_name": _field(lines, "Employee Name"),
        "shipper_name": _field(lines, "Shipper Name"),
        "order_date": _field(lines, "Order Date"),
        "shipped_date": _field(lines, "Shipped Date"),
        "items": items,
    }


def parse_inventory_report(path: Path) -> dict:
    lines = _lines(path)
    period = category = category_id = None
    rows, in_table = [], False
    for ln in lines:
        if ln.startswith("Stock Report for"):
            period = ln.replace("Stock Report for", "").strip()
        elif ln.startswith("Category"):
            category = ln.split(":", 1)[1].strip()
        elif ln.startswith("id category"):
            m = re.search(r"(\d+)", ln)
            category_id = int(m.group(1)) if m else None
        elif ln.startswith("Product") and "Units Sold" in ln:
            in_table = True
        elif in_table:
            m = _INV_RE.match(ln)
            if m:
                rows.append({
                    "product_name": m.group(1), "units_sold": float(m.group(2)),
                    "units_in_stock": float(m.group(3)), "unit_price": float(m.group(4)),
                })
    return {"period": period, "category": category, "category_id": category_id, "lines": rows}


def _num(line: str) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)", line)
    return float(m.group(1)) if m else None
