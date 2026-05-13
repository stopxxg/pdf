# scripts/shared_rules.py
"""Shared rule constants and utilities for PDF and Word pipelines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Text target rules (exact string matches)
# ---------------------------------------------------------------------------
TEXT_TARGET_RULES: list[tuple[str, str, str]] = [
    ("http：", "文字/标点", "URL存在全角冒号，可能导致链接失效。建议改为半角http://或https://。"),
    ("https：", "文字/标点", "URL存在全角冒号，可能导致链接失效。建议改为半角https://。"),
    ("0. 001", "文字/标点", "数值0.001中存在多余空格。建议改为0.001。"),
    ("，。", "文字/标点", "连续出现逗号和句号。建议删除多余标点。"),
    ("。。", "文字/标点", "连续出现两个句号。建议删除多余标点。"),
    ("..", "文字/标点", "连续出现两个英文句点。建议核查DOI、URL或参考文献标点。"),
    ("、、", "文字/标点", "连续出现两个顿号。建议删除多余顿号。"),
    ("本研仍", "文字/标点", "本研疑为本研究。建议补全。"),
    ("波段性", "文字/标点", "波段性在趋势描述中疑为波动性。建议核改。"),
    ("与和", "文字/标点", "与和连用不当。建议删除多余连接词。"),
    ("摘 要", "文字/标点", "摘要中间有多余空格，应改为摘要。"),
]


# ---------------------------------------------------------------------------
# Regex-based text rules
# ---------------------------------------------------------------------------
REGEX_RULES: list[tuple[str, str, str]] = [
    (r"[pP]\s*<\s*0\.\s+0[15]", "公式/统计表达", "p值表达存在多余空格或断裂风险。建议统一为紧凑形式，并核查p是否斜体。"),
    (r"0\.\s+\d+", "文字/标点", "小数点后存在多余空格，建议删除空格。"),
    (r"图\s+\d+", "文字/标点", "图与编号之间存在多余空格，建议改为图1格式。"),
    (r"表\s+\d+", "文字/标点", "表与编号之间存在多余空格，建议改为表1格式。"),
    (r"et al\.[A-Z]", "文字/标点", "et al.后缺少空格，建议改为et al. Author。"),
]


# ---------------------------------------------------------------------------
# Subscript prefixes (variables that commonly take numeric subscripts)
# ---------------------------------------------------------------------------
SUBSCRIPT_PREFIXES: set[str] = set("ITRPXYZWVSDHCKMNpxyzwvsdhckmn")


# ---------------------------------------------------------------------------
# Stat symbol patterns for italic/upright checking
# ---------------------------------------------------------------------------
STAT_SYMBOL_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"[pP]\s*(?:[<=>≤≥])\s*(?:0?\.\d+|\d+)"), "p", "p值中的p"),
    (re.compile(r"[I]\d+"), "I", "Moran's I中的I"),
    (re.compile(r"[R]\d+|R²"), "R", "相关系数R"),
    (re.compile(r"[F]\s*\(|F\d+"), "F", "F统计量"),
    (re.compile(r"[tzq]\s*(?:=|<|>|≥|≤|\()"), "tzq", "统计符号"),
]


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------
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
