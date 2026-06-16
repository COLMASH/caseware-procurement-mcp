"""SQLite layer: one file holds the relational tables, an FTS5 keyword index,
and the contract vector index (sqlite-vec, with a pure-Python fallback).

Design choice: structured records live in real tables so the relational
questions ("which invoices have no PO?", "mismatches?") are deterministic SQL.
Only the narrative contract is embedded.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

# Detect sqlite-vec availability once.
try:
    import sqlite_vec  # noqa: F401
    _HAVE_SQLITE_VEC = True
except Exception:  # pragma: no cover
    _HAVE_SQLITE_VEC = False


class Connection(sqlite3.Connection):
    """Subclass so we can stash `vec_enabled` (the base C type forbids attrs)."""

    vec_enabled: bool = False


def connect(db_path: Path | str | None = None, *, read_only: bool = False) -> Connection:
    path = Path(db_path or config.DB_PATH)
    if read_only:
        if not path.exists():
            raise FileNotFoundError(
                f"Knowledge base not found at {path}. Build it first:\n"
                f"    uv run python -m procurement_kb.pipeline.run"
            )
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, factory=Connection)
    else:
        con = sqlite3.connect(path, factory=Connection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    # Best-effort load of the sqlite-vec extension.
    con.vec_enabled = False
    if _HAVE_SQLITE_VEC:
        try:
            con.enable_load_extension(True)
            import sqlite_vec

            sqlite_vec.load(con)
            con.enable_load_extension(False)
            con.vec_enabled = True
        except Exception:
            con.vec_enabled = False
    return con


SCHEMA = f"""
-- ------------------------------------------------------------------ --
-- Lineage registry: every source file, so every answer can be traced --
-- ------------------------------------------------------------------ --
CREATE TABLE documents (
    doc_id       TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    file_type    TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    page_count   INTEGER,
    ingested_at  TEXT DEFAULT (datetime('now'))
);

-- ---------------- Northwind transactional graph (join on order_id) ---------- --
CREATE TABLE invoices (
    order_id     INTEGER PRIMARY KEY,
    doc_id       TEXT REFERENCES documents(doc_id),
    customer_id  TEXT,
    contact_name TEXT,
    order_date   TEXT,
    city         TEXT,
    country      TEXT,
    total_price  REAL
);
CREATE TABLE invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES invoices(order_id),
    product_id INTEGER, product_name TEXT, quantity REAL, unit_price REAL
);

CREATE TABLE purchase_orders (
    order_id      INTEGER PRIMARY KEY,
    doc_id        TEXT REFERENCES documents(doc_id),
    order_date    TEXT,
    customer_name TEXT
);
CREATE TABLE po_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES purchase_orders(order_id),
    product_id INTEGER, product_name TEXT, quantity REAL, unit_price REAL
);

CREATE TABLE shipping_orders (
    order_id      INTEGER PRIMARY KEY,
    doc_id        TEXT REFERENCES documents(doc_id),
    ship_name     TEXT, ship_city TEXT, ship_region TEXT, ship_country TEXT,
    customer_id   TEXT, customer_name TEXT,
    employee_name TEXT, shipper_name TEXT,
    order_date    TEXT, shipped_date TEXT
);
CREATE TABLE shipping_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES shipping_orders(order_id),
    product_name TEXT, quantity REAL, unit_price REAL, total REAL
);

CREATE TABLE inventory_reports (
    doc_id      TEXT PRIMARY KEY REFERENCES documents(doc_id),
    period      TEXT, category TEXT, category_id INTEGER
);
CREATE TABLE inventory_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT REFERENCES inventory_reports(doc_id),
    product_name TEXT, units_sold REAL, units_in_stock REAL, unit_price REAL
);

-- ---------------- Image invoices: SEPARATE universe (no order_id) ----------- --
CREATE TABLE image_invoices (
    doc_id         TEXT PRIMARY KEY REFERENCES documents(doc_id),
    layout_family  TEXT,
    invoice_number TEXT, issue_date TEXT,
    seller_name    TEXT, seller_tax_id TEXT, seller_iban TEXT,
    client_name    TEXT, client_tax_id TEXT,
    currency       TEXT, subtotal REAL, tax_amount REAL, shipping REAL, total REAL
);
CREATE TABLE image_invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT REFERENCES image_invoices(doc_id),
    description TEXT, qty REAL, unit_price REAL, amount REAL
);

-- ---------------- Contract: narrative chunks + color metadata --------------- --
CREATE TABLE contract_chunks (
    chunk_id  INTEGER PRIMARY KEY,
    doc_id    TEXT REFERENCES documents(doc_id),
    section   TEXT, page INTEGER, text TEXT,
    highlight TEXT,             -- none | placeholder | info | option
    indexed   INTEGER           -- 1 if part of the retrievable index (info excluded)
);

-- ---------------- Unified keyword index over structured records ------------- --
CREATE VIRTUAL TABLE doc_fts USING fts5(
    content, doc_id UNINDEXED, category UNINDEXED, order_id UNINDEXED
);

-- ---------------- Contract keyword index (BM25) ----------------------------- --
CREATE VIRTUAL TABLE contract_fts USING fts5(text, content='');
"""

# Vector index DDL is created separately because it depends on the backend.
VEC_DDL = f"CREATE VIRTUAL TABLE contract_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{config.EMBED_DIM}]);"
VEC_FALLBACK_DDL = "CREATE TABLE contract_vec_fallback (chunk_id INTEGER PRIMARY KEY, embedding BLOB);"


def init_db(con: sqlite3.Connection) -> None:
    """Drop everything and recreate (idempotent / re-runnable).

    Tables are dropped child-first: every table that REFERENCES another is
    dropped before its parent, with `documents` (the lineage root that all
    record tables reference) last. With `PRAGMA foreign_keys = ON`, dropping a
    parent while child rows still reference it raises
    `FOREIGN KEY constraint failed`, so this order is what makes a re-run over
    an already-populated database work.
    """
    cur = con.cursor()
    drops = [
        # FTS / vector virtual tables (no foreign keys) — safe to drop anytime.
        "doc_fts", "contract_fts", "contract_vec", "contract_vec_fallback",
        # Child tables before the parents they reference.
        "invoice_items", "invoices",
        "po_items", "purchase_orders",
        "shipping_items", "shipping_orders",
        "inventory_lines", "inventory_reports",
        "image_invoice_items", "image_invoices",
        "contract_chunks",
        # Lineage root last: everything above references documents(doc_id).
        "documents",
    ]
    for t in drops:
        cur.execute(f"DROP TABLE IF EXISTS {t}")
    cur.executescript(SCHEMA)
    if getattr(con, "vec_enabled", False):
        cur.execute(VEC_DDL)
    else:
        cur.execute(VEC_FALLBACK_DDL)
    con.commit()
