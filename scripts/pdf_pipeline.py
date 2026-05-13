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

    # Tag each char
    tagged: list[tuple[str, str]] = []  # (tag, char)
    for ci in char_infos:
        c = ci["c"]
        size = ci["size"]
        y = ci["bbox"][1]
        dy = y - baseline
        tag = ""
        if size > 0 and base_size > 0:
            if size < base_size * 0.85 and dy < -base_size * 0.1:
                tag = "sup"
            elif size < base_size * 0.85 and dy > base_size * 0.05:
                tag = "sub"
        if _is_italic_span(span) and not tag:
            tag = "i"
        tagged.append((tag, c))

    # Merge consecutive same tags
    result_parts: list[str] = []
    current_tag = ""
    current_chars: list[str] = []

    def flush():
        if not current_chars:
            return
        s = "".join(current_chars)
        if current_tag:
            result_parts.append(f"<{current_tag}>{s}</{current_tag}>")
        else:
            result_parts.append(s)

    for tag, c in tagged:
        if tag != current_tag:
            flush()
            current_tag = tag
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


def _classify_blocks(blocks: list[tuple]) -> tuple[list[tuple], list[tuple], list[tuple]]:
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
    paragraphs = [b[4] for b in sorted_blocks if b[4].strip()]

    if not paragraphs:
        return ""

    md = f"\n[[PAGE={page_no}]]\n\n"
    md += "\n\n".join(paragraphs)
    return md


def extract_page_text(page: fitz.Page) -> str:
    """Plain text extraction with dual-column awareness."""
    blocks = page.get_text("blocks")
    if not blocks:
        return page.get_text("text") or ""

    page_width = page.rect.width
    mid = page_width / 2

    left: list[tuple] = []
    right: list[tuple] = []
    full: list[tuple] = []

    for b in blocks:
        x0, y0, x1, y1, text, *_ = b
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

    def _vertical_coverage(blocks: list[tuple]) -> float:
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
        ph = page.rect.height
        return total / ph if ph > 0 else 0.0

    left_cov = _vertical_coverage(left)
    right_cov = _vertical_coverage(right)
    is_dual = len(left) >= 3 and len(right) >= 3 and left_cov >= 0.30 and right_cov >= 0.30
    if not is_dual:
        return page.get_text("text") or ""

    left.sort(key=lambda b: b[1])
    right.sort(key=lambda b: b[1])
    full.sort(key=lambda b: b[1])

    body_top = min(left[0][1] if left else float("inf"), right[0][1] if right else float("inf"))
    body_bottom = max(left[-1][3] if left else 0, right[-1][3] if right else 0)

    header = [b for b in full if b[3] < body_top]
    footer = [b for b in full if b[1] > body_bottom]
    middle = [b for b in full if b not in header and b not in footer]

    parts: list[tuple] = []
    parts.extend(header)
    parts.extend(left)
    parts.extend(middle)
    parts.extend(right)
    parts.extend(footer)

    return "\n".join(b[4] for b in parts)


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

    # Pages needing visual inspection
    visual_pages: set[int] = set()
    for page_no, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        if any(kw in text for kw in ("图", "表", "公式", "Fig.", "Table", "Equation", "式中")):
            visual_pages.add(page_no)
        # Also add pages with findings that have fallback_rect
        for f in findings:
            if f.page == page_no and f.fallback_rect:
                visual_pages.add(page_no)

    parts.append("# Pages Requiring Visual Inspection\n")
    if visual_pages:
        for p in sorted(visual_pages):
            parts.append(f"- Page {p}: `pages/page_{p:03d}.png`")
        parts.append("")
        parts.append("For each listed page, open the corresponding PNG and verify figure/table/formula layout, "
                     "axis labels, legend, watermark, three-line table format, subscript/superscript visual rendering, etc.")
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


def load_findings(path: Path) -> list[Finding]:
    data = json.loads(path.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    for item in data:
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
    return findings


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
            findings = load_findings(args.findings_json)
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
