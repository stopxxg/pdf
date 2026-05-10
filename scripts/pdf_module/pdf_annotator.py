"""Convert API review findings into precise PDF annotations.

Maps AI-returned (page, original) into exact PDF coordinates using
page.search_for(). Falls back to fallback_rect estimation on failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import fitz  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path("/private/tmp/pdfdeps")))
    import fitz  # type: ignore


@dataclass(frozen=True)
class MappedFinding:
    file: str
    page: int
    target: str
    category: str
    suggestion: str
    severity: str
    source: str
    fallback_rect: tuple[float, float, float, float] | None = None
    end_of_doc: bool = False


@dataclass
class MappingResult:
    findings: list[MappedFinding]
    missed: list[dict[str, Any]]


def _infer_severity(error: str) -> str:
    e = error.lower()
    if any(w in e for w in ("占位符", "排版事故", "必须删除", "严重", "缺失", "错误")):
        return "high"
    if any(w in e for w in ("多余空格", "标点", "斜体", "缺少", "建议")):
        return "medium"
    return "low"


def _infer_category(error: str) -> str:
    e = error.lower()
    if any(w in e for w in ("参考文献", "et al", "卷号", "期号", "引用")):
        return "参考文献格式"
    if any(w in e for w in ("斜体", "正体", "p值", "统计符号", "上标", "下标")):
        return "公式/统计符号正斜体"
    if any(w in e for w in ("图", "表", "坐标轴", "图例", "审图号")):
        return "图/表格式"
    if any(w in e for w in ("多余空格", "标点", "逗号", "句号", "冒号")):
        return "文字/标点"
    if any(w in e for w in ("术语", "统一", "不一致")):
        return "术语/统一"
    if any(w in e for w in ("占位符", "排版", "水印")):
        return "版式/占位符"
    return "AI审读"


def _build_suggestion(issue: dict[str, Any]) -> str:
    parts: list[str] = [str(issue.get("error", ""))]
    fix = str(issue.get("fix", ""))
    if fix:
        parts.append(f"建议修改为：{fix}")
    comment = str(issue.get("comment", ""))
    if comment:
        parts.append(f"批注：{comment}")
    return "；".join(parts)


def _find_rect(page: fitz.Page, target: str) -> fitz.Rect | None:
    if not target.strip():
        return None
    # Exact match first
    rects = page.search_for(target, quads=False)
    if rects:
        return fitz.Rect(rects[0])
    # Compact match (remove spaces)
    compact_target = re.sub(r"\s+", "", target)
    if len(compact_target) >= 4:
        rects = page.search_for(compact_target, quads=False)
        if rects:
            return fitz.Rect(rects[0])
    # Word-by-word fuzzy match
    words = target.split()
    if len(words) >= 2:
        query = words[0] + words[-1]
        if len(query) >= 4:
            rects = page.search_for(query, quads=False)
            if rects:
                return fitz.Rect(rects[0])
    return None


def map_api_findings(
    pdf_path: Path,
    api_issues: list[dict[str, Any]],
) -> MappingResult:
    """Map AI findings to precise PDF coordinates."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return MappingResult(
            findings=[],
            missed=[{"reason": f"open_failed: {exc}"}],
        )

    findings: list[MappedFinding] = []
    missed: list[dict[str, Any]] = []

    try:
        for issue in api_issues:
            page_no = int(issue.get("page", 0))
            original = str(issue.get("original", ""))
            if page_no < 1 or page_no > doc.page_count:
                missed.append({"issue": issue, "reason": "page_out_of_range"})
                continue
            if not original.strip():
                missed.append({"issue": issue, "reason": "empty_target"})
                continue

            page = doc[page_no - 1]
            rect = _find_rect(page, original)

            suggestion = _build_suggestion(issue)
            severity = _infer_severity(str(issue.get("error", "")))
            category = _infer_category(str(issue.get("error", "")))

            if rect is None:
                # Try paragraph context if available
                paragraph = str(issue.get("paragraph", ""))
                if paragraph.strip():
                    rect = _find_rect(page, paragraph)

            if rect is None:
                # Fallback: append to end-of-document summary page
                findings.append(
                    MappedFinding(
                        file=pdf_path.name,
                        page=page_no,
                        target=original,
                        category=category,
                        suggestion=suggestion,
                        severity=severity,
                        source="api",
                        fallback_rect=None,
                        end_of_doc=True,
                    )
                )
                continue

            findings.append(
                MappedFinding(
                    file=pdf_path.name,
                    page=page_no,
                    target=original,
                    category=category,
                    suggestion=suggestion,
                    severity=severity,
                    source="api",
                    fallback_rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                )
            )
    finally:
        doc.close()

    return MappingResult(findings=findings, missed=missed)
