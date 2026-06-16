"""Pipeline orchestrator.

    uv run python -m procurement_kb.pipeline.run [--data DIR] [--db FILE]

Walks the data folder, registers every file for lineage, routes each document to
the right extractor (deterministic parser / vision-LLM / color-aware contract),
and builds one SQLite file with relational tables + FTS5 keyword index +
contract vector index. Re-runnable and idempotent.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import fitz

from .. import config, db
from . import extract_contract, extract_image, extract_pdf, embed
from .cache import cached, sha256_file

log = logging.getLogger("procurement_kb.pipeline")


def _page_count(path: Path, file_type: str) -> int:
    if file_type != "pdf":
        return 1
    try:
        with fitz.open(path) as d:
            return d.page_count
    except Exception:
        return 1


def _register(con, doc_id, category, path: Path, file_type):
    con.execute(
        "INSERT OR REPLACE INTO documents(doc_id, category, source_path, file_type, sha256, page_count)"
        " VALUES (?,?,?,?,?,?)",
        (doc_id, category, str(path), file_type, sha256_file(path), _page_count(path, file_type)),
    )


def _fts(con, doc_id, category, order_id, content):
    con.execute(
        "INSERT INTO doc_fts(content, doc_id, category, order_id) VALUES (?,?,?,?)",
        (content, doc_id, category, order_id),
    )


def run(data_dir: Path, db_path: Path) -> None:
    con = db.connect(db_path)
    db.init_db(con)
    backend = "sqlite-vec" if getattr(con, "vec_enabled", False) else "numpy-fallback"
    log.info("Vector backend: %s", backend)
    counts: dict[str, int] = {}

    def bump(k):
        counts[k] = counts.get(k, 0) + 1

    # ---- Invoices folder: PDFs (Northwind) + JPGs (image invoices) ----------
    for path in sorted((data_dir / "invoices").glob("*")):
        if path.suffix.lower() == ".pdf":
            doc_id = path.stem
            _register(con, doc_id, "invoice", path, "pdf")
            rec = extract_pdf.parse_invoice(path)
            con.execute(
                "INSERT INTO invoices(order_id, doc_id, customer_id, contact_name, order_date, city, country, total_price)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (rec["order_id"], doc_id, rec["customer_id"], rec["contact_name"],
                 rec["order_date"], rec["city"], rec["country"], rec["total_price"]),
            )
            for it in rec["items"]:
                con.execute(
                    "INSERT INTO invoice_items(order_id, product_id, product_name, quantity, unit_price) VALUES (?,?,?,?,?)",
                    (rec["order_id"], it["product_id"], it["product_name"], it["quantity"], it["unit_price"]),
                )
            prods = " ".join(i["product_name"] for i in rec["items"])
            _fts(con, doc_id, "invoice", rec["order_id"],
                 f"invoice order {rec['order_id']} customer {rec['customer_id']} {rec['contact_name']} {rec['city']} {rec['country']} {prods}")
            bump("invoice")
        elif path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            doc_id = path.stem
            _register(con, doc_id, "image_invoice", path, path.suffix.lower().lstrip("."))
            # Only the vision step is cached: it is the one non-deterministic,
            # API-dependent extractor. Deterministic PDF/contract parsers run
            # every time (fast, and never go stale when the code changes).
            rec = cached(path, extract_image.extract_image_invoice)
            con.execute(
                "INSERT INTO image_invoices(doc_id, layout_family, invoice_number, issue_date, seller_name,"
                " seller_tax_id, seller_iban, client_name, client_tax_id, currency, subtotal, tax_amount, shipping, total)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, rec.get("layout_family"), rec.get("invoice_number"), rec.get("issue_date"),
                 rec.get("seller_name"), rec.get("seller_tax_id"), rec.get("seller_iban"),
                 rec.get("client_name"), rec.get("client_tax_id"), rec.get("currency"),
                 rec.get("subtotal"), rec.get("tax_amount"), rec.get("shipping"), rec.get("total")),
            )
            for it in rec.get("line_items", []):
                con.execute(
                    "INSERT INTO image_invoice_items(doc_id, description, qty, unit_price, amount) VALUES (?,?,?,?,?)",
                    (doc_id, it.get("description"), it.get("qty"), it.get("unit_price"), it.get("amount")),
                )
            descs = " ".join((i.get("description") or "") for i in rec.get("line_items", []))
            _fts(con, doc_id, "image_invoice", None,
                 f"invoice {rec.get('invoice_number') or ''} {rec.get('seller_name') or ''} {rec.get('client_name') or ''} {descs}")
            bump("image_invoice")

    # ---- Purchase orders ----------------------------------------------------
    for path in sorted((data_dir / "purchase_orders").glob("*.pdf")):
        doc_id = path.stem
        _register(con, doc_id, "purchase_order", path, "pdf")
        rec = extract_pdf.parse_purchase_order(path)
        con.execute(
            "INSERT INTO purchase_orders(order_id, doc_id, order_date, customer_name) VALUES (?,?,?,?)",
            (rec["order_id"], doc_id, rec["order_date"], rec["customer_name"]),
        )
        for it in rec["items"]:
            con.execute(
                "INSERT INTO po_items(order_id, product_id, product_name, quantity, unit_price) VALUES (?,?,?,?,?)",
                (rec["order_id"], it["product_id"], it["product_name"], it["quantity"], it["unit_price"]),
            )
        prods = " ".join(i["product_name"] for i in rec["items"])
        _fts(con, doc_id, "purchase_order", rec["order_id"],
             f"purchase order {rec['order_id']} {rec['customer_name']} {prods}")
        bump("purchase_order")

    # ---- Shipping orders ----------------------------------------------------
    for path in sorted((data_dir / "shipping_orders").glob("*.pdf")):
        doc_id = path.stem
        _register(con, doc_id, "shipping_order", path, "pdf")
        rec = extract_pdf.parse_shipping_order(path)
        con.execute(
            "INSERT INTO shipping_orders(order_id, doc_id, ship_name, ship_city, ship_region, ship_country,"
            " customer_id, customer_name, employee_name, shipper_name, order_date, shipped_date)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec["order_id"], doc_id, rec["ship_name"], rec["ship_city"], rec["ship_region"], rec["ship_country"],
             rec["customer_id"], rec["customer_name"], rec["employee_name"], rec["shipper_name"],
             rec["order_date"], rec["shipped_date"]),
        )
        for it in rec["items"]:
            con.execute(
                "INSERT INTO shipping_items(order_id, product_name, quantity, unit_price, total) VALUES (?,?,?,?,?)",
                (rec["order_id"], it["product_name"], it.get("quantity"), it.get("unit_price"), it.get("total")),
            )
        prods = " ".join(i["product_name"] for i in rec["items"])
        _fts(con, doc_id, "shipping_order", rec["order_id"],
             f"shipping order {rec['order_id']} {rec['ship_name']} {rec['ship_city']} {rec['ship_country']} {rec['customer_name']} {rec['employee_name']} {rec['shipper_name']} {prods}")
        bump("shipping_order")

    # ---- Inventory reports --------------------------------------------------
    for path in sorted((data_dir / "inventory_reports").glob("*.pdf")):
        doc_id = path.stem
        _register(con, doc_id, "inventory_report", path, "pdf")
        rec = extract_pdf.parse_inventory_report(path)
        con.execute(
            "INSERT INTO inventory_reports(doc_id, period, category, category_id) VALUES (?,?,?,?)",
            (doc_id, rec["period"], rec["category"], rec["category_id"]),
        )
        for ln in rec["lines"]:
            con.execute(
                "INSERT INTO inventory_lines(doc_id, product_name, units_sold, units_in_stock, unit_price) VALUES (?,?,?,?,?)",
                (doc_id, ln["product_name"], ln["units_sold"], ln["units_in_stock"], ln["unit_price"]),
            )
        prods = " ".join(l["product_name"] for l in rec["lines"])
        _fts(con, doc_id, "inventory_report", None,
             f"inventory stock report {rec['period']} category {rec['category']} {prods}")
        bump("inventory_report")

    # ---- Contract: chunks + colors + embeddings -----------------------------
    _ingest_contracts(con, data_dir, bump)

    con.commit()
    log.info("Ingested: %s", " · ".join(f"{k} {counts[k]}" for k in sorted(counts)))
    log.info("Database written to %s", db_path)
    con.close()


def _ingest_contracts(con, data_dir: Path, bump) -> None:
    import sqlite_vec

    next_id = 1
    indexed_rows: list[tuple[int, str]] = []  # (chunk_id, index_text)
    for path in sorted((data_dir / "contracts").glob("*.pdf")):
        doc_id = path.stem
        _register(con, doc_id, "contract", path, "pdf")
        chunks = extract_contract.extract_contract_chunks(path)
        _fts(con, doc_id, "contract", None,
             "master contract for supply of goods and services totalenergies template")
        for ch in chunks:
            cid = next_id
            next_id += 1
            con.execute(
                "INSERT INTO contract_chunks(chunk_id, doc_id, section, page, text, highlight, indexed)"
                " VALUES (?,?,?,?,?,?,?)",
                (cid, doc_id, ch["section"], ch["page"], ch["text"], ch["highlight"], ch["indexed"]),
            )
            if ch["indexed"]:
                idx_text = f"{ch['section']} — {ch['text']}"
                indexed_rows.append((cid, idx_text))
        bump("contract")

    excluded = next_id - 1 - len(indexed_rows)
    log.info("Contract: %d chunks, %d indexed, %d excluded (template/instruction blocks).",
             next_id - 1, len(indexed_rows), excluded)

    # BM25 keyword index over indexed chunks.
    for cid, text in indexed_rows:
        con.execute("INSERT INTO contract_fts(rowid, text) VALUES (?,?)", (cid, text))

    # Vector index over indexed chunks.
    vectors = embed.embed_texts([t for _, t in indexed_rows])
    if vectors is None:
        log.info("  Vectors skipped (BM25-only contract search).")
        return
    if getattr(con, "vec_enabled", False):
        for (cid, _), vec in zip(indexed_rows, vectors):
            con.execute("INSERT INTO contract_vec(chunk_id, embedding) VALUES (?, ?)",
                        (cid, sqlite_vec.serialize_float32(vec)))
    else:
        import numpy as np
        for (cid, _), vec in zip(indexed_rows, vectors):
            con.execute("INSERT INTO contract_vec_fallback(chunk_id, embedding) VALUES (?, ?)",
                        (cid, np.asarray(vec, dtype=np.float32).tobytes()))
    log.info("  Embedded %d chunks (%s, %d-d).", len(vectors), config.EMBED_MODEL, config.EMBED_DIM)


def main() -> None:
    # Progress goes to stderr; stdout is reserved (defensive, project-wide).
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    ap = argparse.ArgumentParser(description="Build the procurement knowledge base.")
    ap.add_argument("--data", type=Path, default=config.DATA_DIR)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    args = ap.parse_args()
    if not args.data.exists():
        sys.exit(f"Data directory not found: {args.data}")
    run(args.data, args.db)


if __name__ == "__main__":
    main()
