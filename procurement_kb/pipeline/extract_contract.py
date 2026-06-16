"""Contract extraction: text + semantic highlight colors (no OCR).

The contract is a digital PDF, so text comes out perfectly with PyMuPDF and the
highlights are vector fill-rects (not pixels), read in milliseconds at zero
token cost. Per the document's own legend:
    yellow = placeholder to complete    green = authoring instruction
    grey   = optional clause            (blue = section-header formatting, ignored)

We use color as data-quality metadata: green/meta instruction blocks are tagged
'info' and EXCLUDED from the retrievable index, so the agent never returns
template boilerplate ("the supplier is [NAME OF SUPPLIER]") as a real term.
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

_CHUNK_CHARS = 1400
_META_PHRASES = ("to be deleted before issuing", "instructions for use of the document")
_HEADING_RE = re.compile(
    r"^(PART\b|ARTICLE\b|SCHEDULE\b|APPENDIX\b|SECTION\b|\d+(\.\d+)*\.?\s+\S)"
)


def _classify(fill) -> str | None:
    """Map an RGB fill (0-1 tuple) to a highlight kind, else None."""
    if not fill or len(fill) < 3:
        return None
    r, g, b = fill[0], fill[1], fill[2]
    if r > 0.8 and g > 0.8 and b < 0.35:
        return "placeholder"          # yellow
    if r < 0.35 and g > 0.7 and b < 0.35:
        return "info"                 # green
    if 0.74 < r < 0.92 and abs(r - g) < 0.07 and abs(g - b) < 0.07:
        return "option"               # grey
    return None


def _colored_rects(page) -> list[tuple[str, fitz.Rect]]:
    out = []
    for d in page.get_drawings():
        kind = _classify(d.get("fill"))
        if kind:
            out.append((kind, fitz.Rect(d["rect"])))
    return out


def _line_kind(bbox: fitz.Rect, rects: list[tuple[str, fitz.Rect]]) -> str:
    """Dominant highlight over a line (priority green > yellow > grey)."""
    area = max(bbox.get_area(), 1.0)
    found = set()
    for kind, r in rects:
        inter = bbox & r
        if inter.is_valid and inter.get_area() / area > 0.2:
            found.add(kind)
    for k in ("info", "placeholder", "option"):
        if k in found:
            return k
    return "none"


def _is_heading(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 90:
        return False
    if _HEADING_RE.match(t):
        return True
    return t.isupper() and 4 <= len(t) <= 70 and not t.endswith(".")


def extract_contract_chunks(path: Path) -> list[dict]:
    doc = fitz.open(path)
    ordered: list[tuple[int, str, str, bool]] = []  # (page1, text, kind, is_heading)
    for pno in range(doc.page_count):
        page = doc[pno]
        rects = _colored_rects(page)
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                if not text:
                    continue
                kind = _line_kind(fitz.Rect(line["bbox"]), rects)
                ordered.append((pno + 1, text, kind, _is_heading(text)))

    chunks: list[dict] = []
    cur: list[tuple[str, str]] = []
    section = "Preamble"
    page_start: int | None = None

    def flush():
        nonlocal cur, page_start
        if not cur:
            return
        body = " ".join(t for t, _ in cur).strip()
        if not body:
            cur = []
            return
        low = body.lower()
        counts: dict[str, int] = {}
        for t, k in cur:
            counts[k] = counts.get(k, 0) + len(t)
        total = sum(counts.values()) or 1
        if any(p in low for p in _META_PHRASES) or counts.get("info", 0) / total > 0.4:
            highlight = "info"
        elif counts.get("placeholder", 0) > 0:
            highlight = "placeholder"
        elif counts.get("option", 0) > 0:
            highlight = "option"
        else:
            highlight = "none"
        chunks.append({
            "section": section,
            "page": page_start or 1,
            "text": body,
            "highlight": highlight,
            "indexed": 0 if highlight == "info" else 1,
        })
        cur = []
        page_start = None

    for page1, text, kind, is_head in ordered:
        if is_head:
            flush()
            section = text
            continue
        if page_start is None:
            page_start = page1
        cur.append((text, kind))
        if sum(len(t) for t, _ in cur) >= _CHUNK_CHARS:
            flush()
    flush()
    return chunks
