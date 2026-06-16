"""Content-hash extraction cache.

Keyed on the SHA-256 of the source bytes, so the pipeline is re-runnable and a
re-run never re-OCRs or re-calls the vision API. The repo ships the 5 image
invoices pre-extracted here, so `pipeline.run` works fully offline.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .. import config


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cached(path: Path | str, extract_fn: Callable[[Path], dict | list]) -> dict | list:
    """Return cached extraction for `path`, computing + storing it on a miss."""
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(path)
    cache_file = config.CACHE_DIR / f"{digest}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    result = extract_fn(Path(path))
    cache_file.write_text(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    return result
