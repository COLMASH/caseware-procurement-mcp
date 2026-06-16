"""MCP server exposing the procurement knowledge base.

Run (stdio, for Claude Desktop):
    uv run python -m procurement_kb.server.mcp_server

Inspect:
    npx @modelcontextprotocol/inspector uv run python -m procurement_kb.server.mcp_server

A small, well-typed tool set. Each tool returns Pydantic models (so the SDK emits
`structuredContent`) and every result carries SourceRefs for grounded citation.
The MCP client (Claude Desktop / ChatGPT) is the agent that routes between tools.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import db
from ..models import (
    ContractHit, DocumentOut, InventoryReportSummary, OrderDossier,
    Reconciliation, SearchResults,
)
from . import queries

mcp = FastMCP("procurement-kb")


def _con():
    return db.connect(read_only=True)


@mcp.tool()
def search(query: str, doc_type: str | None = None, limit: int = 5) -> SearchResults:
    """Keyword search for evidence across ALL structured records (invoices,
    purchase orders, shipping orders, inventory reports, image invoices).

    Use for "find evidence about a vendor / order / item". Returns ranked hits
    with short snippets + source refs — call get_document for full detail.
    Optionally filter by doc_type: invoice | purchase_order | shipping_order |
    inventory_report | image_invoice | contract.
    """
    con = _con()
    try:
        return queries.search(con, query, doc_type, limit)
    finally:
        con.close()


@mcp.tool()
def get_document(doc_id: str) -> DocumentOut | None:
    """Fetch the full structured record for one document by its id
    (e.g. 'invoice_10248', 'order_10687', 'batch1-1486'), including line items
    and a source reference. Use after `search` to drill into a specific hit."""
    con = _con()
    try:
        return queries.get_document(con, doc_id)
    finally:
        con.close()


@mcp.tool()
def get_order_dossier(order_id: int) -> OrderDossier:
    """Assemble every document that supports a given order_id — invoice,
    purchase order and shipping order — with key fields and source refs.

    Use for "which documents support order 10687?" or "what purchase order
    supports this invoice?". Reports which document types are missing."""
    con = _con()
    try:
        return queries.get_order_dossier(con, order_id)
    finally:
        con.close()


@mcp.tool()
def reconcile(order_id: int | None = None) -> list[Reconciliation]:
    """Three-way match across invoice / purchase order / shipping order.

    Flags missing documents (e.g. invoices with no matching PO) and any
    quantity/price mismatches between the related records. Pass an order_id for
    one order, or omit it to reconcile ALL orders. Use for "which invoices are
    missing a matching PO?", "are there mismatches between invoices, POs and
    shipping orders?", "does this shipment match the invoice?"."""
    con = _con()
    try:
        return queries.reconcile(con, order_id)
    finally:
        con.close()


@mcp.tool()
def search_contract(query: str, k: int = 5) -> list[ContractHit]:
    """Semantic + keyword (hybrid) search over the supply-of-goods contract.

    Use for "summarize the contract terms relevant to supply of goods" or any
    clause-level question. Returns the most relevant clauses with section, page
    and source ref. Template instruction blocks are excluded from the index;
    a 'placeholder' highlight means the clause contains unfilled template fields."""
    con = _con()
    try:
        return queries.search_contract(con, query, k)
    finally:
        con.close()


@mcp.tool()
def list_inventory_reports() -> list[InventoryReportSummary]:
    """List the available inventory (stock) reports — period, product category
    and how many products each covers. Use for "what inventory reports are
    available, and what period do they cover?"."""
    con = _con()
    try:
        return queries.list_inventory_reports(con)
    finally:
        con.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
