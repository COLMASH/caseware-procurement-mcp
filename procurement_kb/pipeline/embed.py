"""Local embeddings via fastembed (ONNX bge-small, no torch, no GPU).

Degrades gracefully: if the model cannot be loaded/downloaded, returns None and
the pipeline falls back to FTS5/BM25-only contract search.
"""
from __future__ import annotations

import logging

from .. import config

# NOTE: logging only (never print). This module is imported by the MCP server,
# where stdout is the JSON-RPC channel and must not be polluted.
log = logging.getLogger("procurement_kb.embed")

_model = None


def get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        _model = TextEmbedding(model_name=config.EMBED_MODEL, cache_dir=str(config.MODELS_DIR))
    return _model


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    if not texts:
        return []
    try:
        model = get_model()
        return [vec.tolist() for vec in model.embed(texts)]
    except Exception as exc:  # pragma: no cover
        log.warning("embeddings unavailable (%s); contract search will use BM25 only.", exc)
        return None
