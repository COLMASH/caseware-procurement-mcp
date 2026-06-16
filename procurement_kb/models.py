"""Pydantic schemas.

Two families:
  * extraction records  -> validated rows produced by the pipeline
  * tool I/O models     -> typed MCP tool results (become `structuredContent`)

Every tool result carries `SourceRef`s so answers trace back to a source file.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Source reference / lineage
# --------------------------------------------------------------------------- #
class SourceRef(BaseModel):
    doc_id: str = Field(description="Stable document id, e.g. 'invoice_10248'")
    category: str = Field(description="invoice | purchase_order | shipping_order | inventory_report | image_invoice | contract")
    source_path: str = Field(description="Path to the original file (for citation)")
    page: Optional[int] = Field(default=None, description="1-based page, when applicable")


# --------------------------------------------------------------------------- #
# Image-invoice extraction (the only LLM-extracted, heterogeneous schema).
# batch1 = formal EU invoice (header, IBAN, VAT). batch2 = industrial, often
# headerless. So almost every field is Optional and a `layout_family` is tagged.
# --------------------------------------------------------------------------- #
class ImageLineItem(BaseModel):
    description: str
    qty: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class ImageInvoice(BaseModel):
    layout_family: Literal["formal_eu", "industrial", "unknown"] = "unknown"
    invoice_number: Optional[str] = None
    issue_date: Optional[str] = None
    seller_name: Optional[str] = None
    seller_tax_id: Optional[str] = None
    seller_iban: Optional[str] = None
    client_name: Optional[str] = None
    client_tax_id: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    shipping: Optional[float] = None
    total: Optional[float] = None
    line_items: list[ImageLineItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# MCP tool I/O models
# --------------------------------------------------------------------------- #
class SearchHit(BaseModel):
    doc_id: str
    category: str
    order_id: Optional[int] = None
    snippet: str = Field(description="Short matching excerpt — NOT the full document")
    source: SourceRef


class SearchResults(BaseModel):
    query: str
    count: int
    results: list[SearchHit]


class DocumentOut(BaseModel):
    doc_id: str
    category: str
    fields: dict = Field(description="Structured fields extracted from the document")
    line_items: list[dict] = Field(default_factory=list)
    source: SourceRef


class OrderDocRef(BaseModel):
    present: bool
    doc_id: Optional[str] = None
    source: Optional[SourceRef] = None
    summary: dict = Field(default_factory=dict)


class OrderDossier(BaseModel):
    order_id: int
    invoice: OrderDocRef
    purchase_order: OrderDocRef
    shipping_order: OrderDocRef
    note: str = ""


class LineDiff(BaseModel):
    product: str
    issue: str = Field(description="What mismatches and between which documents")


class Reconciliation(BaseModel):
    order_id: int
    has_invoice: bool
    has_purchase_order: bool
    has_shipping_order: bool
    status: Literal["complete", "missing_document", "quantity_or_price_mismatch"]
    findings: list[str] = Field(default_factory=list)
    line_diffs: list[LineDiff] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class ContractHit(BaseModel):
    chunk_id: int
    section: str
    snippet: str
    highlight: Literal["none", "placeholder", "option"] = "none"
    score: float
    source: SourceRef


class InventoryReportSummary(BaseModel):
    doc_id: str
    period: str
    category: str
    category_id: Optional[int] = None
    product_count: int
    source: SourceRef
