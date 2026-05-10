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
    tmp_deps = Path("/private/tmp/pdfdeps")
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
                        "line_bbox": line_bbox,
                    }


def _italic_flag() -> int:
    try:
        return int(fitz.TEXT_FONT_ITALIC)  # type: ignore[attr-defined]
    except Exception:
        return 2


def is_italic(char: dict[str, object]) -> bool:
    font = str(char.get("font", "")).lower()
    flags = int(char.get("flags", 0) or 0)
    return bool(flags & _italic_flag()) or "italic" in font or "oblique" in font


def union_rect(rects: Iterable[fitz.Rect]) -> fitz.Rect:
    items = list(rects)
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


def detect_p_value_style(doc: fitz.Document, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    # Match p/P followed by optional space, comparator, optional space, and number.
    # Covers p<0.05, P > 0.01, p=0.001, p≤0.05, etc.
    p_regex = re.compile(r"[pP]\s*(?:[<=>≤≥])\s*(?:0?\.\d+|\d+)")
    for page_no, page in enumerate(doc, start=1):
        chars = list(page_chars(page))
        text = "".join(str(ch["c"]) for ch in chars)
        for match in p_regex.finditer(text):
            start, end = match.start(), match.end()
            run = chars[start:end]
            if not run:
                continue
            p_char = run[0]
            rect = char_rect(run)
            ys = [float(ch["bbox"][1]) for ch in run]  # type: ignore[index]
            size = float(p_char.get("size", 0) or 0)
            if p_char["c"] in "pP" and not is_italic(p_char):
                findings.append(
                    Finding(
                        filename,
                        page_no,
                        f"auto:p-style:{page_no}:{start}",
                        "公式/统计符号正斜体",
                        "字符级字体检查显示，此处p值中的p为正体。建议将p排为斜体。",
                        severity="high",
                        source="char-font",
                        fallback_rect=rect,
                    )
                )
            if max(ys) - min(ys) > max(3.0, size * 0.6):
                findings.append(
                    Finding(
                        filename,
                        page_no,
                        f"auto:p-linebreak:{page_no}:{start}",
                        "公式/统计表达断行",
                        "字符级位置检查显示，统计表达被拆成跨行显示。建议避免在统计表达内部断行。",
                        severity="medium",
                        source="char-position",
                        fallback_rect=rect,
                    )
                )
    return findings


def detect_text_rules(filename: str, page_no: int, text: str) -> list[Finding]:
    findings: list[Finding] = []
    front = text[:2400]
    if page_no == 1:
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
        ("0. 05", "文字/标点", "显著性水平数字中存在多余空格。建议改为“0.05”。"),
        ("0. 01", "文字/标点", "显著性水平数字中存在多余空格。建议改为“0.01”。"),
        ("，。", "文字/标点", "连续出现逗号和句号。建议删除多余标点。"),
        ("。。", "文字/标点", "连续出现两个句号。建议删除多余标点。"),
        ("..", "文字/标点", "连续出现两个英文句点。建议核查DOI、URL或参考文献标点。"),
        ("本研仍", "文字/标点", "“本研”疑为“本研究”。建议补全。"),
        ("波段性", "文字/标点", "“波段性”在趋势描述中疑为“波动性”。建议核改。"),
        ("与和", "文字/标点", "“与和”连用不当。建议删除多余连接词。"),
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

    occurrence = 0
    for match in re.finditer(r"[pP]\s*<\s*0\.\s+0[15]", text):
        add_text_finding(
            findings,
            filename,
            page_no,
            match.group(),
            "公式/统计表达",
            "p值表达存在多余空格或断裂风险。建议统一为紧凑形式，并核查p是否斜体。",
            occurrence=occurrence,
        )
        occurrence += 1

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
    for page_no, page in enumerate(doc, start=1):
        for line in (page.get_text("text") or "").splitlines():
            match = re.match(r"^［([0-9]+)］", line.strip())
            if match:
                refs.append((int(match.group(1)), page_no, line.strip()))
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


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[object, ...]] = set()
    unique: list[Finding] = []
    for item in findings:
        key = (item.file, item.page, item.target, item.category, item.occurrence, item.fallback_rect)
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


def run_api_review(pdf: Path, artifact_dir: Path) -> list[Finding]:
    """Run API review on a PDF and return findings with precise coordinates."""
    try:
        from pdf_module.pdf_ai_client import ModelConfig, review_markdown, _resolve_api_key, _resolve_base_url, _resolve_model_name
        from pdf_module.pdf_annotator import map_api_findings
    except Exception:
        return []

    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "config.json"
    prompt_path = project_root / "prompt.json"

    if not config_path.exists():
        return []

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not cfg.get("auto_enable_api_review", False):
        return []

    provider = str(cfg.get("provider", "doubao")).strip().lower()
    try:
        api_key = _resolve_api_key(provider)
    except Exception:
        return []

    base_url = _resolve_base_url(provider, str(cfg.get("base_url", "")))
    model_name = _resolve_model_name(provider, str(cfg.get("model_name", "")))

    model_cfg = ModelConfig(
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=float(cfg.get("temperature", 0.3)),
        top_p=float(cfg.get("top_p", 1.0)),
        max_tokens=int(cfg.get("max_tokens", 4096)),
        timeout=int(cfg.get("timeout_seconds", 120)),
        stream=bool(cfg.get("stream", False)),
        enable_prompt_cache=bool(cfg.get("enable_prompt_cache", False)),
    )

    prompt = ""
    if prompt_path.exists():
        try:
            p = json.loads(prompt_path.read_text(encoding="utf-8"))
            prompt = str(p.get("full_doc_prompt", ""))
        except Exception:
            pass

    md_path = artifact_dir / pdf.stem / "fulltext.md"
    if not md_path.exists():
        return []

    md_text = md_path.read_text(encoding="utf-8")
    result = review_markdown(md_text, model_cfg, prompt=prompt)

    if not result.issues:
        return []

    mapped = map_api_findings(pdf, result.issues)
    findings: list[Finding] = []
    for mf in mapped.findings:
        findings.append(
            Finding(
                file=mf.file,
                page=mf.page,
                target=mf.target,
                category=mf.category,
                suggestion=mf.suggestion,
                severity=mf.severity,
                source="api",
                fallback_rect=mf.fallback_rect,
            )
        )

    if mapped.missed:
        missed_path = artifact_dir / pdf.stem / "api_missed.json"
        missed_path.write_text(json.dumps(mapped.missed, ensure_ascii=False, indent=2), encoding="utf-8")

    return findings


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
        findings.extend(detect_p_value_style(doc, pdf.name))
        findings.extend(detect_caption_order(doc, pdf.name))
        findings.extend(detect_reference_sequence(doc, pdf.name))
        for page_no, page in enumerate(doc, start=1):
            findings.extend(detect_text_rules(pdf.name, page_no, extract_page_text(page)))

        # API review layer (optional, controlled by config.json)
        api_findings = run_api_review(pdf, artifact_dir)
        if api_findings:
            findings.extend(api_findings)

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
            )
        )
    return findings


def find_rect(page: fitz.Page, finding: Finding) -> fitz.Rect | None:
    if finding.target.startswith("auto:") and finding.fallback_rect:
        return fitz.Rect(finding.fallback_rect)
    variants = [
        finding.target,
        finding.target.replace("\n", " "),
        finding.target.replace("\n", ""),
        " ".join(finding.target.split()),
    ]
    for query in variants:
        rects = page.search_for(query, quads=False)
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
        for finding in findings:
            if Path(finding.file).name != pdf.name:
                continue
            if finding.page < 1 or finding.page > doc.page_count:
                missed.append(asdict(finding) | {"reason": "page out of range"})
                continue
            if add_annotation(doc[finding.page - 1], finding):
                annotated += 1
            else:
                missed.append(asdict(finding) | {"reason": "target not found"})

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
    parser.add_argument("--mode", choices=["scan", "annotate", "auto"], default="scan")
    parser.add_argument("--findings-json", type=Path, help="Reviewed findings JSON for annotate mode.")
    parser.add_argument("--same-name", action="store_true", help="Keep output PDF filenames unchanged.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum PDFs to process; 0 means all.")
    parser.add_argument("--render-dpi", type=int, default=144, help="DPI for page PNG rendering during scan. 0 disables rendering.")
    parser.add_argument("--verbose", action="store_true", help="Print full JSON results instead of compact summary.")
    args = parser.parse_args()

    if args.mode == "auto":
        # auto mode now includes local rules + optional API review
        # Quality depends on config.json: auto_enable_api_review + provider
        pass

    root = args.root.resolve()
    output_dir = resolve_output(root, args.output)
    pdfs = pdfs_under(root, output_dir)
    if args.limit > 0:
        pdfs = pdfs[: args.limit]

    results: list[dict[str, object]] = []
    if args.mode in {"scan", "auto"}:
        for pdf in pdfs:
            item = collect_candidates(pdf, output_dir, render_dpi=args.render_dpi)
            results.append(item)
            print(json.dumps({"phase": "scan", "file": pdf.name, "status": item["status"], "candidates": item.get("candidate_count", 0)}, ensure_ascii=False))

    if args.mode in {"annotate", "auto"}:
        if args.findings_json:
            findings = load_findings(args.findings_json)
        elif args.mode == "auto":
            findings = []
            for item in results:
                candidate = item.get("candidate_json")
                if candidate:
                    findings.extend(load_findings(Path(str(candidate))))
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
