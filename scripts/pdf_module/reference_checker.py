"""GB/T 7714-2015 reference format checker for Chinese academic journals.

Produces candidate findings for reference numbering, formatting, completeness,
and citation-reference consistency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fitz  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import sys, os
    deps = Path(os.environ.get("PDFDEPS_PATH", "/private/tmp/pdfdeps"))
    if deps.exists():
        sys.path.insert(0, str(deps))
    import fitz  # type: ignore


@dataclass
class RefIssue:
    page: int
    ref_no: int | None
    target: str
    category: str
    suggestion: str
    severity: str = "medium"


def _extract_refs(text: str) -> list[tuple[int, str]]:
    """Extract reference lines with their numbers."""
    lines = text.splitlines()
    refs: list[tuple[int, str]] = []
    in_refs = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"参考文献[（(]References[）)]?[:：]?", stripped):
            in_refs = True
            continue
        if in_refs:
            m = re.match(r"^[［\[]?([0-9]+)[］\]]?\s+(.*)$", stripped)
            if m:
                refs.append((int(m.group(1)), m.group(2)))
            elif refs and not re.match(r"^[［\[]?[0-9]+", stripped):
                # Continuation of previous reference (bilingual refs)
                last_no, last_text = refs[-1]
                refs[-1] = (last_no, last_text + " " + stripped)
    return refs


def _extract_in_text_citations(text: str) -> set[int]:
    """Extract in-text citation numbers like ［1］, [1], [1-3], [1,2]."""
    cites: set[int] = set()
    for m in re.finditer(r"[［\[]([0-9]+(?:[，,\-–—][0-9]+)*)[］\]]", text):
        group = m.group(1)
        for part in re.split(r"[，,\-–—]", group):
            if part.isdigit():
                cites.add(int(part))
    return cites


def _check_ref_format(ref_no: int, text: str) -> list[RefIssue]:
    issues: list[RefIssue] = []
    t = text.strip()

    # Detect doc type marker
    has_marker = bool(re.search(r"[［\[]([JMCDRON/OL]+)[］\]]", t))
    if not has_marker:
        issues.append(
            RefIssue(
                page=0,
                ref_no=ref_no,
                target=t[:40],
                category="参考文献格式",
                suggestion="参考文献缺少文献类型标识（如[J]、[M]等），建议按GB/T 7714补充。",
                severity="medium",
            )
        )

    # et al. / 等 punctuation
    if "et al" in t and "et al." not in t and "et al.," not in t:
        issues.append(
            RefIssue(
                page=0,
                ref_no=ref_no,
                target="et al",
                category="参考文献格式",
                suggestion="英文参考文献中et al.后应加句点，建议改为“et al.”。",
                severity="low",
            )
        )

    # Chinese references with missing "等"
    if re.search(r"[一-鿿]", t) and "，" in t:
        # Extract author part: before the first period, Chinese comma, or title marker
        authors_part = t.split(".")[0] if "." in t else t.split("。")[0]
        # Count authors by Chinese commas, but only if the commas are within reasonable length
        if len(authors_part) < 80:
            comma_count = authors_part.count("，")
            # Heuristic: 3 commas ≈ 4 authors; require at least 3 commas and no "等"
            if comma_count >= 3 and "等" not in authors_part:
                issues.append(
                    RefIssue(
                        page=0,
                        ref_no=ref_no,
                        target=authors_part[:30],
                        category="参考文献格式",
                        suggestion="中文参考文献作者超过3人时，建议在第3人后加“等”。",
                        severity="low",
                    )
                )

    # Volume/issue completeness for journal articles
    if "[J]" in t or "[J/OL]" in t:
        # Look for year pattern
        year_match = re.search(r"(\d{4})", t)
        if year_match:
            after_year = t[year_match.end():]
            # Accept multiple styles: , 33(5) ; Vol.33, No.5 ; only volume
            has_volume_issue = re.search(r",\s*\d+\s*\(\s*\d+\s*\)", after_year)
            has_vol_no = re.search(r"Vol\.\s*\d+|No\.\s*\d+", after_year, re.IGNORECASE)
            has_only_volume = re.search(r",\s*\d+\s*[:：.]", after_year)
            if not has_volume_issue and not has_vol_no and not has_only_volume:
                issues.append(
                    RefIssue(
                        page=0,
                        ref_no=ref_no,
                        target=t[:40],
                        category="参考文献格式",
                        suggestion="期刊参考文献建议补充完整的卷(期)号，如“2026，33(5)”。",
                        severity="low",
                    )
                )

    # Page range or article number
    if "[J]" in t or "[J/OL]" in t:
        # Accept colon, period, or space before page numbers
        has_pages = re.search(r"[:：.\s]\s*\d+[-–—]\d+", t) or re.search(r"[:：.\s]\s*\d{3,}", t)
        if not has_pages:
            issues.append(
                RefIssue(
                    page=0,
                    ref_no=ref_no,
                    target=t[:40],
                    category="参考文献格式",
                    suggestion="期刊参考文献缺少起止页码或文章编号，建议补充。",
                    severity="low",
                )
            )

    # Full-width colon in page numbers or URLs
    if re.search(r"http：//|https：//", t):
        issues.append(
            RefIssue(
                page=0,
                ref_no=ref_no,
                target="http：",
                category="参考文献格式",
                suggestion="URL中存在全角冒号，建议改为半角“http://”。",
                severity="medium",
            )
        )

    # DOI format
    if "DOI" in t.upper() and not re.search(r"10\.\d{4,}/", t):
        issues.append(
            RefIssue(
                page=0,
                ref_no=ref_no,
                target="DOI",
                category="参考文献格式",
                suggestion="DOI格式疑似不规范，建议按“10.xxxx/xxxx”格式核对。",
                severity="low",
            )
        )

    # Bilingual reference consistency (English translation should not have serial number)
    if re.search(r"[一-鿿]", t):
        match = re.search(r"\b(\d{1,3})\s+[A-Z][a-zA-Z\s,]+\.\s*[A-Z]", t)
        if match:
            start = match.start()
            preceding = t[max(0, start - 15):start]
            # Skip if the number is part of a year/vol/issue citation like "2024, 33"
            if not re.search(r"(?:19|20)\d{2}\s*[-,;:\s]*\s*$", preceding):
                issues.append(
                    RefIssue(
                        page=0,
                        ref_no=ref_no,
                        target=t[:30],
                        category="参考文献格式",
                        suggestion="双语参考文献的英文翻译不应另加序号，建议删除开头编号。",
                        severity="low",
                    )
                )

    return issues


def check_references_text(full_text: str, filename: str, last_page: int = 1) -> list[RefIssue]:
    """Run full reference check on plain text."""
    refs = _extract_refs(full_text)
    if not refs:
        return []

    issues: list[RefIssue] = []

    # 1. Numbering continuity
    nums = [n for n, _ in refs]
    if len(nums) >= 2:
        expected = list(range(nums[0], nums[-1] + 1))
        if nums != expected:
            missing = [n for n in expected if n not in nums]
            duplicates = [n for n in set(nums) if nums.count(n) > 1]
            msg = []
            if missing:
                msg.append(f"缺号：{missing}")
            if duplicates:
                msg.append(f"重复：{duplicates}")
            issues.append(
                RefIssue(
                    page=0,
                    ref_no=None,
                    target="参考文献编号",
                    category="参考文献格式",
                    suggestion=f"参考文献编号不连续。{'; '.join(msg)}。建议按正文引用顺序重新编号。",
                    severity="high",
                )
            )

    # 2. Individual format checks
    for ref_no, text in refs:
        issues.extend(_check_ref_format(ref_no, text))

    # 3. Citation-reference consistency
    in_text_cites = _extract_in_text_citations(full_text)
    ref_nums = {n for n, _ in refs}

    uncited = sorted(ref_nums - in_text_cites)
    uncited_in_text = sorted(in_text_cites - ref_nums)

    if uncited:
        issues.append(
            RefIssue(
                page=0,
                ref_no=None,
                target="参考文献",
                category="参考文献格式",
                suggestion=f"以下参考文献在正文中未被引用：{uncited}。建议核查或删除。",
                severity="medium",
            )
        )

    if uncited_in_text:
        issues.append(
            RefIssue(
                page=0,
                ref_no=None,
                target="正文引用",
                category="参考文献格式",
                suggestion=f"正文引用了以下不存在的参考文献编号：{uncited_in_text}。建议核查。",
                severity="high",
            )
        )

    # 4. Reference count is intentionally not flagged automatically because journal limits vary.

    # Attach approximate page numbers
    if last_page <= 0:
        last_page = 1
    for issue in issues:
        if issue.page == 0:
            issue.page = last_page

    return issues


def check_references(doc: fitz.Document, filename: str) -> list[RefIssue]:
    """Run full reference check on a PDF document."""
    full_text = "\n".join(page.get_text("text") or "" for page in doc)
    return check_references_text(full_text, filename, doc.page_count)


def to_findings(issues: list[RefIssue], filename: str) -> list[dict[str, Any]]:
    return [
        {
            "file": filename,
            "page": issue.page,
            "target": issue.target,
            "category": issue.category,
            "suggestion": issue.suggestion,
            "severity": issue.severity,
            "source": "reference-check",
            "occurrence": 0,
            "fallback_rect": None,
            "end_of_doc": False,
        }
        for issue in issues
    ]


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) < 2:
        print("Usage: python reference_checker.py <pdf_path>", file=sys.stderr)
        print("       python reference_checker.py --text <fulltext_path> <filename>", file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--text":
        if len(sys.argv) < 4:
            print("Usage: python reference_checker.py --text <fulltext_path> <filename>", file=sys.stderr)
            sys.exit(1)
        text_path = Path(sys.argv[2])
        filename = sys.argv[3]
        if not text_path.exists():
            print(f"Error: file not found: {text_path}", file=sys.stderr)
            sys.exit(1)
        full_text = text_path.read_text(encoding="utf-8")
        issues = check_references_text(full_text, filename)
        print(json.dumps(to_findings(issues, filename), ensure_ascii=False, indent=2))
        sys.exit(0)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        doc = fitz.open(path)
        issues = check_references(doc, path.name)
        doc.close()
        print(json.dumps(to_findings(issues, path.name), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
