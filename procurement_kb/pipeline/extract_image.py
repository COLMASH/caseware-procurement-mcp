"""Structured extraction of the image-based invoices.

The 5 JPGs are heterogeneous (batch1 = formal EU; batch2 = industrial, often
headerless). A template OCR parser would break, so we hand the image to a
vision LLM with a tolerant Pydantic schema and let it absorb the layout
differences in one call. Results are cached by content hash.

The repo ships the 5 invoices pre-extracted in `cache/`, so this API path only
runs on a cache miss (e.g. a brand-new image) and requires ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import base64
from pathlib import Path

from .. import config
from ..models import ImageInvoice

_PROMPT = (
    "Extract this invoice into the given schema. It may be a formal European "
    "invoice (header, IBAN, VAT) or a bare industrial invoice (just a line-item "
    "table, sometimes with no header). Set layout_family to 'formal_eu' or "
    "'industrial'. Use null for anything absent; never invent values. Copy "
    "amounts exactly as printed, even if column totals look inconsistent."
)


def extract_image_invoice(path: Path) -> dict:
    """Vision-LLM extraction. Only reached on a cache miss."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            f"No cached extraction for {path.name} and ANTHROPIC_API_KEY is not set. "
            "The repo ships pre-extracted JSON in cache/; set the key to extract new images."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(path.read_bytes()).decode()
    schema = ImageInvoice.model_json_schema()

    resp = client.messages.create(
        model=config.VISION_MODEL,
        max_tokens=2048,
        tools=[{
            "name": "record_invoice",
            "description": "Record the structured invoice fields.",
            "input_schema": schema,
        }],
        tool_choice={"type": "tool", "name": "record_invoice"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            ],
        }],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return ImageInvoice.model_validate(block.input).model_dump()
    raise RuntimeError(f"Vision model returned no structured output for {path.name}")
