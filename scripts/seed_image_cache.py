"""Seed the extraction cache with the 5 image invoices.

These records were produced by a vision model (Claude) reading each JPG, then
hand-verified against the image. Seeding the cache keyed by content hash lets
`pipeline.run` reproduce the full knowledge base OFFLINE with no API key, while
`extract_image.py` keeps the real vision path for any new/unseen image.

    uv run python scripts/seed_image_cache.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from procurement_kb import config              # noqa: E402
from procurement_kb.models import ImageInvoice  # noqa: E402
from procurement_kb.pipeline.cache import sha256_file  # noqa: E402

INVOICES = config.DATA_DIR / "invoices"

RECORDS: dict[str, dict] = {
    "batch1-1486.jpg": {
        "layout_family": "formal_eu", "invoice_number": "23285582", "issue_date": "12/19/2015",
        "seller_name": "Harris-Green", "seller_tax_id": "935-80-2834", "seller_iban": "GB11QYTR88328261828600",
        "client_name": "Good PLC", "client_tax_id": "993-98-0454",
        "currency": "USD", "subtotal": 34624.30, "tax_amount": 3462.43, "shipping": None, "total": 38086.73,
        "line_items": [
            {"description": "16 Inches Marble Coffee Table Top Inlay with Multi Stone at Border Game Table", "qty": 4, "unit_price": 280.50, "amount": 1234.20},
            {"description": "6'x3' Black Marble Large Dining Table Top Very Fine Handmade Marquetry Birds Art", "qty": 5, "unit_price": 5303.66, "amount": 29170.13},
            {"description": "Luxurious Pattern Stone Dinning Table Top Marble Conference Table Size 48 Inches", "qty": 2, "unit_price": 3492.00, "amount": 7682.40},
        ],
    },
    "batch1-1488.jpg": {
        "layout_family": "formal_eu", "invoice_number": "77833987", "issue_date": "05/20/2013",
        "seller_name": "Freeman and Sons", "seller_tax_id": "973-76-8676", "seller_iban": "GB43RCPI15397639476218",
        "client_name": "Houston Group", "client_tax_id": "901-88-1175",
        "currency": "USD", "subtotal": 117.75, "tax_amount": 11.78, "shipping": None, "total": 129.53,
        "line_items": [
            {"description": "Introduction to Thematic Cartography", "qty": 1, "unit_price": 8.99, "amount": 9.89},
            {"description": "Sonic Wind The Story of John Paul Stapp and How a Renegade Doctor Be", "qty": 1, "unit_price": 4.49, "amount": 4.94},
            {"description": "Entertaining", "qty": 1, "unit_price": 4.49, "amount": 4.94},
            {"description": "Rebecca to the Rescue (American Girl (Quality))", "qty": 2, "unit_price": 4.89, "amount": 10.76},
            {"description": "Gulag archipelago / Gulag Archipelago Volume 2 / 1st edition paperbacks", "qty": 3, "unit_price": 30.00, "amount": 99.00},
        ],
    },
    "batch2-0998.jpg": {
        "layout_family": "industrial", "invoice_number": None, "issue_date": None,
        "seller_name": None, "client_name": None,
        "currency": "USD", "subtotal": 1289.0, "tax_amount": None, "shipping": 50.0, "total": 1339.0,
        "line_items": [
            {"description": "3M 49 Fastbond Insulation Adh. 5 Gal 1 x 5gal/pail", "qty": 1, "unit_price": 119.00, "amount": 119.0},
            {"description": "Activator CREAM 5-gal 5 gallons/pailt", "qty": 2, "unit_price": 130.00, "amount": 260.0},
            {"description": "AEB2461 PTFE 10\"x36YDS 5mil Glass Cloth Fabric / No Adh.", "qty": 4, "unit_price": 174.00, "amount": 696.0},
            {"description": "Permabond 106 Cyanoacrylate 1-oz 10 bottles/case", "qty": 2, "unit_price": 107.00, "amount": 214.0},
        ],
    },
    "batch2-0999.jpg": {
        "layout_family": "industrial", "invoice_number": "118", "issue_date": "March 9, 2022",
        "seller_name": "BLUE STREAK ELECTRONICS", "client_name": "GEONICS LTD",
        "currency": "USD", "subtotal": 804.0, "tax_amount": 63.47, "shipping": 50.0, "total": 916.47,
        "line_items": [
            {"description": "3M Scotchcast Electrical Resin #8 - 16 lbs/kit 16 lbs/case", "qty": 2, "unit_price": 346.00, "amount": 346.00},
            {"description": "3M DP460 EG Epoxy Adhesive - 50ml 2:1 12 kits/case", "qty": 4, "unit_price": 226.00, "amount": 226.00},
            {"description": "Freight AE Blake Montreal to Aerospace Metal", "qty": 6, "unit_price": 136.00, "amount": 136.00},
            {"description": "Lead-time is a mere estimate. Actual delivery may differ without notice", "qty": 8, "unit_price": 96.00, "amount": 96.00},
        ],
    },
    "batch2-1000.jpg": {
        "layout_family": "industrial", "invoice_number": None, "issue_date": None,
        "seller_name": None, "client_name": None,
        "currency": "USD", "subtotal": 1175.0, "tax_amount": 93.70, "shipping": 50.0, "total": 1317.70,
        "line_items": [
            {"description": "3M 205 Painters Tape 48mm x 55m GREEN 24 rolls/case | 1,152 rolls/skid", "qty": 2, "unit_price": 266.00, "amount": 266.00},
            {"description": "3M R3187 Repulp.BLUE 96mm x55m 8 rolls/case", "qty": 5, "unit_price": 61.00, "amount": 61.00},
            {"description": "3M 3792LM TCQ Jet Melt 8\"x 11lbs. 5/8\" CLEAR | 11 pounds/case", "qty": 7, "unit_price": 136.00, "amount": 136.00},
            {"description": "3M BBI-4A-50' HeatShrink Tube 5.43\"-8.86\"OD", "qty": 1, "unit_price": 716.00, "amount": 716.00},
        ],
    },
}


def main() -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for name, raw in RECORDS.items():
        path = INVOICES / name
        if not path.exists():
            print(f"  SKIP (missing): {name}")
            continue
        record = ImageInvoice.model_validate(raw).model_dump()  # validate against schema
        digest = sha256_file(path)
        out = config.CACHE_DIR / f"{digest}.json"
        out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"  seeded {name} -> cache/{digest[:12]}….json")


if __name__ == "__main__":
    main()
