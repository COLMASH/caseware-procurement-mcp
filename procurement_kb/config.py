"""Central configuration: paths and model settings.

Everything is resolved relative to the repo root so the project is portable and
re-runnable from any working directory.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root = parent of the `procurement_kb` package directory.
ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal ``.env`` loader — no third-party dependency.

    Populates ``os.environ`` from a ``.env`` file at the repo root so a key
    written there (e.g. ``ANTHROPIC_API_KEY=sk-ant-...``) is picked up like an
    ``export``. Uses ``setdefault``, so a variable already set in the real
    environment (``export`` or an inline ``VAR=... uv run ...``) always wins.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):  # tolerate `export VAR=...`
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")  # drop optional quotes
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()

DATA_DIR = Path(os.environ.get("PKB_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("PKB_DB_PATH", ROOT / "procurement.db"))
CACHE_DIR = Path(os.environ.get("PKB_CACHE_DIR", ROOT / "cache"))
MODELS_DIR = Path(os.environ.get("PKB_MODELS_DIR", ROOT / ".models"))

# Embeddings (local, ONNX, no torch). 384-dim keeps the sqlite-vec index small.
EMBED_MODEL = os.environ.get("PKB_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384

# Vision extraction of the image invoices. Only used on a cache miss; the repo
# ships pre-extracted JSON in `cache/`, so the pipeline runs fully offline.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
VISION_MODEL = os.environ.get("PKB_VISION_MODEL", "claude-opus-4-8")

# Document categories (folder name -> canonical category).
CATEGORIES = {
    "invoices": "invoice",          # note: invoices/ holds BOTH pdf and jpg
    "purchase_orders": "purchase_order",
    "shipping_orders": "shipping_order",
    "inventory_reports": "inventory_report",
    "contracts": "contract",
}
