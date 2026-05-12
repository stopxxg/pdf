"""Terminology consistency checker for Chinese academic papers.

Extracts key terms from title, abstract, and keywords, then scans the full
body for inconsistent variants or abbreviations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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
class TermIssue:
    page: int
    target: str
    category: str
    suggestion: str
    severity: str = "low"


def _extract_title_abstract_keywords(text: str) -> tuple[str, str, str]:
    """Extract title, abstract, and keywords from front matter."""
    lines = text.splitlines()
    title = ""
    abstract = ""
    keywords = ""

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not title and len(stripped) >= 10 and re.search(r"[一-鿿]{8,}", stripped):
            title = stripped
        if "摘" in stripped and "要" in stripped:
            # Abstract starts here or next line
            abstract_lines = [stripped]
            for j in range(i + 1, min(i + 60, len(lines))):
                stripped_j = lines[j].strip()
                if any(kw in stripped_j for kw in ("关键词", "［结论］", "[结论]", "Abstract", "Key words", "［目的］")):
                    break
                abstract_lines.append(lines[j])
            abstract = " ".join(abstract_lines)
        if "关键词" in stripped or "关键词：" in stripped:
            keywords = stripped.replace("关键词：", "").replace("关键词:", "").strip()

    return title, abstract, keywords


def _extract_terms(text: str) -> set[str]:
    """Extract candidate terms (Chinese noun phrases, length 4–12 chars)."""
    # Remove punctuation
    cleaned = re.sub(r"[^一-鿿a-zA-Z0-9\s]", " ", text)
    # Find Chinese phrases 4–12 chars long
    terms: set[str] = set()
    for m in re.finditer(r"[一-鿿]{4,12}", cleaned):
        term = m.group()
        # Skip common non-terms
        if len(term) >= 6:
            terms.add(term)
    return terms


def _find_variants(full_text: str, terms: set[str]) -> list[tuple[str, str, int]]:
    """Find potential inconsistent variants of key terms."""
    variants: list[tuple[str, str, int]] = []
    stop_words = {"的", "是", "在", "和", "与", "及", "或", "为", "了", "对", "将", "从", "到", "以"}
    for term in terms:
        if len(term) < 8:
            continue
        orig_count = full_text.count(term)
        for drop in range(2, min(5, len(term) - 3)):
            sub = term[drop:]
            if len(sub) < 4 or sub[0] in stop_words:
                continue
            if sub in full_text and sub != term:
                count = full_text.count(sub)
                # Only flag when the full term also appears frequently
                # and the variant is not overwhelmingly dominant (which suggests intentional abbreviation)
                if count >= 3 and orig_count >= 3 and count <= orig_count * 2:
                    variants.append((term, sub, count))
    return variants


def check_terms_text(full_text: str, filename: str) -> list[TermIssue]:
    """Run terminology consistency check on plain text."""
    title, abstract, keywords = _extract_title_abstract_keywords(full_text)

    front_text = title + " " + abstract + " " + keywords
    terms = _extract_terms(front_text)

    issues: list[TermIssue] = []

    for original, variant, count in _find_variants(full_text, terms):
        issues.append(
            TermIssue(
                page=0,
                target=variant,
                category="术语/统一",
                suggestion=f"正文中多次出现“{variant}”（{count}次），疑似“{original}”的不一致简写或变体，建议全文统一。",
                severity="low",
            )
        )

    # Attach approximate page numbers
    for issue in issues:
        if issue.page == 0:
            issue.page = 1  # Term issues are usually global

    return issues


def check_terms(doc: fitz.Document, filename: str) -> list[TermIssue]:
    """Run terminology consistency check on a PDF document."""
    full_text = "\n".join(page.get_text("text") or "" for page in doc)
    return check_terms_text(full_text, filename)


def to_findings(issues: list[TermIssue], filename: str) -> list[dict[str, Any]]:
    return [
        {
            "file": filename,
            "page": issue.page,
            "target": issue.target,
            "category": issue.category,
            "suggestion": issue.suggestion,
            "severity": issue.severity,
            "source": "term-check",
            "occurrence": 0,
            "fallback_rect": None,
            "end_of_doc": True,  # Global issues go to end-of-doc summary
        }
        for issue in issues
    ]


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) < 2:
        print("Usage: python term_checker.py <pdf_path>", file=sys.stderr)
        print("       python term_checker.py --text <fulltext_path> <filename>", file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--text":
        if len(sys.argv) < 4:
            print("Usage: python term_checker.py --text <fulltext_path> <filename>", file=sys.stderr)
            sys.exit(1)
        text_path = Path(sys.argv[2])
        filename = sys.argv[3]
        if not text_path.exists():
            print(f"Error: file not found: {text_path}", file=sys.stderr)
            sys.exit(1)
        full_text = text_path.read_text(encoding="utf-8")
        issues = check_terms_text(full_text, filename)
        print(json.dumps(to_findings(issues, filename), ensure_ascii=False, indent=2))
        sys.exit(0)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        doc = fitz.open(path)
        issues = check_terms(doc, path.name)
        doc.close()
        print(json.dumps(to_findings(issues, path.name), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
