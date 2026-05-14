#!/usr/bin/env python3
"""High-precision PDF proofreading pipeline for Chinese academic journals.

Extracts rich text with markup, renders pages at high quality, runs rule checks,
and produces a unified review_context.md designed for deep AI editorial review.

Usage:
    python pdf_pipeline.py --root <folder> --output <folder>/BBB --mode prepare --limit 1
    python pdf_pipeline.py --root <folder> --output <folder>/BBB --mode annotate --findings-json <path> --limit 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    import fitz  # type: ignore
except ModuleNotFoundError:
    tmp_deps = Path(os.environ.get("PDFDEPS_PATH", "/private/tmp/pdfdeps"))
    if tmp_deps.exists():
        sys.path.insert(0, str(tmp_deps))
    import fitz  # type: ignore

from shared_rules import Finding, dedupe_findings, SUBSCRIPT_PREFIXES, STAT_SYMBOL_PATTERNS, TEXT_TARGET_RULES, REGEX_RULES


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def pdfs_under(root: Path, output_dir: Path) -> list[Path]:
    output_dir = output_dir.resolve()
    pdfs: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() != ".pdf" or not path.is_file():
            continue
        try:
            if output_dir in path.resolve().parents:
                continue
        except FileNotFoundError:
            pass
        pdfs.append(path)
    return pdfs


# ---------------------------------------------------------------------------
# Character-level extraction (for rule checks)
# ---------------------------------------------------------------------------
def page_chars(page: fitz.Page) -> Iterator[dict[str, object]]:
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    yield {
                        "c": char.get("c", ""),
                        "bbox": tuple(char.get("bbox", (0, 0, 0, 0))),
                        "font": span.get("font", ""),
                        "flags": span.get("flags", 0),
                        "size": span.get("size", 0),
                    }


def _italic_flag() -> int:
    try:
        return int(fitz.TEXT_FONT_ITALIC)  # type: ignore[attr-defined]
    except Exception:
        return 2


def _bold_flag() -> int:
    try:
        return int(fitz.TEXT_FONT_BOLD)  # type: ignore[attr-defined]
    except Exception:
        return 1


def is_italic(char: dict[str, object]) -> bool:
    font = str(char.get("font", "")).lower()
    flags = int(char.get("flags", 0))
    return bool(flags & _italic_flag()) or "italic" in font or "oblique" in font


def union_rect(rects: Iterable[fitz.Rect]) -> fitz.Rect:
    items = list(rects)
    if not items:
        return fitz.Rect(0, 0, 0, 0)
    rect = fitz.Rect(items[0])
    for item in items[1:]:
        rect |= fitz.Rect(item)
    return rect


def char_rect(chars: list[dict[str, object]]) -> tuple[float, float, float, float]:
    rect = union_rect(fitz.Rect(char["bbox"]) for char in chars)  # type: ignore[arg-type]
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def compact(s: str) -> str:
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------------------
# Text extraction with markup (superscript / subscript / italic)
# ---------------------------------------------------------------------------
def _is_italic_span(span: dict[str, object]) -> bool:
    font = str(span.get("font", "")).lower()
    flags = int(span.get("flags", 0) or 0)
    return bool(flags & _italic_flag()) or "italic" in font or "oblique" in font


def _is_bold_span(span: dict[str, object]) -> bool:
    font = str(span.get("font", "")).lower()
    flags = int(span.get("flags", 0) or 0)
    return bool(flags & _bold_flag()) or "bold" in font


def _span_text_with_markup(span: dict[str, object], apply_markup: bool = True) -> str:
    chars = span.get("chars", [])
    if not chars:
        return ""

    text_parts: list[str] = []
    if not apply_markup:
        return "".join(str(c.get("c", "")) for c in chars)

    # Collect character info
    char_infos: list[dict[str, Any]] = []
    for c in chars:
        char_infos.append({
            "c": str(c.get("c", "")),
            "bbox": tuple(c.get("bbox", (0, 0, 0, 0))),
            "font": str(span.get("font", "")),
            "flags": int(span.get("flags", 0) or 0),
            "size": float(span.get("size", 0) or 0),
        })

    if not char_infos:
        return ""

    # Determine baseline and average size from the span
    base_size = float(span.get("size", 0) or 0)
    if base_size <= 0 and char_infos:
        base_size = max(ci["size"] for ci in char_infos)

    # Estimate baseline from majority of characters
    ys = [ci["bbox"][1] for ci in char_infos]
    baseline = sum(ys) / len(ys) if ys else 0

    # Tag each char — bold, italic and sub/sup can co-occur
    tagged: list[tuple[str, str]] = []  # (tag_string, char)
    for ci in char_infos:
        c = ci["c"]
        size = ci["size"]
        y = ci["bbox"][1]
        dy = y - baseline
        tags: list[str] = []
        if size > 0 and base_size > 0:
            if size < base_size * 0.85 and dy < -base_size * 0.1:
                tags.append("sup")
            elif size < base_size * 0.85 and dy > base_size * 0.05:
                tags.append("sub")
        if _is_italic_span(span):
            tags.append("i")
        if _is_bold_span(span):
            tags.append("b")
        # Canonical tag order: bold outermost, italic middle, sub/sup innermost
        tags.sort(key=lambda t: {"sub": 0, "sup": 0, "i": 1, "b": 2}.get(t, 3))
        tagged.append(("+".join(tags) if tags else "", c))

    # Merge consecutive identical tag-sets
    result_parts: list[str] = []
    current_tag_set = ""
    current_chars: list[str] = []

    def _wrap(s: str, tag_list: list[str]) -> str:
        for t in tag_list:
            s = f"<{t}>{s}</{t}>"
        return s

    def flush():
        if not current_chars:
            return
        s = "".join(current_chars)
        if current_tag_set:
            tag_list = current_tag_set.split("+")
            result_parts.append(_wrap(s, tag_list))
        else:
            result_parts.append(s)

    for tag_set, c in tagged:
        if tag_set != current_tag_set:
            flush()
            current_tag_set = tag_set
            current_chars = [c]
        else:
            current_chars.append(c)
    flush()

    return "".join(result_parts)


def _line_text_with_markup(line: dict[str, object], apply_markup: bool = True) -> str:
    spans = line.get("spans", [])
    if not spans:
        return ""
    parts: list[str] = []
    for span in spans:
        text = _span_text_with_markup(span, apply_markup=apply_markup)
        if text:
            parts.append(text)
    return "".join(parts)


def _vertical_coverage(blocks: list[tuple]) -> float:
    """Fraction of page height covered by the given blocks (0.0–1.0)."""
    if not blocks:
        return 0.0
    ys = sorted([b[1] for b in blocks])
    total = 0.0
    current_start = ys[0]
    current_end = ys[0]
    for y in ys[1:]:
        if y <= current_end + 20:
            current_end = y
        else:
            total += current_end - current_start
            current_start = y
            current_end = y
    total += current_end - current_start
    # Normalize against a typical A4 body height (~750pt). Using actual page
    # height would require passing page_rect, but the threshold check only
    # needs a rough relative measure — the caller already requires ≥3 blocks
    # on each side, so coverage just guards against narrow incidental columns.
    return total / 800.0 if total > 0 else 0.0


def _classify_blocks(blocks: list[tuple], page_rect: fitz.Rect) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Split blocks into left-column, right-column, and full-width groups.

    Uses the actual page midpoint (not block-extent midpoint) so that
    single-column pages with narrow content aren't misclassified.
    """
    if not blocks:
        return [], [], []
    mid = page_rect.width / 2

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
    """Re-order blocks for dual-column reading order: header → left col → middle → right col → footer.

    Single-column pages are returned in natural top-to-bottom order.
    Dual-column detection requires ≥3 blocks on each side AND ≥30% vertical
    coverage on each side (matching extract_page_text criteria), which guards
    against false positives on pages where content happens to cluster left/right.
    """
    left, right, full = _classify_blocks(blocks, page_rect)
    left_cov = _vertical_coverage(left)
    right_cov = _vertical_coverage(right)
    is_dual = (
        len(left) >= 3 and len(right) >= 3
        and left_cov >= 0.30 and right_cov >= 0.30
    )
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
    raw = page.get_text("rawdict")
    blocks: list[tuple] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        lines = block.get("lines", [])
        line_texts: list[str] = []
        for line in lines:
            txt = _line_text_with_markup(line, apply_markup=apply_markup)
            if txt.strip():
                line_texts.append(txt)
        if line_texts:
            paragraph = "\n".join(line_texts)
            blocks.append((bbox[0], bbox[1], bbox[2], bbox[3], paragraph))

    sorted_blocks = _sort_dual_column(blocks, page.rect)
    raw_paragraphs = [b[4] for b in sorted_blocks if b[4].strip()]

    if not raw_paragraphs:
        return ""

    # Detect tables and build structured representations
    table_regions: list[tuple[float, float, str]] = []  # (y0, y1, table_md)
    try:
        tables = page.find_tables()
        for table in tables:
            extracted = table.extract()
            if not extracted:
                continue
            rows = len(extracted)
            cols = max(len(row) for row in extracted) if rows else 0
            if rows < 2 or cols < 2:
                continue
            tb = table.bbox  # (x0, y0, x1, y1)
            tbl_md = f"\n[TABLE_START rows={rows} cols={cols}]\n"
            for ri, row in enumerate(extracted):
                cells = []
                for ci, cell in enumerate(row):
                    cell_text = (cell or "").strip().replace("\n", " ")
                    cells.append(cell_text if cell_text else "—")
                tbl_md += "| " + " | ".join(cells) + " |\n"
                if ri == 0:
                    tbl_md += "|" + "|".join(["---"] * len(cells)) + "|\n"
            tbl_md += "[TABLE_END]\n"
            table_regions.append((tb[1], tb[3], tbl_md))
    except Exception:
        pass  # find_tables may fail on some PDFs; degrade gracefully

    md = f"\n[[PAGE={page_no}]]\n\n"
    pi = 0
    # Compute paragraph y-position as midpoint of its original block's y-range
    para_y_mid = {}
    for b in sorted_blocks:
        if b[4].strip():
            para_y_mid[b[4].strip()] = (b[1] + b[3]) / 2

    for para in raw_paragraphs:
        # Insert any table whose top edge falls before this paragraph
        para_y = para_y_mid.get(para, 0)
        while table_regions and table_regions[0][0] < para_y:
            _, _, tbl_md = table_regions.pop(0)
            md += tbl_md + "\n"
        pi += 1
        pid = f"{page_no}.{pi}"
        md += f"[¶{pid}] {para}\n\n"

    # Any remaining tables after all paragraphs
    for _, _, tbl_md in table_regions:
        md += tbl_md + "\n"

    return md


def extract_page_text(page: fitz.Page) -> str:
    """Plain text extraction with dual-column awareness.

    Shares block-classification and column-detection logic with the markdown
    extraction path (_sort_dual_column) so both outputs agree on reading order.
    """
    blocks = page.get_text("blocks")
    if not blocks:
        return page.get_text("text") or ""

    left, right, full = _classify_blocks(blocks, page.rect)
    left_cov = _vertical_coverage(left)
    right_cov = _vertical_coverage(right)
    is_dual = (
        len(left) >= 3 and len(right) >= 3
        and left_cov >= 0.30 and right_cov >= 0.30
    )
    if not is_dual:
        return page.get_text("text") or ""

    sorted_blocks = _sort_dual_column(blocks, page.rect)
    return "\n".join(b[4] for b in sorted_blocks)


def write_text_artifacts(doc: fitz.Document, pdf: Path, artifact_dir: Path) -> Path:
    """Write extracted text, markdown with markup, and per-page text files."""
    paper_dir = artifact_dir / pdf.stem
    paper_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[str] = []
    for page_no, page in enumerate(doc, start=1):
        text = extract_page_text(page)
        chunks.append(f"===== PAGE {page_no} =====\n{text}\n")
        (paper_dir / f"page_{page_no:03d}.txt").write_text(text, encoding="utf-8")

    fulltext_txt = "\n".join(chunks)
    (paper_dir / "fulltext.txt").write_text(fulltext_txt, encoding="utf-8")

    # Markdown with italic/sup/sub markup
    md_parts: list[str] = []
    for page_no, page in enumerate(doc, start=1):
        md = _page_to_markdown(page, page_no, apply_markup=True)
        if md:
            md_parts.append(md)

    fulltext_md = "\n".join(md_parts)
    (paper_dir / "fulltext.md").write_text(fulltext_md, encoding="utf-8")
    return paper_dir


# ---------------------------------------------------------------------------
# Rule-based detectors (retained from low_cost_pdf_pipeline.py)
# ---------------------------------------------------------------------------
def add_text_finding(
    findings: list[Finding],
    filename: str,
    page: int,
    target: str,
    category: str,
    suggestion: str,
    severity: str = "medium",
    source: str = "rule",
    occurrence: int = 0,
) -> None:
    findings.append(
        Finding(
            file=filename,
            page=page,
            target=target,
            category=category,
            suggestion=suggestion,
            severity=severity,
            source=source,
            occurrence=occurrence,
        )
    )


def _add_regex_findings(
    findings: list[Finding],
    filename: str,
    page_no: int,
    text: str,
    patterns: list[tuple[str, str, str]],
) -> None:
    for regex, category, suggestion in patterns:
        occurrence = 0
        for match in re.finditer(regex, text):
            add_text_finding(
                findings,
                filename,
                page_no,
                match.group(),
                category,
                suggestion,
                occurrence=occurrence,
            )
            occurrence += 1


def detect_stat_symbol_style(doc: fitz.Document, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    stat_patterns = STAT_SYMBOL_PATTERNS
    for page_no, page in enumerate(doc, start=1):
        chars = list(page_chars(page))
        text = "".join(str(ch["c"]) for ch in chars)
        for regex, symbol_label, desc in stat_patterns:
            for match in regex.finditer(text):
                start, end = match.start(), match.end()
                run = chars[start:end]
                if not run:
                    continue
                symbol_char = run[0]
                rect = char_rect(run)
                ys = [float(ch["bbox"][1]) for ch in run]  # type: ignore[index]
                size = float(symbol_char.get("size", 0) or 0)
                if not is_italic(symbol_char):
                    findings.append(
                        Finding(
                            filename,
                            page_no,
                            f"auto:stat-style:{symbol_label}:{page_no}:{start}",
                            "公式/统计符号正斜体",
                            f"字符级字体检查显示，此处{desc}为正体。建议排为斜体。",
                            severity="medium",
                            source="char-font",
                            fallback_rect=rect,
                        )
                    )
                if max(ys) - min(ys) > max(3.0, size * 0.6):
                    findings.append(
                        Finding(
                            filename,
                            page_no,
                            f"auto:stat-linebreak:{symbol_label}:{page_no}:{start}",
                            "公式/统计表达断行",
                            "字符级位置检查显示，统计表达被拆成跨行显示。建议避免在统计表达内部断行。",
                            severity="medium",
                            source="char-position",
                            fallback_rect=rect,
                        )
                    )
    return findings


def detect_script_style(doc: fitz.Document, filename: str) -> list[Finding]:
    """Detect missing subscripts for common variable+digit patterns (e.g., I30, T1)."""
    findings: list[Finding] = []
    subscript_prefixes = SUBSCRIPT_PREFIXES
    for page_no, page in enumerate(doc, start=1):
        chars = list(page_chars(page))
        text = "".join(str(ch["c"]) for ch in chars)
        i = 0
        while i < len(chars) - 1:
            ch = chars[i]
            if ch["c"].isalpha() and ch["c"] in subscript_prefixes and is_italic(ch):
                letter_rect = fitz.Rect(ch["bbox"])
                letter_size = float(ch.get("size", 0) or 0)
                if letter_size <= 0:
                    i += 1
                    continue
                j = i + 1
                digits: list[dict[str, object]] = []
                while j < len(chars) and chars[j]["c"].isdigit():
                    dy = abs(float(chars[j]["bbox"][1]) - float(ch["bbox"][1]))
                    if dy > letter_size * 0.8:
                        break
                    digits.append(chars[j])
                    j += 1
                if 1 <= len(digits) <= 3:
                    digit_text = "".join(d["c"] for d in digits)
                    # Skip likely years (19xx, 20xx)
                    if len(digit_text) == 4 and digit_text.startswith(("19", "20")):
                        i = j
                        continue
                    # Skip if followed by closing bracket/parenthesis (likely citation/group label)
                    if j < len(chars) and chars[j]["c"] in ")】）］]}":
                        i = j
                        continue
                    # Skip if preceded by period or comma (likely citation, e.g., "et al., 2023")
                    if i > 0 and chars[i - 1]["c"] in ".，,":
                        i = j
                        continue
                    digit_rects = [fitz.Rect(d["bbox"]) for d in digits]
                    combined_digit_rect = union_rect(digit_rects)
                    digit_size = max(float(d.get("size", 0) or 0) for d in digits)
                    letter_center_y = (letter_rect.y0 + letter_rect.y1) / 2
                    digit_center_y = (combined_digit_rect.y0 + combined_digit_rect.y1) / 2
                    is_sub = (
                        digit_center_y > letter_center_y + letter_size * 0.05
                        and digit_size < letter_size * 0.9
                    )
                    if not is_sub:
                        gap = digit_rects[0].x0 - letter_rect.x1
                        if gap < letter_size * 1.5:
                            target_text = ch["c"] + digit_text
                            findings.append(
                                Finding(
                                    filename,
                                    page_no,
                                    f"auto:subscript:{page_no}:{i}",
                                    "公式/下标格式",
                                    f"字符级位置检查显示，{target_text} 中的数字未显示为下标。建议将数字改为下标格式。",
                                    severity="medium",
                                    source="char-position",
                                    fallback_rect=(
                                        combined_digit_rect.x0,
                                        combined_digit_rect.y0,
                                        combined_digit_rect.x1,
                                        combined_digit_rect.y1,
                                    ),
                                )
                            )
                i = j
            else:
                i += 1
    return findings


def detect_text_rules(filename: str, page_no: int, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if page_no == 1:
        front = text[:2400]
        if re.search(r"文献标识码：\s*(?:文章编号|中图分类号|\n)", front):
            add_text_finding(
                findings,
                filename,
                page_no,
                "文献标识码",
                "期刊元数据",
                "文献标识码疑似缺失。建议按期刊规范补充对应标识码。",
                "high",
            )
        # Structured abstract check: support full-width, half-width, and bold brackets
        abstract_labels = ["目的", "方法", "结果", "结论"]
        label_patterns = [f"[{label}]" for label in abstract_labels]
        label_patterns += [f"［{label}］" for label in abstract_labels]
        label_patterns += [f"【{label}】" for label in abstract_labels]
        label_patterns += [f"{label}" for label in abstract_labels]  # bold/plain text fallback
        found_labels = [p for p in label_patterns if p in front]
        # Only flag if this looks like a research article (not a review)
        review_keywords = ["综述", "进展", "展望", "review", "overview", "progress"]
        is_review = any(kw in front for kw in review_keywords)
        if not is_review and len(found_labels) < 3:
            missing_labels = [label for label in abstract_labels if not any(label in found for found in found_labels)]
            if missing_labels:
                add_text_finding(
                    findings,
                    filename,
                    page_no,
                    "摘",
                    "摘要结构",
                    f"结构式摘要未检出{''.join(missing_labels)}。建议核查摘要栏目是否完整（若本文为综述可忽略）。",
                    "medium",
                )

    text_targets = TEXT_TARGET_RULES
    for target, category, suggestion in text_targets:
        occurrence = 0
        start = 0
        while True:
            hit = text.find(target, start)
            if hit < 0:
                break
            add_text_finding(
                findings, filename, page_no, target, category, suggestion, occurrence=occurrence
            )
            occurrence += 1
            start = hit + len(target)

    _add_regex_findings(findings, filename, page_no, text, REGEX_RULES)

    lines = [line.strip() for line in text.splitlines() if compact(line)]
    for i in range(len(lines) - 1):
        if len(compact(lines[i])) >= 6 and compact(lines[i]) == compact(lines[i + 1]):
            add_text_finding(
                findings,
                filename,
                page_no,
                lines[i],
                "重复排版",
                "相邻两行重复出现同一内容。建议删除重复内容。",
                "high",
            )
            break

    return findings


def caption_items(page: fitz.Page, page_no: int, prefix: str) -> list[tuple[int, int, float, str, fitz.Rect | None]]:
    items: list[tuple[int, int, float, str, fitz.Rect | None]] = []
    for line in (page.get_text("text") or "").splitlines():
        stripped = line.strip()
        match = re.match(rf"^{prefix}\s*([0-9]+)\s+", stripped)
        if not match or len(stripped) > 80:
            continue
        num = int(match.group(1))
        rects = page.search_for(stripped[: min(len(stripped), 30)])
        rect = rects[0] if rects else None
        items.append((num, page_no, rect.y0 if rect else 99999, stripped, rect))
    return items


def detect_caption_order(doc: fitz.Document, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    for prefix, category in [("图", "图序/版式"), ("表", "表序/版式")]:
        caps: list[tuple[int, int, float, str, fitz.Rect | None]] = []
        for page_no, page in enumerate(doc, start=1):
            caps.extend(caption_items(page, page_no, prefix))
        caps.sort(key=lambda x: (x[1], x[2]))
        previous: tuple[int, int, float, str, fitz.Rect | None] | None = None
        for item in caps:
            if previous and item[0] < previous[0]:
                rect = item[4]
                findings.append(
                    Finding(
                        filename,
                        item[1],
                        f"auto:caption-order:{prefix}:{item[1]}:{item[0]}",
                        category,
                        f"坐标检查显示{prefix}{item[0]}编号相对前一处{prefix}{previous[0]}回退。建议核查图表题位置与正文引用顺序。",
                        severity="medium",
                        source="layout-coordinate",
                        fallback_rect=(rect.x0, rect.y0, rect.x1, rect.y1) if rect else None,
                    )
                )
            previous = item
    return findings


def detect_reference_sequence(doc: fitz.Document, filename: str) -> list[Finding]:
    refs: list[tuple[int, int, str]] = []
    in_ref_section = False
    for page_no, page in enumerate(doc, start=1):
        for line in (page.get_text("text") or "").splitlines():
            stripped = line.strip()
            if re.match(r"^参考文献\s*$", stripped):
                in_ref_section = True
                continue
            if not in_ref_section:
                continue
            # Support full-width ［1］, half-width [1], and parentheses (1)
            match = re.match(r"^[\[［(]([0-9]+)[\]］)]", stripped)
            if match:
                refs.append((int(match.group(1)), page_no, stripped))
    if len(refs) < 2:
        return []
    nums = [item[0] for item in refs]
    duplicates = len(nums) != len(set(nums))
    continuous = nums == list(range(nums[0], nums[-1] + 1))
    if continuous and not duplicates:
        return []
    first = refs[0]
    issues: list[str] = []
    if duplicates:
        issues.append("重复")
    if not continuous:
        issues.append("跳号或不连续")
    return [
        Finding(
            filename,
            first[1],
            first[2][:20],
            "参考文献编号",
            f"参考文献编号可能存在{'、'.join(issues)}。建议按正文引用顺序核对编号连续性。",
            severity="high",
            source="reference-sequence",
        )
    ]


def detect_figure_table_citation_order(doc: fitz.Document, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    for prefix, label in [("图", "图"), ("表", "表")]:
        cites: list[tuple[int, int]] = []
        range_covered: set[int] = set()
        for page_no, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            # Detect range citations like "图1—5" or "图2、3、4" and mark them as covered
            for rmatch in re.finditer(rf"{prefix}\s*([0-9]+)\s*[—~\-～]\s*([0-9]+)", text):
                start_n, end_n = int(rmatch.group(1)), int(rmatch.group(2))
                range_covered.update(range(start_n, end_n + 1))
            for match in re.finditer(rf"{prefix}\s*([0-9]+)", text):
                num = int(match.group(1))
                cites.append((page_no, num))
        if len(cites) < 2:
            continue
        seen: set[int] = set()
        first_cites: list[tuple[int, int]] = []
        for page_no, num in cites:
            if num not in seen:
                seen.add(num)
                first_cites.append((page_no, num))
        if len(first_cites) >= 2:
            nums = [n for _, n in first_cites]
            expected = list(range(min(nums), max(nums) + 1))
            missing = [n for n in expected if n not in nums and n not in range_covered]
            if missing:
                findings.append(
                    Finding(
                        filename,
                        first_cites[0][0],
                        f"auto:{label}-citation-order",
                        f"{label}序/版式",
                        f"正文首次引用的{label}编号不连续，缺少{label}{missing}。建议核查{label}顺序与正文引用是否一致。",
                        severity="medium",
                        source="text-rule",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# P2 detectors: Latin names, formula annotations, numeral style
# ---------------------------------------------------------------------------

# Pattern for Latin scientific binomials: "Genus species" or "G. species"
_LATIN_BINOMIAL_RE = re.compile(
    r"\b([A-Z][a-zàâäèéêëîïôöùûüÿçœ]+)\s+([a-zàâäèéêëîïôöùûüÿçœ]{3,})\b"
)
_LATIN_ABBREV_RE = re.compile(
    r"\b([A-Z])\.\s*([a-zàâäèéêëîïôöùûüÿçœ]{3,})\b"
)
# Common Chinese biological indicators for proximity detection
_BIO_SUFFIXES = re.compile(
    r"(?:树|草|花|藤|竹|灌|藻|菌|霉|虫|鱼|鸟|鼠|蛇|蛙|螺|贝"
    r"|小麦|玉米|水稻|大豆|棉花|油菜|马铃薯|番茄|烟草|拟南芥"
    r"|线虫|果蝇|斑马鱼|小鼠|大鼠|家蚕|蜜蜂|蚕豆|苜蓿|杨树|松树"
    r"|栎树|柳树|桦树|云杉|冷杉|落叶松|柏树|杉木|竹子|甘蔗|高粱"
    r"|谷子|糜子|荞麦|燕麦|大麦|黑麦|花生|芝麻|向日葵|甜菜)"
)


def detect_latin_name_first_mention(doc: fitz.Document, filename: str) -> list[Finding]:
    """Detect Latin scientific binomials and flag potential missing first-mention introductions.

    For each unique Latin binomial, records its first occurrence page and nearby Chinese
    context. Reports a mapping that helps the AI verify first-mention compliance.

    This is an assistive detector — it surfaces information; the AI makes the final call.
    """
    findings: list[Finding] = []
    latin_occurrences: dict[str, list[tuple[int, str]]] = {}  # "Genus species" -> [(page, context)]

    for page_no, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""

        for match in _LATIN_BINOMIAL_RE.finditer(text):
            genus, species = match.group(1), match.group(2)
            # Skip common false positives: abbreviations, units, statistical terms
            if genus in ("Table", "Figure", "Fig", "Equation", "Model", "Group", "Treatment"):
                continue
            if species in ("the", "and", "for", "was", "with", "from", "that", "this", "were"):
                continue
            full_name = f"{genus} {species}"
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            context = text[start:end].replace("\n", " ")
            if full_name not in latin_occurrences:
                latin_occurrences[full_name] = []
            latin_occurrences[full_name].append((page_no, context))

    # Report each unique Latin binomial's first occurrence for AI cross-reference
    for name, occurrences in sorted(latin_occurrences.items()):
        first_page = occurrences[0][0]
        ctx = occurrences[0][1][:120]
        # Check if Chinese bio name is nearby on first occurrence
        has_chinese_nearby = bool(_BIO_SUFFIXES.search(ctx))
        findings.append(Finding(
            file=filename,
            page=first_page,
            target=name,
            category="latin-name",
            suggestion=(
                f"拉丁学名 '{name}' 首次出现在第{first_page}页。"
                + ("附近检出中文物种名，请核实是否已在首次提及处标注拉丁学名。"
                   if has_chinese_nearby else
                   "请核实该学名在正文中首次提及时是否已给出中文名称及拉丁学名。")
            ),
            severity="medium",
            source="rule",
        ))

    return findings


def detect_formula_annotation(doc: fitz.Document, filename: str) -> list[Finding]:
    """Check that formulas followed by '式中：' have all variables annotated with units.

    Scans for the pattern: formula block → '式中：' → variable list.
    Flags cases where '式中：' is present but variable annotations appear incomplete.
    """
    findings: list[Finding] = []
    formula_keywords = re.compile(r"(式中|其中|这里)[：:]")

    for page_no, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""

        for match in formula_keywords.finditer(text):
            keyword = match.group(1)
            start = match.end()
            # Look at the next ~300 chars for variable annotations
            snippet = text[start:start + 300]
            # Count variable-annotation patterns: "X 为/是/表示" or "X——"
            var_patterns = re.findall(
                r"[A-Za-zα-ωβγδεζηθικλμνξπρστυφχψω][′'*]?\s*(?:为|是|表示|——|—|，|,)",
                snippet,
            )
            # Check for units in parentheses after variables
            unit_patterns = re.findall(
                r"[）\)]\s*[，,;；]|\)\s*为|\)\s*表示|[）\)]\s*$",
                snippet,
            )

            if len(var_patterns) == 0:
                # '式中：' present but no variable annotations detected
                if keyword == "式中":
                    findings.append(Finding(
                        file=filename,
                        page=page_no,
                        target=match.group(0),
                        category="formula",
                        suggestion=(
                            "检出'式中：'但未识别到后续变量注解。"
                            "请核查公式后是否按规范以'式中：'开头逐项注解变量，"
                            "并在括号内注明单位。"
                        ),
                        severity="medium",
                        source="rule",
                    ))
            elif len(unit_patterns) < len(var_patterns) * 0.5:
                # Some variables may lack unit annotations
                findings.append(Finding(
                    file=filename,
                    page=page_no,
                    target=match.group(0),
                    category="formula",
                    suggestion=(
                        f"公式注解区域检出{len(var_patterns)}个疑似变量，"
                        f"但仅{len(unit_patterns)}处疑似单位括号。"
                        "请核查每个变量是否均按规范注明了单位。"
                    ),
                    severity="low",
                    source="rule",
                ))

    return findings


def detect_numeral_style(doc: fitz.Document, filename: str) -> list[Finding]:
    """Check GB/T 15835 numeral style: consistent use of Arabic vs Chinese numerals.

    Flags:
    - Chinese numerals in technical contexts where Arabic is expected
    - Mixed date formats (e.g., '2025年3月' vs '2025-03' in the same document)
    - Range connectors inconsistency (～ vs — vs -)
    """
    findings: list[Finding] = []
    all_text_parts: list[str] = []

    for page_no, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        all_text_parts.append(text)

        # Flag Chinese numerals used where Arabic is expected in technical contexts
        # Pattern: "表X" or "图X" where X is a Chinese numeral
        chinese_fig_table = re.findall(r"([图表])[一二三四五六七八九十]{1,3}(?!\d)", text)
        if chinese_fig_table:
            findings.append(Finding(
                file=filename,
                page=page_no,
                target=chinese_fig_table[0][0] + chinese_fig_table[0][1],
                category="numeral-style",
                suggestion=(
                    f"检出中文数字用于图表编号（'{chinese_fig_table[0][0]}{chinese_fig_table[0][1]}'）。"
                    "GB/T 15835建议技术文献中图表编号使用阿拉伯数字。"
                ),
                severity="low",
                source="rule",
            ))

        # Range connector check: detect mixed usage of ~, —, -
        ranges = re.findall(r"\d+\s*([～~—\-])\s*\d+", text)
        connectors = set(connector for connector in ranges)
        if len(connectors) >= 2:
            findings.append(Finding(
                file=filename,
                page=page_no,
                target="range-connector",
                category="numeral-style",
                suggestion=(
                    f"同一页检出不统一的数值范围连接符：{connectors}。"
                    "GB/T 15835建议全文中范围连接符保持一致。"
                ),
                severity="low",
                source="rule",
            ))

    # Cross-page: check date format consistency across the document
    full_text = "\n".join(all_text_parts)
    date_formats = []
    if re.search(r"\d{4}\s*年\s*\d{1,2}\s*月", full_text):
        date_formats.append("YYYY年MM月")
    if re.search(r"\d{4}-\d{2}-\d{2}", full_text):
        date_formats.append("YYYY-MM-DD")
    if re.search(r"\d{4}/\d{2}/\d{2}", full_text):
        date_formats.append("YYYY/MM/DD")
    if re.search(r"\d{4}\.\d{2}\.\d{2}", full_text):
        date_formats.append("YYYY.MM.DD")

    if len(date_formats) >= 2:
        findings.append(Finding(
            file=filename,
            page=1,
            target="date-format",
            category="numeral-style",
            suggestion=(
                f"全文中检出不统一的日期格式：{', '.join(date_formats)}。"
                "建议统一为一种格式（推荐'YYYY年MM月DD日'或'YYYY-MM-DD'）。"
            ),
            severity="low",
            source="rule",
        ))

    return findings


# ---------------------------------------------------------------------------
# Prepare phase: extract + rules + review context
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Prepare phase: extract + rules + review context
# ---------------------------------------------------------------------------
def prepare_document(pdf: Path, output_dir: Path, render_dpi: int = 200) -> dict[str, object]:
    artifact_dir = output_dir / "_artifacts"
    candidate_dir = output_dir / "_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, object] = {
        "file": str(pdf),
        "status": "skipped",
        "reason": "",
        "pages": 0,
        "candidate_count": 0,
        "candidate_json": "",
        "artifact_dir": "",
    }

    try:
        doc = fitz.open(pdf)
    except Exception as exc:
        result["reason"] = f"open failed: {exc}"
        return result

    try:
        result["pages"] = doc.page_count
        paper_dir = write_text_artifacts(doc, pdf, artifact_dir)

        # High-quality page rendering
        image_dir = paper_dir / "pages"
        image_dir.mkdir(exist_ok=True)
        scale = render_dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        for page_no, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(image_dir / f"page_{page_no:03d}.png")

        # Run all rule-based detectors
        findings: list[Finding] = []
        findings.extend(detect_stat_symbol_style(doc, pdf.name))
        findings.extend(detect_script_style(doc, pdf.name))
        findings.extend(detect_caption_order(doc, pdf.name))
        findings.extend(detect_reference_sequence(doc, pdf.name))
        findings.extend(detect_figure_table_citation_order(doc, pdf.name))
        findings.extend(detect_latin_name_first_mention(doc, pdf.name))
        findings.extend(detect_formula_annotation(doc, pdf.name))
        findings.extend(detect_numeral_style(doc, pdf.name))
        for page_no, page in enumerate(doc, start=1):
            findings.extend(detect_text_rules(pdf.name, page_no, extract_page_text(page)))

        findings = dedupe_findings(findings)

        # Write initial findings JSON
        candidate_path = candidate_dir / f"{pdf.stem}.findings.json"
        candidate_path.write_text(
            json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Build review_context.md
        review_context = _build_review_context(pdf, doc, paper_dir, findings)
        review_path = paper_dir / "review_context.md"
        review_path.write_text(review_context, encoding="utf-8")

        result.update({
            "status": "done",
            "candidate_count": len(findings),
            "candidate_json": str(candidate_path),
            "artifact_dir": str(paper_dir),
            "review_context": str(review_path),
        })
        return result
    except Exception as exc:
        result["reason"] = f"prepare failed: {exc}"
        return result
    finally:
        doc.close()


def _build_review_context(pdf: Path, doc: fitz.Document, paper_dir: Path, findings: list[Finding]) -> str:
    """Build a unified review context document for AI editorial review."""
    parts: list[str] = []

    parts.append(f"# Review Context: {pdf.name}")
    parts.append(f"- Pages: {doc.page_count}")
    parts.append("")

    # Read fulltext.md
    fulltext_md_path = paper_dir / "fulltext.md"
    if fulltext_md_path.exists():
        fulltext = fulltext_md_path.read_text(encoding="utf-8")
        parts.append("# Full Text (with markup)\n")
        parts.append(fulltext)
        parts.append("")

    # Auto-detected rule findings
    parts.append("# Auto-Detected Rule Findings\n")
    if findings:
        parts.append(f"Total: {len(findings)} findings\n")
        by_category: dict[str, list[Finding]] = {}
        for f in findings:
            by_category.setdefault(f.category, []).append(f)
        for category, items in sorted(by_category.items()):
            parts.append(f"## {category}\n")
            for item in items:
                parts.append(f"- **Page {item.page}**: {item.suggestion}")
                if item.target and not item.target.startswith("auto:"):
                    parts.append(f"  - Target: `{item.target}`")
                if item.fallback_rect:
                    parts.append(f"  - Rect: {item.fallback_rect}")
            parts.append("")
    else:
        parts.append("No rule-based findings detected.\n")

    # Pages needing visual inspection — track reason per page
    visual_pages: dict[int, list[str]] = {}  # page_no -> list of reasons
    for page_no, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""

        # Keyword-based detection
        page_kws = [kw for kw in ("图", "表", "公式", "Fig.", "Table", "Equation", "式中") if kw in text]
        if page_kws:
            visual_pages.setdefault(page_no, []).append(f"keyword: {', '.join(page_kws)}")

        # Structural detection: pages with embedded images (catches pure-graphic pages
        # that have no extractable text matching keywords)
        images = page.get_images(full=True)
        if images:
            visual_pages.setdefault(page_no, []).append(
                f"embedded images: {len(images)} image object(s)"
            )

        # Findings with coordinate data on this page
        for f in findings:
            if f.page == page_no and f.fallback_rect:
                visual_pages.setdefault(page_no, []).append(
                    f"finding[{f.category}]: {f.suggestion[:80]}"
                )

    parts.append("# Pages Requiring Visual Inspection\n")
    if visual_pages:
        parts.append("Open each PNG and cross-check against extracted text findings:")
        parts.append("")
        for p in sorted(visual_pages):
            reasons = "; ".join(visual_pages[p])
            parts.append(f"- Page {p}: `pages/page_{p:03d}.png`  — {reasons}")
        parts.append("")
        parts.append("**How to inspect each page:**")
        parts.append("- Formulas: check italic vs upright, subscript position/size, OMath/MathType artifacts (broken baselines, overlapping components, missing glyphs)")
        parts.append("- Figures: caption below figure, bilingual match, axis labels+units readable, legend present, data lines distinguishable, no watermark/overlap/placeholder, map has 审图号")
        parts.append("- Tables: caption above table, three-line table format, header units in negative exponent form, zero=\"0\" and unmeasured=\"—\"")
        parts.append("- Layout: no cropped content, no unexpected blank pages, header/footer consistency")
        parts.append("")
        parts.append("**Cross-check rule**: If extracted text suggests an issue (e.g., subscript error, italic missing) but the PNG shows correct visual rendering, DISMISS the finding. Extraction artifacts do NOT count as errors.")
        parts.append("")
        parts.append("After visual inspection, record in a `_visual_review` section of your compiled findings JSON:")
        parts.append("- `visual_pages_checked`: number of pages you actually opened and inspected")
        parts.append("- `visual_dismissed`: list of finding IDs you dismissed because visual rendering was correct")
        parts.append("- `visual_new`: list of new issues discovered only through visual inspection (if any)")
    else:
        parts.append("No specific pages flagged for visual inspection.\n")

    parts.append("")
    parts.append("# Review Instructions")
    parts.append("1. Read the full text above sentence by sentence.")
    parts.append("2. Check front matter: title, authors, abstract structure, keywords, CLC, DOI, funding.")
    parts.append("3. Check text and logic: repeated phrasing, dangling referents, conclusion/data mismatch, term consistency.")
    parts.append("4. Check punctuation: no full-width colons in URLs, correct comma/period usage, consistent parentheses.")
    parts.append("5. Check numerals and units: consistent spacing, correct range connectors, unbroken statistical expressions.")
    parts.append("6. Check formulas and symbols: italic variables, upright operators/units, correct subscripts/superscripts.")
    parts.append("7. Open each visual inspection page PNG to verify figures, tables, and formula layout.")
    parts.append("8. Check references: GB/T 7714 format, volume/issue completeness, citation-reference consistency, bilingual refs.")
    parts.append("9. Cross-check auto-detected findings above; confirm or dismiss each one.")
    parts.append("10. For every confirmed issue, produce a finding with: page, target text, category, severity, suggestion.")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Annotation phase
# ---------------------------------------------------------------------------
_HALF_WIDTH_TRANS = str.maketrans({
    "，": ",", "。": ".", "：": ":", "；": ";",
    "（": "(", "）": ")", "［": "[", "］": "]",
    "【": "[", "】": "]", "、": ",", "！": "!",
    "？": "?", "“": '"', "”": '"', "‘": "'", "’": "'",
    "′": "'", "″": '"', "—": "-", "–": "-",
})


def _to_halfwidth(s: str) -> str:
    return s.translate(_HALF_WIDTH_TRANS)


def _extract_search_keys(target: str) -> list[str]:
    if target.startswith("auto:"):
        target = target.split(":", 2)[-1] if target.count(":") >= 2 else target
    keys: list[str] = []
    if len(target) <= 30:
        keys.append(target)
    core = target.strip("（）()[]［］\"'\"'")
    if core and core != target and len(core) <= 30:
        keys.append(core)
    parts = re.split(r"[，。：；、！？\s\(\)\[\]（）［］]", target)
    for p in sorted(parts, key=len, reverse=True):
        if len(p) >= 4 and p not in keys:
            keys.append(p)
            if len(keys) >= 5:
                break
    if len(target) > 6:
        keys.append(target[:8])
        keys.append(target[-8:])
    return keys[:5]


def find_rect(page: fitz.Page, finding: Finding) -> fitz.Rect | None:
    if finding.target.startswith("auto:") and finding.fallback_rect:
        return fitz.Rect(finding.fallback_rect)
    base = finding.target
    variants: list[str] = [
        base,
        base.replace("\n", " "),
        base.replace("\n", ""),
        " ".join(base.split()),
        _to_halfwidth(base),
        _to_halfwidth(base.replace("\n", " ")),
        _to_halfwidth(" ".join(base.split())),
    ]
    for query in variants:
        if not query:
            continue
        rects = page.search_for(query, quads=False)
        if rects:
            return fitz.Rect(rects[min(finding.occurrence, len(rects) - 1)])

    keys = _extract_search_keys(base)
    for key in keys:
        if not key or len(key) < 3:
            continue
        rects = page.search_for(key, quads=False)
        if rects:
            return fitz.Rect(rects[min(finding.occurrence, len(rects) - 1)])

    if finding.fallback_rect:
        return fitz.Rect(finding.fallback_rect)
    return None


def add_annotation(page: fitz.Page, finding: Finding) -> bool:
    rect = find_rect(page, finding)
    if rect is None:
        return False
    mark = fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2)
    annot = page.add_rect_annot(mark)
    annot.set_colors(stroke=(1, 0, 0))
    annot.set_border(width=1.2)
    annot.set_info(content=f"{finding.category}：{finding.suggestion}")
    annot.update()
    return True


def count_annotations(doc: fitz.Document) -> dict[str, int]:
    counts: dict[str, int] = {}
    for page in doc:
        for annot in page.annots() or []:
            name = annot.type[1]
            counts[name] = counts.get(name, 0) + 1
    return counts


_CJK_FONTS = ("china-ss", "hebo", "cjk", "helv")


def _insert_cjk_text(page: fitz.Page, point: tuple[float, float], text: str, **kwargs) -> None:
    for font in _CJK_FONTS:
        try:
            page.insert_text(point, text, fontname=font, **kwargs)
            return
        except Exception:
            continue


def _add_end_of_doc_summary(doc: fitz.Document, findings: list[Finding]) -> int:
    if not findings:
        return 0
    page_width = doc[0].rect.width
    page_height = doc[0].rect.height
    page = doc.new_page(-1, width=page_width, height=page_height)
    y = 50
    count = 0

    title = "未定位批注汇总（以下问题未能在原文中找到精确位置，请手动核查）"
    _insert_cjk_text(page, (50, y), title, fontsize=14, color=(1, 0, 0))
    y += 35

    for f in findings:
        line1 = f"{count + 1}. [{f.category}] 第{f.page}页"
        line2 = f"   问题：{f.suggestion[:180]}"
        lines = [line1, line2]
        block_height = len(lines) * 18 + 8
        if y + block_height > page_height - 40:
            page = doc.new_page(-1, width=page_width, height=page_height)
            y = 50
        for line in lines:
            _insert_cjk_text(page, (50, y), line, fontsize=10, color=(0, 0, 0))
            y += 18
        rect = fitz.Rect(45, max(0, y - block_height + 2), page_width - 45, y)
        annot = page.add_rect_annot(rect)
        annot.set_colors(stroke=(1, 0, 0))
        annot.set_border(width=1.2)
        annot.set_info(content=f"{f.category}：{f.suggestion}")
        annot.update()
        y += 10
        count += 1
    return count


def load_findings(path: Path) -> tuple[list[Finding], dict[str, object]]:
    """Load reviewed findings JSON.

    Returns (findings, visual_review_meta).
    Handles both old flat-list format and new wrapped format with _visual_review.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    visual_meta: dict[str, object] = {}

    if isinstance(data, dict) and "findings" in data:
        # New wrapped format: {"_visual_review": {...}, "findings": [...]}
        visual_meta = data.get("_visual_review", {}) or {}
        items = data["findings"]
    elif isinstance(data, list):
        # Old flat-list format
        items = data
    else:
        items = []

    findings: list[Finding] = []
    for item in items:
        rect = item.get("fallback_rect")
        findings.append(
            Finding(
                file=item["file"],
                page=int(item["page"]),
                target=item["target"],
                category=item["category"],
                suggestion=item["suggestion"],
                severity=item.get("severity", "medium"),
                source=item.get("source", "reviewed"),
                occurrence=int(item.get("occurrence", 0)),
                fallback_rect=tuple(rect) if rect else None,
                end_of_doc=bool(item.get("end_of_doc", False)),
            )
        )
    return findings, visual_meta


# Categories whose findings MUST be visually confirmed against rendered PNGs.
_VISUAL_CATEGORIES = frozenset({
    "stat-symbol", "subscript", "formula", "figure", "table",
    "font-style", "script",
})


def validate_reviewed_findings(
    path: Path,
    findings: list[Finding],
    visual_meta: dict[str, object],
    page_count: int = 0,
) -> tuple[list[str], list[str]]:
    """Validate reviewed findings before annotation.

    Returns (errors, warnings).
    - errors: must-fix issues — annotation should abort in strict mode.
    - warnings: suspicious patterns — print but don't block.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Visual review metadata checks ---

    if not visual_meta:
        errors.append(
            "MISSING _visual_review: no visual review metadata found. "
            "Step 4 (Visual Inspection) and Step 5 (Cross-Check) were likely skipped."
        )
    else:
        pages_checked = visual_meta.get("pages_checked", [])
        if not pages_checked:
            errors.append(
                "EMPTY pages_checked: no page PNGs were reported as inspected. "
                "Visual review was not performed."
            )

        dismissed = visual_meta.get("dismissed", [])
        visual_findings = [f for f in findings if f.category in _VISUAL_CATEGORIES]
        if visual_findings and not dismissed:
            warnings.append(
                f"ZERO dismissed: {len(visual_findings)} visual-category findings, none dismissed. "
                "Rule detectors nearly always produce some false positives — verify Step 5 was performed."
            )

    # --- Finding reasonability checks ---

    valid_severities = frozenset({"high", "medium", "low"})
    targets_seen: set[tuple[int, str]] = set()
    empty_target_count = 0
    empty_suggestion_count = 0
    bad_page_count = 0
    bad_severity_count = 0
    duplicate_count = 0
    gibberish_count = 0

    for f in findings:
        # Empty target
        if not f.target or not f.target.strip():
            empty_target_count += 1
            continue
        # Empty suggestion
        if not f.suggestion or not f.suggestion.strip():
            empty_suggestion_count += 1
        # Page bounds (0 = check skipped)
        if page_count > 0 and (f.page < 1 or f.page > page_count):
            bad_page_count += 1
        # Valid severity
        if f.severity not in valid_severities:
            bad_severity_count += 1
        # Duplicate target on same page
        key = (f.page, f.target.strip())
        if key in targets_seen:
            duplicate_count += 1
        else:
            targets_seen.add(key)
        # Gibberish target (random keystrokes, very unlikely in real text)
        t = f.target.strip()
        if len(t) >= 8 and not any(ord(c) > 127 for c in t):
            # Pure ASCII target >= 8 chars: check for improbably random strings
            if re.search(r"[bcdfghjklmnpqrstvwxyz]{6,}", t, re.IGNORECASE):
                gibberish_count += 1

    if empty_target_count:
        errors.append(f"EMPTY target: {empty_target_count} finding(s) have no target text.")
    if empty_suggestion_count:
        errors.append(f"EMPTY suggestion: {empty_suggestion_count} finding(s) have no suggestion.")
    if bad_page_count:
        errors.append(
            f"PAGE OUT OF BOUNDS: {bad_page_count} finding(s) reference pages "
            f"outside the document's 1–{page_count} range."
        )
    if bad_severity_count:
        warnings.append(
            f"INVALID severity: {bad_severity_count} finding(s) use non-standard severity "
            f"(expected high/medium/low)."
        )
    if duplicate_count:
        warnings.append(
            f"DUPLICATE targets: {duplicate_count} finding(s) have the same (page, target) as another."
        )
    if gibberish_count:
        errors.append(
            f"GIBBERISH target: {gibberish_count} finding(s) have implausible ASCII target text "
            f"(probable AI hallucination)."
        )

    # --- Visual-category findings missing visual_confirmed ---
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("findings", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            unchecked: list[str] = []
            for item in items:
                cat = item.get("category", "")
                if cat in _VISUAL_CATEGORIES and "visual_confirmed" not in item:
                    unchecked.append(
                        f"page {item.get('page', '?')} [{cat}]: {item.get('suggestion', '')[:60]}"
                    )
            if unchecked:
                warnings.append(
                    f"MISSING visual_confirmed on {len(unchecked)} visual-category finding(s): "
                    + "; ".join(unchecked[:5])
                    + (f" ... and {len(unchecked) - 5} more" if len(unchecked) > 5 else "")
                )
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # --- Count anomaly detection ---
    if page_count > 0 and findings:
        pages_with_findings: dict[int, int] = {}
        for f in findings:
            pages_with_findings[f.page] = pages_with_findings.get(f.page, 0) + 1
        if pages_with_findings:
            max_per_page = max(pages_with_findings.values())
            avg_per_page = len(findings) / page_count
            if max_per_page > avg_per_page * 5 and max_per_page >= 10:
                burst_page = max(pages_with_findings, key=pages_with_findings.get)
                warnings.append(
                    f"BURST anomaly: page {burst_page} has {max_per_page} findings "
                    f"(avg {avg_per_page:.1f}/page). Possible AI focus drift."
                )

        high_count = sum(1 for f in findings if f.severity == "high")
        if high_count > len(findings) * 0.5 and len(findings) >= 5:
            warnings.append(
                f"SEVERITY inflation: {high_count}/{len(findings)} findings are 'high' severity "
                f"({100*high_count//len(findings)}%). Verify these are genuinely high-severity."
            )

    return errors, warnings


def annotate_pdf(pdf: Path, output_dir: Path, findings: list[Finding], same_name: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "file": str(pdf),
        "status": "skipped",
        "reason": "",
        "pages": 0,
        "findings_configured": len(findings),
        "findings_annotated": 0,
        "missed": [],
        "output": "",
        "annotation_types": {},
        "render_verified": False,
    }
    try:
        doc = fitz.open(pdf)
    except Exception as exc:
        result["reason"] = f"open failed: {exc}"
        return result
    try:
        result["pages"] = doc.page_count
        annotated = 0
        missed: list[dict[str, object]] = []
        end_doc_findings: list[Finding] = []
        for finding in findings:
            if Path(finding.file).name != pdf.name:
                continue
            if finding.end_of_doc:
                end_doc_findings.append(finding)
                continue

            annotated_success = False
            for attempt_page in (finding.page, finding.page - 1, finding.page + 1):
                if 1 <= attempt_page <= doc.page_count:
                    if add_annotation(doc[attempt_page - 1], finding):
                        annotated_success = True
                        break

            if annotated_success:
                annotated += 1
            else:
                if finding.page < 1 or finding.page > doc.page_count:
                    missed.append(asdict(finding) | {"reason": "page out of range"})
                else:
                    missed.append(asdict(finding) | {"reason": "target not found"})

        if end_doc_findings:
            annotated += _add_end_of_doc_summary(doc, end_doc_findings)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_name = pdf.name if same_name else f"{pdf.stem}_annotated.pdf"
        out_path = output_dir / out_name
        tmp_path = output_dir / f".{pdf.stem}.tmp.pdf"
        if tmp_path.exists():
            tmp_path.unlink()
        doc.save(tmp_path, garbage=4, deflate=True)
        os.replace(tmp_path, out_path)
        result.update({"status": "done", "findings_annotated": annotated, "missed": missed, "output": str(out_path)})
    except Exception as exc:
        result["reason"] = f"annotate failed: {exc}"
        return result
    finally:
        doc.close()

    try:
        verify = fitz.open(result["output"])
        try:
            for page in verify:
                pix = page.get_pixmap(matrix=fitz.Matrix(0.12, 0.12), alpha=False, annots=True)
                if pix.width <= 0 or pix.height <= 0:
                    raise RuntimeError("empty render")
            result["annotation_types"] = count_annotations(verify)
            result["render_verified"] = True
        finally:
            verify.close()
    except Exception as exc:
        result["status"] = "done_with_verify_error"
        result["reason"] = f"verify failed: {exc}"
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def append_log(output_dir: Path, entries: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "batch_proofread_log.json"
    prior: list[dict[str, object]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                prior = loaded
        except Exception:
            prior = []
    replaced = {Path(str(item.get("file", ""))).name for item in entries}
    prior = [item for item in prior if Path(str(item.get("file", ""))).name not in replaced]
    prior.extend(entries)
    path.write_text(json.dumps(prior, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def resolve_output(root: Path, output: Path | None) -> Path:
    return output.resolve() if output else (root / "annotated_pdfs").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="High-precision PDF proofreading pipeline for Chinese academic journals.",
    )
    parser.add_argument("--root", type=Path, help="Folder containing source PDFs. Optional when --file is given.")
    parser.add_argument("--file", type=Path, help="Process a single specific PDF file instead of scanning a folder.")
    parser.add_argument("--output", type=Path, help="Output folder. Defaults to ROOT/annotated_pdfs.")
    parser.add_argument("--mode", choices=["prepare", "annotate"], default="prepare",
                        help="prepare: extract text, render pages, run rule checks. "
                             "annotate: apply reviewed findings to PDF.")
    parser.add_argument("--findings-json", type=Path, help="Reviewed findings JSON for annotate mode.")
    parser.add_argument("--same-name", action="store_true", help="Keep output PDF filenames unchanged.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum PDFs to process; 0 means all.")
    parser.add_argument("--render-dpi", type=int, default=200, help="DPI for page PNG rendering.")
    parser.add_argument("--force", action="store_true", help="Annotate even if validation finds errors.")
    parser.add_argument("--verbose", action="store_true", help="Print full JSON results.")
    args = parser.parse_args()

    if args.render_dpi < 100:
        print("Warning: render-dpi below 100 may reduce visual inspection quality. Using 100.", file=sys.stderr)
        args.render_dpi = 100

    if args.file:
        pdfs = [args.file.resolve()]
        root = args.file.resolve().parent
        output_dir = resolve_output(root, args.output)
    else:
        if not args.root:
            raise SystemExit("Either --root or --file is required.")
        root = args.root.resolve()
        output_dir = resolve_output(root, args.output)
        pdfs = pdfs_under(root, output_dir)
        if args.limit > 0:
            pdfs = pdfs[: args.limit]

    results: list[dict[str, object]] = []
    if args.mode == "prepare":
        for pdf in pdfs:
            item = prepare_document(pdf, output_dir, render_dpi=args.render_dpi)
            results.append(item)
            print(json.dumps({
                "phase": "prepare",
                "file": pdf.name,
                "status": item["status"],
                "pages": item.get("pages", 0),
                "candidates": item.get("candidate_count", 0),
                "review_context": item.get("review_context", ""),
            }, ensure_ascii=False))

    if args.mode == "annotate":
        if args.findings_json:
            findings, visual_meta = load_findings(args.findings_json)

            # Determine page count from first PDF for reasonability checks
            _page_count = 0
            if pdfs:
                try:
                    _doc = fitz.open(pdfs[0])
                    _page_count = _doc.page_count
                    _doc.close()
                except Exception:
                    pass

            errors, warnings = validate_reviewed_findings(
                args.findings_json, findings, visual_meta, page_count=_page_count,
            )
            if errors or warnings:
                print("\n=== FINDINGS VALIDATION ===", file=sys.stderr)
                for e in errors:
                    print(f"  ERROR: {e}", file=sys.stderr)
                for w in warnings:
                    print(f"  WARNING: {w}", file=sys.stderr)
                print("", file=sys.stderr)

            if errors and not args.force:
                raise SystemExit(
                    "Validation found errors. Annotation aborted.\n"
                    "  Re-run with --force to bypass (not recommended).\n"
                    "  Or fix the findings JSON and try again."
                )
        else:
            raise SystemExit("--findings-json is required in annotate mode")

        annotate_results = []
        for pdf in pdfs:
            item = annotate_pdf(pdf, output_dir, findings, same_name=args.same_name)
            annotate_results.append(item)
            print(json.dumps({
                "phase": "annotate",
                "file": pdf.name,
                "status": item["status"],
                "annotations": item.get("findings_annotated", 0),
                "missed": len(item.get("missed", [])),
            }, ensure_ascii=False))
        append_log(output_dir, annotate_results)
        results = annotate_results

    if args.verbose:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({
            "root": str(root),
            "output": str(output_dir),
            "mode": args.mode,
            "pdfs": len(pdfs),
            "done": sum(1 for item in results if str(item.get("status", "")).startswith("done")),
            "skipped": sum(1 for item in results if item.get("status") == "skipped"),
            "total_annotations": sum(int(item.get("findings_annotated", 0) or 0) for item in results),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
