"""PDF → Markdown converter with dual-column awareness and italic markup.

Inspired by proofpdf; adapted for the claude-code-pdf-academic-proofreader
pipeline. Uses PyMuPDF to produce structured Markdown with HTML tags for
italics and page markers [[PAGE=N]].
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

try:
    import fitz  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path("/private/tmp/pdfdeps")))
    import fitz  # type: ignore


def _italic_flag() -> int:
    try:
        return int(fitz.TEXT_FONT_ITALIC)  # type: ignore[attr-defined]
    except Exception:
        return 2


def _is_italic_span(span: dict[str, object]) -> bool:
    font = str(span.get("font", "")).lower()
    flags = int(span.get("flags", 0) or 0)
    return bool(flags & _italic_flag()) or "italic" in font or "oblique" in font


def _span_text(span: dict[str, object]) -> str:
    chars = span.get("chars", [])
    return "".join(str(c.get("c", "")) for c in chars)


def _line_text(line: dict[str, object], apply_markup: bool = True) -> str:
    spans = line.get("spans", [])
    if not spans:
        return ""
    parts: list[str] = []
    for span in spans:
        text = _span_text(span)
        if not text.strip():
            continue
        if apply_markup and _is_italic_span(span):
            parts.append(f"<i>{text}</i>")
        else:
            parts.append(text)
    return "".join(parts)


def _classify_blocks(blocks: list[tuple]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Classify text blocks into left column, right column, and full-width."""
    if not blocks:
        return [], [], []

    xs = [b[0] for b in blocks]
    xes = [b[2] for b in blocks]
    min_x, max_x = min(xs), max(xes)
    width = max_x - min_x
    mid = min_x + width / 2

    left: list[tuple] = []
    right: list[tuple] = []
    full: list[tuple] = []

    for b in blocks:
        x0, _, x1, _, text, *_ = b
        if not text.strip() or x1 - x0 < 10:
            continue
        if x0 < mid - 40 and x1 > mid + 40:
            full.append(b)
        elif x1 <= mid + 40:
            left.append(b)
        elif x0 >= mid - 40:
            right.append(b)
        else:
            full.append(b)

    return left, right, full


def _sort_dual_column(blocks: list[tuple], page_rect: fitz.Rect) -> list[tuple]:
    """Sort blocks for dual-column layout: header → left → middle → right → footer."""
    left, right, full = _classify_blocks(blocks)
    is_dual = len(left) >= 3 and len(right) >= 3
    if not is_dual:
        return sorted(blocks, key=lambda b: (b[1], b[0]))

    left.sort(key=lambda b: b[1])
    right.sort(key=lambda b: b[1])
    full.sort(key=lambda b: b[1])

    body_top = min(
        left[0][1] if left else float("inf"),
        right[0][1] if right else float("inf"),
    )
    body_bottom = max(
        left[-1][3] if left else 0,
        right[-1][3] if right else 0,
    )

    header = [b for b in full if b[3] < body_top]
    footer = [b for b in full if b[1] > body_bottom]
    middle = [b for b in full if b not in header and b not in footer]

    result: list[tuple] = []
    result.extend(header)
    result.extend(left)
    result.extend(middle)
    result.extend(right)
    result.extend(footer)
    return result


def _page_to_markdown(page: fitz.Page, page_no: int, apply_markup: bool = True) -> str:
    """Convert a single PDF page to Markdown text."""
    raw = page.get_text("rawdict")
    blocks: list[tuple] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        lines = block.get("lines", [])
        line_texts: list[str] = []
        for line in lines:
            txt = _line_text(line, apply_markup=apply_markup)
            if txt.strip():
                line_texts.append(txt)
        if line_texts:
            paragraph = " ".join(line_texts)
            blocks.append((bbox[0], bbox[1], bbox[2], bbox[3], paragraph))

    sorted_blocks = _sort_dual_column(blocks, page.rect)
    paragraphs = [b[4] for b in sorted_blocks if b[4].strip()]

    if not paragraphs:
        return ""

    md = f"\n[[PAGE={page_no}]]\n\n"
    md += "\n\n".join(paragraphs)
    return md


def pdf_to_markdown(pdf_path: Path, apply_markup: bool = True) -> str:
    """Convert an entire PDF to Markdown with page markers and italic markup."""
    doc = fitz.open(pdf_path)
    try:
        parts: list[str] = []
        for page_no, page in enumerate(doc, start=1):
            md = _page_to_markdown(page, page_no, apply_markup=apply_markup)
            if md:
                parts.append(md)
        return "\n".join(parts)
    finally:
        doc.close()
