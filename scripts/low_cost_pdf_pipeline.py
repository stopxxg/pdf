#!/usr/bin/env python3
"""Low-output PDF proofreading pipeline for Chinese academic journals.

This script is intentionally quiet. It writes full extraction artifacts,
candidate findings, and logs to disk, while printing only compact progress
summaries. The intended workflow is:

1. Run automatic candidate detection for one PDF at a time.
2. Let an editor or AI review the compact candidate JSON, adding/deleting items.
3. Re-run annotation using the reviewed findings JSON.

The script never edits source PDFs.
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


@dataclass(frozen=True)
class Finding:
    file: str
    page: int
    target: str
    category: str
    suggestion: str
    severity: str = "medium"
    source: str = "rule"
    occurrence: int = 0
    fallback_rect: tuple[float, float, float, float] | None = None
    end_of_doc: bool = False


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


def page_chars(page: fitz.Page) -> Iterator[dict[str, object]]:
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            line_bbox = tuple(line.get("bbox", (0, 0, 0, 0)))
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
    """Add findings for regex-based text rules."""
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
    # Patterns for common statistical expressions
    stat_patterns = [
        (re.compile(r"[pP]\s*(?:[<=>≤≥])\s*(?:0?\.\d+|\d+)"), "p", "p值中的p"),
        (re.compile(r"[I]\d+"), "I", "Moran's I中的I"),
        (re.compile(r"[R]\d+|R²"), "R", "相关系数R"),
        (re.compile(r"[F]\s*\(|F\d+"), "F", "F统计量"),
        (re.compile(r"[tzq]\s*(?:=|<|>|≥|≤|\()"), "tzq", "统计符号"),
    ]
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
    # Common variable letters that frequently carry numeric subscripts in scientific papers
    subscript_prefixes = set("ITRPXYZWVSDHCKMNpxyzwvsdhckmn")
    for page_no, page in enumerate(doc, start=1):
        chars = list(page_chars(page))
        i = 0
        while i < len(chars) - 1:
            ch = chars[i]
            if ch["c"].isalpha() and ch["c"] in subscript_prefixes and is_italic(ch):
                letter_rect = fitz.Rect(ch["bbox"])
                letter_size = float(ch.get("size", 0) or 0)
                if letter_size <= 0:
                    i += 1
                    continue
                # Collect consecutive digits immediately following the letter
                j = i + 1
                digits: list[dict[str, object]] = []
                while j < len(chars) and chars[j]["c"].isdigit():
                    # Ensure digit is on roughly the same line
                    dy = abs(float(chars[j]["bbox"][1]) - float(ch["bbox"][1]))
                    if dy > letter_size * 0.8:
                        break
                    digits.append(chars[j])
                    j += 1
                if 1 <= len(digits) <= 3:
                    digit_rects = [fitz.Rect(d["bbox"]) for d in digits]
                    combined_digit_rect = union_rect(digit_rects)
                    digit_size = max(float(d.get("size", 0) or 0) for d in digits)
                    letter_center_y = (letter_rect.y0 + letter_rect.y1) / 2
                    digit_center_y = (combined_digit_rect.y0 + combined_digit_rect.y1) / 2
                    # Subscript heuristic: digit is lower (larger y) and smaller than the letter
                    is_sub = (
                        digit_center_y > letter_center_y + letter_size * 0.05
                        and digit_size < letter_size * 0.9
                    )
                    if not is_sub:
                        # Guard against large gaps (e.g., across words)
                        gap = digit_rects[0].x0 - letter_rect.x1
                        if gap < letter_size * 1.5:
                            target_text = ch["c"] + "".join(d["c"] for d in digits)
                            findings.append(
                                Finding(
                                    filename,
                                    page_no,
                                    f"auto:subscript:{page_no}:{i}",
                                    "公式/下标格式",
                                    f"字符级位置检查显示，{target_text} 中的数字未显示为下标。建议将数字改为下标格式。",
                                    severity="medium",
                                    source="char-position",
                                    fallback_rect=(combined_digit_rect.x0, combined_digit_rect.y0, combined_digit_rect.x1, combined_digit_rect.y1),
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
        missing_labels = [label for label in ["［目的］", "［方法］", "［结果］", "［结论］"] if label not in front]
        if missing_labels:
            add_text_finding(
                findings,
                filename,
                page_no,
                "摘",
                "摘要结构",
                f"结构式摘要未检出{''.join(missing_labels)}。建议核查摘要栏目是否完整。",
                "medium",
            )

    text_targets: list[tuple[str, str, str]] = [
        ("http：", "文字/标点", "URL存在全角冒号，可能导致链接失效。建议改为半角“http://”或“https://”。"),
        ("https：", "文字/标点", "URL存在全角冒号，可能导致链接失效。建议改为半角“https://”。"),
        ("∥", "文字/标点", "URL中疑似使用了异常双斜线符号。建议改为半角“//”。"),
        ("0. 001", "文字/标点", "数值“0. 001”中存在多余空格。建议改为“0.001”。"),
        ("，。", "文字/标点", "连续出现逗号和句号。建议删除多余标点。"),
        ("。。", "文字/标点", "连续出现两个句号。建议删除多余标点。"),
        ("..", "文字/标点", "连续出现两个英文句点。建议核查DOI、URL或参考文献标点。"),
        ("、、", "文字/标点", "连续出现两个顿号。建议删除多余顿号。"),
        ("本研仍", "文字/标点", "“本研”疑为“本研究”。建议补全。"),
        ("波段性", "文字/标点", "“波段性”在趋势描述中疑为“波动性”。建议核改。"),
        ("与和", "文字/标点", "“与和”连用不当。建议删除多余连接词。"),
        ("摘 要", "文字/标点", "“摘 要”中间有多余空格，应改为“摘要”。"),
    ]
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

    # Regex-based text rules
    _add_regex_findings(findings, filename, page_no, text, [
        (r"[pP]\s*<\s*0\.\s+0[15]", "公式/统计表达", "p值表达存在多余空格或断裂风险。建议统一为紧凑形式，并核查p是否斜体。"),
        (r"0\.\s+\d+", "文字/标点", "小数点后存在多余空格，建议删除空格。"),
        (r"图\s+\d+", "文字/标点", "“图”与编号之间存在多余空格，建议改为“图1”格式。"),
        (r"表\s+\d+", "文字/标点", "“表”与编号之间存在多余空格，建议改为“表1”格式。"),
        (r"et al\.[A-Z]", "文字/标点", "“et al.”后缺少空格，建议改为“et al. Author”。"),
        (r"[a-zA-Z]，[a-zA-Z]", "文字/标点", "英文文本中使用了全角逗号，建议改为半角逗号。"),
        (r"[a-zA-Z]。[a-zA-Z]", "文字/标点", "英文文本中使用了全角句号，建议改为半角句点。"),
    ])

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
            match = re.match(r"^［([0-9]+)］", stripped)
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
    """Detect missing figure/table numbers in first in-text citations."""
    findings: list[Finding] = []
    for prefix, label in [("图", "图"), ("表", "表")]:
        cites: list[tuple[int, int]] = []
        for page_no, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
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
            missing = [n for n in expected if n not in nums]
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


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[object, ...]] = set()
    unique: list[Finding] = []
    for item in findings:
        key = (item.file, item.page, item.target, item.category, item.occurrence, item.fallback_rect, item.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def extract_page_text(page: fitz.Page) -> str:
    """Extract text with dual-column awareness.

    Standard journal PDFs often use two-column body text.
    PyMuPDF's default get_text('text') usually respects reading order,
    but we add an explicit columnar fallback for non-standard layouts.
    """
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

    # Dual-column heuristic: substantial text blocks on both sides
    # AND at least one column has continuous vertical coverage >= 30% of page height
    # (to avoid misclassifying cover pages with scattered elements)
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

    # Determine body text vertical range
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


def write_text_artifacts(doc: fitz.Document, pdf: Path, artifact_dir: Path) -> None:
    paper_dir = artifact_dir / pdf.stem
    paper_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    for page_no, page in enumerate(doc, start=1):
        text = extract_page_text(page)
        chunks.append(f"===== PAGE {page_no} =====\n{text}\n")
        (paper_dir / f"page_{page_no:03d}.txt").write_text(text, encoding="utf-8")
    (paper_dir / "fulltext.txt").write_text("\n".join(chunks), encoding="utf-8")

    # Also generate Markdown with italic markup for API review
    try:
        from pdf_module.pdf_text_converter import pdf_to_markdown
        md = pdf_to_markdown(pdf, apply_markup=True)
        (paper_dir / "fulltext.md").write_text(md, encoding="utf-8")
    except Exception:
        pass


def collect_candidates(pdf: Path, output_dir: Path, render_dpi: int = 0) -> dict[str, object]:
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
        write_text_artifacts(doc, pdf, artifact_dir)
        paper_dir = artifact_dir / pdf.stem
        if render_dpi > 0:
            image_dir = paper_dir / "pages"
            image_dir.mkdir(exist_ok=True)
            scale = render_dpi / 72.0
            mat = fitz.Matrix(scale, scale)
            for page_no, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=mat, alpha=False)
                pix.save(image_dir / f"page_{page_no:03d}.png")

        findings: list[Finding] = []
        findings.extend(detect_stat_symbol_style(doc, pdf.name))
        findings.extend(detect_script_style(doc, pdf.name))
        findings.extend(detect_caption_order(doc, pdf.name))
        findings.extend(detect_reference_sequence(doc, pdf.name))
        findings.extend(detect_figure_table_citation_order(doc, pdf.name))
        for page_no, page in enumerate(doc, start=1):
            findings.extend(detect_text_rules(pdf.name, page_no, extract_page_text(page)))

        findings = dedupe_findings(findings)
        candidate_path = candidate_dir / f"{pdf.stem}.findings.json"
        candidate_path.write_text(
            json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result.update(
            {
                "status": "done",
                "candidate_count": len(findings),
                "candidate_json": str(candidate_path),
                "artifact_dir": str(paper_dir),
            }
        )
        return result
    except Exception as exc:
        result["reason"] = f"scan failed: {exc}"
        return result
    finally:
        doc.close()


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


_HALF_WIDTH_TRANS = str.maketrans({
    "，": ",", "。": ".", "：": ":", "；": ";",
    "（": "(", "）": ")", "［": "[", "］": "]",
    "【": "[", "】": "]", "、": ",", "！": "!",
    "？": "?", "“": '"', "”": '"', "‘": "'", "’": "'",
    "′": "'", "″": '"', "—": "-", "–": "-",
})


def _to_halfwidth(s: str) -> str:
    """Convert common full-width punctuation to half-width for search fallback."""
    return s.translate(_HALF_WIDTH_TRANS)


def _extract_search_keys(target: str) -> list[str]:
    """Extract high-discriminability short phrases from a target for search fallback."""
    if target.startswith("auto:"):
        target = target.split(":", 2)[-1] if target.count(":") >= 2 else target
    keys: list[str] = []
    if len(target) <= 30:
        keys.append(target)
    # Core text without surrounding punctuation
    core = target.strip("（）()[]［］\"'\"'")
    if core and core != target and len(core) <= 30:
        keys.append(core)
    # Split by punctuation/spaces and take longest meaningful fragments
    parts = re.split(r"[，。：；、！？\s\(\)\[\]（）［］]", target)
    for p in sorted(parts, key=len, reverse=True):
        if len(p) >= 4 and p not in keys:
            keys.append(p)
            if len(keys) >= 5:
                break
    # For Chinese targets, also add head and tail slices
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

    # Fallback: search for distinctive key phrases extracted from long targets
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
    """Insert text with CJK font fallback."""
    for font in _CJK_FONTS:
        try:
            page.insert_text(point, text, fontname=font, **kwargs)
            return
        except Exception:
            continue


def _add_end_of_doc_summary(doc: fitz.Document, findings: list[Finding]) -> int:
    """Append a summary page with missed findings that could not be located."""
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


def resolve_output(root: Path, output: Path | None) -> Path:
    return output.resolve() if output else (root / "annotated_pdfs").resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="Folder containing source PDFs.")
    parser.add_argument("--output", type=Path, help="Output folder. Defaults to ROOT/annotated_pdfs.")
    parser.add_argument("--mode", choices=["scan", "annotate"], default="scan")
    parser.add_argument("--findings-json", type=Path, help="Reviewed findings JSON for annotate mode.")
    parser.add_argument("--same-name", action="store_true", help="Keep output PDF filenames unchanged.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum PDFs to process; 0 means all.")
    parser.add_argument("--render-dpi", type=int, default=144, help="DPI for page PNG rendering during scan. 0 disables rendering.")
    parser.add_argument("--verbose", action="store_true", help="Print full JSON results instead of compact summary.")
    args = parser.parse_args()

    root = args.root.resolve()
    output_dir = resolve_output(root, args.output)
    pdfs = pdfs_under(root, output_dir)
    if args.limit > 0:
        pdfs = pdfs[: args.limit]

    results: list[dict[str, object]] = []
    if args.mode == "scan":
        for pdf in pdfs:
            item = collect_candidates(pdf, output_dir, render_dpi=args.render_dpi)
            results.append(item)
            print(json.dumps({"phase": "scan", "file": pdf.name, "status": item["status"], "candidates": item.get("candidate_count", 0)}, ensure_ascii=False))

    if args.mode == "annotate":
        if args.findings_json:
            findings = load_findings(args.findings_json)
        else:
            raise SystemExit("--findings-json is required in annotate mode")

        annotate_results = []
        for pdf in pdfs:
            item = annotate_pdf(pdf, output_dir, findings, same_name=args.same_name)
            annotate_results.append(item)
            print(
                json.dumps(
                    {
                        "phase": "annotate",
                        "file": pdf.name,
                        "status": item["status"],
                        "annotations": item.get("findings_annotated", 0),
                        "missed": len(item.get("missed", [])),
                    },
                    ensure_ascii=False,
                )
            )
        append_log(output_dir, annotate_results)
        results = annotate_results

    if args.verbose:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "output": str(output_dir),
                    "mode": args.mode,
                    "pdfs": len(pdfs),
                    "done": sum(1 for item in results if str(item.get("status", "")).startswith("done")),
                    "skipped": sum(1 for item in results if item.get("status") == "skipped"),
                    "total_annotations": sum(int(item.get("findings_annotated", 0) or 0) for item in results),
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
