"""Query logic behind the MCP tools.

Kept separate from the MCP wiring so it can be unit-tested / driven directly by
the smoke test without a transport. Every function returns typed Pydantic models
carrying SourceRefs.
"""
from __future__ import annotations

import re
import sqlite3

from ..models import (
    ContractHit, DocumentOut, InventoryReportSummary, LineDiff, OrderDocRef,
    OrderDossier, Reconciliation, SearchHit, SearchResults, SourceRef,
)
from ..pipeline import embed

_RRF_K = 60


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fts_query(text: str) -> str:
    toks = re.findall(r"[A-Za-z0-9]+", text)
    return " OR ".join(f'"{t}"' for t in toks)


def _source(con, doc_id: str, page: int | None = None) -> SourceRef:
    row = con.execute(
        "SELECT category, source_path FROM documents WHERE doc_id=?", (doc_id,)
    ).fetchone()
    if not row:
        return SourceRef(doc_id=doc_id, category="unknown", source_path="", page=page)
    return SourceRef(doc_id=doc_id, category=row["category"], source_path=row["source_path"], page=page)


def _items(con, table: str, key: str, value) -> list[dict]:
    rows = con.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("id", None)
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
def search(con, query: str, doc_type: str | None = None, limit: int = 5) -> SearchResults:
    match = _fts_query(query)
    if not match:
        return SearchResults(query=query, count=0, results=[])
    sql = ("SELECT doc_id, category, order_id, "
           "snippet(doc_fts, 0, '[', ']', '…', 12) AS sn "
           "FROM doc_fts WHERE doc_fts MATCH ?")
    params: list = [match]
    if doc_type:
        sql += " AND category = ?"
        params.append(doc_type)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    hits = []
    for r in con.execute(sql, params).fetchall():
        hits.append(SearchHit(
            doc_id=r["doc_id"], category=r["category"], order_id=r["order_id"],
            snippet=r["sn"], source=_source(con, r["doc_id"]),
        ))
    return SearchResults(query=query, count=len(hits), results=hits)


def get_document(con, doc_id: str) -> DocumentOut | None:
    doc = con.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not doc:
        return None
    cat = doc["category"]
    fields: dict = {}
    line_items: list[dict] = []
    if cat == "invoice":
        row = con.execute("SELECT * FROM invoices WHERE doc_id=?", (doc_id,)).fetchone()
        fields = {k: row[k] for k in row.keys() if k != "doc_id"} if row else {}
        line_items = _items(con, "invoice_items", "order_id", fields.get("order_id"))
    elif cat == "purchase_order":
        row = con.execute("SELECT * FROM purchase_orders WHERE doc_id=?", (doc_id,)).fetchone()
        fields = {k: row[k] for k in row.keys() if k != "doc_id"} if row else {}
        line_items = _items(con, "po_items", "order_id", fields.get("order_id"))
    elif cat == "shipping_order":
        row = con.execute("SELECT * FROM shipping_orders WHERE doc_id=?", (doc_id,)).fetchone()
        fields = {k: row[k] for k in row.keys() if k != "doc_id"} if row else {}
        line_items = _items(con, "shipping_items", "order_id", fields.get("order_id"))
    elif cat == "inventory_report":
        row = con.execute("SELECT * FROM inventory_reports WHERE doc_id=?", (doc_id,)).fetchone()
        fields = {k: row[k] for k in row.keys() if k != "doc_id"} if row else {}
        line_items = _items(con, "inventory_lines", "doc_id", doc_id)
    elif cat == "image_invoice":
        row = con.execute("SELECT * FROM image_invoices WHERE doc_id=?", (doc_id,)).fetchone()
        fields = {k: row[k] for k in row.keys() if k != "doc_id"} if row else {}
        line_items = _items(con, "image_invoice_items", "doc_id", doc_id)
    elif cat == "contract":
        n = con.execute("SELECT COUNT(*) c FROM contract_chunks WHERE doc_id=?", (doc_id,)).fetchone()["c"]
        idx = con.execute("SELECT COUNT(*) c FROM contract_chunks WHERE doc_id=? AND indexed=1", (doc_id,)).fetchone()["c"]
        fields = {"note": "Template contract — use search_contract for clause-level retrieval.",
                  "total_chunks": n, "indexed_chunks": idx, "excluded_template_blocks": n - idx}
    return DocumentOut(doc_id=doc_id, category=cat, fields=fields,
                       line_items=line_items, source=_source(con, doc_id))


def get_order_dossier(con, order_id: int) -> OrderDossier:
    def ref(table, summary_cols) -> OrderDocRef:
        row = con.execute(f"SELECT * FROM {table} WHERE order_id=?", (order_id,)).fetchone()
        if not row:
            return OrderDocRef(present=False)
        return OrderDocRef(present=True, doc_id=row["doc_id"],
                           source=_source(con, row["doc_id"]),
                           summary={c: row[c] for c in summary_cols if c in row.keys()})

    inv = ref("invoices", ["customer_id", "contact_name", "order_date", "total_price"])
    po = ref("purchase_orders", ["order_date", "customer_name"])
    ship = ref("shipping_orders", ["ship_name", "ship_country", "order_date", "shipped_date"])
    missing = [n for n, r in [("purchase order", po), ("invoice", inv), ("shipping order", ship)] if not r.present]
    note = ("All three documents present." if not missing
            else "Missing: " + ", ".join(missing) + ".")
    return OrderDossier(order_id=order_id, invoice=inv, purchase_order=po, shipping_order=ship, note=note)


def _all_order_ids(con) -> list[int]:
    rows = con.execute(
        "SELECT order_id FROM invoices UNION SELECT order_id FROM purchase_orders "
        "UNION SELECT order_id FROM shipping_orders ORDER BY order_id"
    ).fetchall()
    return [r["order_id"] for r in rows if r["order_id"] is not None]


def reconcile(con, order_id: int | None = None) -> list[Reconciliation]:
    ids = [order_id] if order_id is not None else _all_order_ids(con)
    out: list[Reconciliation] = []
    for oid in ids:
        inv = con.execute("SELECT doc_id FROM invoices WHERE order_id=?", (oid,)).fetchone()
        po = con.execute("SELECT doc_id FROM purchase_orders WHERE order_id=?", (oid,)).fetchone()
        ship = con.execute("SELECT doc_id FROM shipping_orders WHERE order_id=?", (oid,)).fetchone()
        has_inv, has_po, has_ship = bool(inv), bool(po), bool(ship)

        if not (has_inv or has_po or has_ship):
            out.append(Reconciliation(
                order_id=oid, has_invoice=False, has_purchase_order=False, has_shipping_order=False,
                status="missing_document", findings=[f"Order {oid} not found in any document."],
            ))
            continue

        sources, findings = [], []
        for present, row, label in [(has_inv, inv, "invoice"), (has_po, po, "purchase order"),
                                    (has_ship, ship, "shipping order")]:
            if present:
                sources.append(_source(con, row["doc_id"]))
            else:
                findings.append(f"No {label} found for order {oid}.")

        # line-level comparison across whatever documents exist
        inv_items = {i["product_name"]: i for i in _items(con, "invoice_items", "order_id", oid)}
        po_items = {i["product_name"]: i for i in _items(con, "po_items", "order_id", oid)}
        ship_items = {i["product_name"]: i for i in _items(con, "shipping_items", "order_id", oid)}
        diffs: list[LineDiff] = []
        for prod in set(inv_items) | set(po_items) | set(ship_items):
            qtys = {src: d[prod]["quantity"] for src, d in
                    [("invoice", inv_items), ("PO", po_items), ("shipping", ship_items)] if prod in d}
            prices = {src: d[prod]["unit_price"] for src, d in
                      [("invoice", inv_items), ("PO", po_items), ("shipping", ship_items)] if prod in d}
            if len({round(v, 2) for v in qtys.values()}) > 1:
                diffs.append(LineDiff(product=prod, issue=f"quantity differs across {dict(qtys)}"))
            if len({round(v, 2) for v in prices.values() if v is not None}) > 1:
                diffs.append(LineDiff(product=prod, issue=f"unit price differs across {dict(prices)}"))

        if not (has_inv and has_po and has_ship):
            status = "missing_document"
        elif diffs:
            status = "quantity_or_price_mismatch"
        else:
            status = "complete"
            findings.append("Invoice, purchase order and shipping order all present and line items agree.")
        out.append(Reconciliation(
            order_id=oid, has_invoice=has_inv, has_purchase_order=has_po, has_shipping_order=has_ship,
            status=status, findings=findings, line_diffs=diffs, sources=sources,
        ))
    return out


def search_contract(con, query: str, k: int = 5) -> list[ContractHit]:
    pool = max(k * 4, 20)
    vec_ranks: dict[int, int] = {}
    qvec = embed.embed_texts([query])
    if qvec:
        qv = qvec[0]
        if getattr(con, "vec_enabled", False):
            import sqlite_vec
            rows = con.execute(
                "SELECT chunk_id FROM contract_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (sqlite_vec.serialize_float32(qv), pool),
            ).fetchall()
            for i, r in enumerate(rows):
                vec_ranks[r["chunk_id"]] = i
        else:
            import numpy as np
            qn = np.asarray(qv, dtype=np.float32)
            qnorm = np.linalg.norm(qn) + 1e-9
            sims = []
            for r in con.execute("SELECT chunk_id, embedding FROM contract_vec_fallback").fetchall():
                v = np.frombuffer(r["embedding"], dtype=np.float32)
                sims.append((r["chunk_id"], float(np.dot(qn, v) / (qnorm * (np.linalg.norm(v) + 1e-9)))))
            sims.sort(key=lambda x: -x[1])
            for i, (cid, _) in enumerate(sims[:pool]):
                vec_ranks[cid] = i

    bm_ranks: dict[int, int] = {}
    match = _fts_query(query)
    if match:
        try:
            rows = con.execute(
                "SELECT rowid FROM contract_fts WHERE contract_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, pool),
            ).fetchall()
            for i, r in enumerate(rows):
                bm_ranks[r["rowid"]] = i
        except sqlite3.OperationalError:
            pass

    # Reciprocal Rank Fusion
    scored = []
    for cid in set(vec_ranks) | set(bm_ranks):
        s = 0.0
        if cid in vec_ranks:
            s += 1.0 / (_RRF_K + vec_ranks[cid])
        if cid in bm_ranks:
            s += 1.0 / (_RRF_K + bm_ranks[cid])
        scored.append((cid, s))
    scored.sort(key=lambda x: -x[1])

    hits: list[ContractHit] = []
    for cid, score in scored[:k]:
        row = con.execute(
            "SELECT doc_id, section, page, text, highlight FROM contract_chunks WHERE chunk_id=?", (cid,)
        ).fetchone()
        if not row:
            continue
        hl = row["highlight"] if row["highlight"] in ("none", "placeholder", "option") else "none"
        hits.append(ContractHit(
            chunk_id=cid, section=row["section"], snippet=row["text"][:300].strip(),
            highlight=hl, score=round(score, 4), source=_source(con, row["doc_id"], row["page"]),
        ))
    return hits


def list_inventory_reports(con) -> list[InventoryReportSummary]:
    rows = con.execute(
        "SELECT r.doc_id, r.period, r.category, r.category_id, "
        "(SELECT COUNT(*) FROM inventory_lines l WHERE l.doc_id=r.doc_id) AS pc "
        "FROM inventory_reports r ORDER BY r.period"
    ).fetchall()
    return [InventoryReportSummary(
        doc_id=r["doc_id"], period=r["period"], category=r["category"],
        category_id=r["category_id"], product_count=r["pc"], source=_source(con, r["doc_id"]),
    ) for r in rows]
