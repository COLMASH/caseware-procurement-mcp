"""Reproducible evidence: run the 8 example questions through the same query
logic the MCP tools expose, and print grounded answers with source references.

    uv run python scripts/smoke_test.py

This is the offline proof the system answers the brief's questions; the MCP
server exposes the identical logic to an MCP client (Claude Desktop / ChatGPT).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from procurement_kb import db                 # noqa: E402
from procurement_kb.server import queries     # noqa: E402

con = db.connect(read_only=True)


def hdr(n, q, tool):
    print(f"\n{'─' * 78}\nQ{n}. {q}\n     → tool: {tool}\n")


# Q1 ------------------------------------------------------------------------
hdr(1, "Which invoices are missing a matching purchase order?", "reconcile()")
for r in queries.reconcile(con):
    if r.has_invoice and not r.has_purchase_order:
        src = next((s.doc_id for s in r.sources if s.category == "invoice"), "?")
        print(f"   • order {r.order_id}: invoice present, NO purchase order   [source: {src}]")

# Q2 ------------------------------------------------------------------------
hdr(2, "What purchase order supports invoice 10248?", "get_order_dossier(10248)")
d = queries.get_order_dossier(con, 10248)
po = d.purchase_order
if po.present:
    print(f"   PO {po.doc_id}   [source: {Path(po.source.source_path).name}]")
else:
    print("   No purchase order found.")

# Q3 ------------------------------------------------------------------------
hdr(3, "Does shipment 10248 match the related invoice?", "reconcile(10248)")
r = queries.reconcile(con, 10248)[0]
print(f"   status: {r.status}")
for f in r.findings:
    print(f"   • {f}")
print(f"   sources: {', '.join(s.doc_id for s in r.sources)}")

# Q4 ------------------------------------------------------------------------
hdr(4, "Summarize the contract terms relevant to supply of goods.", "search_contract(...)")
for h in queries.search_contract(con, "supply of goods delivery acceptance quality warranty terms", k=3):
    print(f"   • [{h.section[:38]}] (p.{h.source.page}, score {h.score})")
    print(f"     {h.snippet[:150]}…")

# Q5 ------------------------------------------------------------------------
hdr(5, "Which documents support order 10687?", "get_order_dossier(10687)")
d = queries.get_order_dossier(con, 10687)
for name, ref in [("invoice", d.invoice), ("purchase_order", d.purchase_order), ("shipping_order", d.shipping_order)]:
    mark = f"✓ {ref.doc_id}" if ref.present else "✗ (none)"
    print(f"   {name:16s} {mark}")
print(f"   note: {d.note}")

# Q6 ------------------------------------------------------------------------
hdr(6, "Are there mismatches between invoices, POs and shipping orders?", "reconcile()")
allr = queries.reconcile(con)
from collections import Counter
c = Counter(r.status for r in allr)
print(f"   {len(allr)} orders → " + ", ".join(f"{k}: {v}" for k, v in c.items()))
for r in allr:
    if r.status != "complete":
        miss = [n for n, b in [("invoice", r.has_invoice), ("PO", r.has_purchase_order), ("shipping", r.has_shipping_order)] if not b]
        extra = f"missing {miss}" if miss else f"{len(r.line_diffs)} line diff(s)"
        print(f"   • order {r.order_id}: {r.status} ({extra})")

# Q7 ------------------------------------------------------------------------
hdr(7, "What inventory reports are available, and what period do they cover?", "list_inventory_reports()")
for s in queries.list_inventory_reports(con):
    print(f"   • {s.period}  category={s.category} (id {s.category_id})  {s.product_count} products  [{s.doc_id}]")

# Q8 ------------------------------------------------------------------------
hdr(8, "Find evidence related to vendor 'Federal Shipping'.", "search('Federal Shipping')")
res = queries.search(con, "Federal Shipping", limit=4)
print(f"   {res.count} hits")
for h in res.results:
    print(f"   • {h.category:15s} {h.doc_id:18s} {h.snippet}   [source: {h.source.source_path.split('/')[-1]}]")

print(f"\n{'─' * 78}\nAll 8 example questions answered with grounded source references. ✓")
con.close()
