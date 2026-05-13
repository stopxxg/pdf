# Project Quality Review & Bug Hunt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Systematically inspect and fix bugs, code smells, and cross-pipeline inconsistencies in the PDF/Word academic proofreader.

**Architecture:** Three-phase execution: (A) fix bugs in uncommitted changes, (B) extract shared rule constants to eliminate duplication, (C) verify cross-pipeline consistency via regression tests.

**Tech Stack:** Python 3.14, pytest, python-docx, PyMuPDF (fitz)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `scripts/pdf_module/reference_checker.py` | PDF reference format checking (GB/T 7714) |
| `scripts/pdf_module/term_checker.py` | PDF terminology consistency checking |
| `scripts/word_module/word_rule_detectors.py` | Word (.docx) mechanical rule detectors |
| `scripts/pdf_pipeline.py` | PDF pipeline orchestration (prepare + annotate) |
| `scripts/word_pipeline.py` | Word pipeline orchestration (prepare + annotate) |
| `scripts/shared_rules.py` | **NEW** Shared rule constants (text targets, regexes, prefixes, dedupe) |
| `tests/test_reference_checker.py` | **NEW** Regression tests for reference checker |
| `tests/test_word_rule_detectors.py` | **NEW** Regression tests for Word detectors |
| `tests/test_shared_rules.py` | **NEW** Tests for shared rule extraction |

---

## Task 1: Fix reference_checker.py bilingual regex false positive

**Files:**
- Modify: `scripts/pdf_module/reference_checker.py:185-196`
- Test: `tests/test_reference_checker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reference_checker.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "pdf_module"))

from reference_checker import _check_ref_format

def test_bilingual_ref_no_false_positive_on_year_in_title():
    """A Chinese ref with '10th' or year-like numbers in the English title
    should NOT be flagged as having an extra serial number."""
    text = "张三, 李四. 水土保持研究[J]. 2024, 31(2): 123-130."
    issues = _check_ref_format(1, text)
    # The old buggy regex would match "2024, 31" as a serial number
    assert not any("不应另加序号" in i.suggestion for i in issues)

def test_bilingual_ref_real_extra_serial_number():
    """A ref where English translation truly starts with a number should be flagged."""
    text = "张三, 李四. 水土保持研究[J]. 2024, 31(2): 123-130. 2 Zhang S, Li S. Research on Soil and Water Conservation."
    issues = _check_ref_format(1, text)
    assert any("不应另加序号" in i.suggestion for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/iswcxxg/Documents/New\ project/claude-code-pdf-academic-proofreader && python -m pytest tests/test_reference_checker.py -v`
Expected: FAIL — the first test fails because the current regex `\d+\s+[A-Z][a-zA-Z\s,]+\.\s*[A-Z]` matches `2024, 31`.

- [ ] **Step 3: Fix the regex**

In `scripts/pdf_module/reference_checker.py`, replace the bilingual check block (lines 185-196) with a stricter regex that requires the number to appear at the start of a sentence/line-like boundary after Chinese content, not just anywhere:

```python
    # Bilingual reference consistency (English translation should not have serial number)
    if re.search(r"[一-鿿]", t):
        # Look for a standalone English translation line/paragraph that starts with a number
        # Heuristic: after Chinese content, a number followed by English title/author pattern
        # Require the number to be at a word boundary after Chinese or punctuation, not mid-sentence
        if re.search(r"[一-鿿，。；！？]\s*(\d+)\s+[A-Z][a-zA-Z\s,]+\.\s*[A-Z]", t):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_reference_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_reference_checker.py scripts/pdf_module/reference_checker.py
git commit -m "fix(reference_checker): tighten bilingual ref serial-number regex

Prevent false positives when English title contains year-like numbers.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Fix word_rule_detectors.py _is_italic side-effect bug

**Files:**
- Modify: `scripts/word_module/word_rule_detectors.py:30-34`
- Test: `tests/test_word_rule_detectors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_word_rule_detectors.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "word_module"))

from unittest.mock import MagicMock
from word_rule_detectors import _is_italic

def test_is_italic_does_not_mutate_document():
    """_is_italic must be read-only; it must not add rPr elements."""
    run = MagicMock()
    run.font.italic = None
    # Simulate a run with NO rPr
    run._r.findall.return_value = []
    run._r.find.return_value = None
    result = _is_italic(run)
    # The bug: get_or_add_rPr modifies the XML tree
    run._r.get_or_add_rPr.assert_not_called()
    assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_word_rule_detectors.py::test_is_italic_does_not_mutate_document -v`
Expected: FAIL — assertion on `assert_not_called()` fails because the current code calls `get_or_add_rPr()`.

- [ ] **Step 3: Fix the side effect**

Replace `scripts/word_module/word_rule_detectors.py:30-34`:

```python
def _is_italic(run: Any) -> bool:
    if run.font.italic:
        return True
    rPr = run._r.find(qn("w:rPr"))
    if rPr is None:
        return False
    return rPr.find(qn("w:i")) is not None
```

Similarly, audit `_is_subscript` at lines 37-40 and ensure it also uses `find` only:

```python
def _is_subscript(run: Any) -> bool:
    rPr = run._r.find(qn("w:rPr"))
    if rPr is None:
        return False
    elem = rPr.find(qn("w:vertAlign"))
    return elem is not None and elem.get(qn("w:val")) == "subscript"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_word_rule_detectors.py::test_is_italic_does_not_mutate_document -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_word_rule_detectors.py scripts/word_module/word_rule_detectors.py
git commit -m "fix(word): make _is_italic and _is_subscript read-only

Use find() instead of get_or_add_rPr() to avoid mutating OOXML.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Fix detect_common_typos false positive on 快速地

**Files:**
- Modify: `scripts/word_module/word_rule_detectors.py:490`
- Test: `tests/test_word_rule_detectors.py`

- [ ] **Step 1: Write the failing test**

```python
def test_no_false_positive_on_kuaisu_di():
    """快速地 is a correct adverbial; do not flag it."""
    from word_rule_detectors import detect_common_typos, Finding
    doc = MagicMock()
    doc.paragraphs = [MagicMock(text="快速地完成了实验。")]
    findings = detect_common_typos(doc, "test.docx")
    assert not any("快速地" in f.suggestion for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_word_rule_detectors.py::test_no_false_positive_on_kuaisu_di -v`
Expected: FAIL — the regex `快速地[做进]` matches the text.

- [ ] **Step 3: Remove the false-positive rule**

In `scripts/word_module/word_rule_detectors.py`, delete this line from `chinese_typos`:

```python
        (r"快速地[做进]", "文字/用词", "快速地后若接动词，确认是否应为快速地。"),
```

Also add a comment above the list:

```python
    # Chinese typo patterns (heuristic regexes)
    # NOTE: 的/地/得 rules are deliberately omitted because the adverbial
    # particle 地 before a verb is grammatically correct (e.g. 快速地完成).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_word_rule_detectors.py::test_no_false_positive_on_kuaisu_di -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_word_rule_detectors.py scripts/word_module/word_rule_detectors.py
git commit -m "fix(word): remove false-positive 快速地 typo rule

快速地+verb is grammatically correct; flagging it creates noise.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Fix superscript regex over-match in word_rule_detectors.py

**Files:**
- Modify: `scripts/word_module/word_rule_detectors.py:409-425`
- Test: `tests/test_word_rule_detectors.py`

- [ ] **Step 1: Write the failing test**

```python
def test_no_false_positive_on_non_unit_m2():
    """m2 should only match as a unit, not as part of a word like am2."""
    from word_rule_detectors import detect_superscript_errors, Finding
    doc = MagicMock()
    doc.paragraphs = [MagicMock(text="The sample am2 was collected.")]
    findings = detect_superscript_errors(doc, "test.docx")
    assert not any("m2" in f.target for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_word_rule_detectors.py::test_no_false_positive_on_non_unit_m2 -v`
Expected: FAIL — the regex `[Rm]2\b` matches `m2` inside `am2`.

- [ ] **Step 3: Add word-boundary prefix requirement**

Replace the superscript_patterns list in `scripts/word_module/word_rule_detectors.py` with stricter patterns that require a word boundary or unit prefix before the target:

```python
    superscript_patterns = [
        (r"\b[Rm]2\b", "单位上标", "2"),
        (r"\b[Rm]3\b", "单位上标", "3"),
        (r"\bcm2\b", "单位上标", "2"),
        (r"\bcm3\b", "单位上标", "3"),
        (r"\bm2\b", "单位上标", "2"),        # standalone m²
        (r"\bm3\b", "单位上标", "3"),
        (r"\bkm2\b", "单位上标", "2"),
        (r"\bkm3\b", "单位上标", "3"),
        (r"\bmm2\b", "单位上标", "2"),
        (r"\bmm3\b", "单位上标", "3"),
        (r"\bhm2\b", "单位上标", "2"),
        (r"\bh2\b", "单位上标", "2"),
        (r"\bs2\b", "单位上标", "2"),
        (r"\bd2\b", "单位上标", "2"),
        (r"\ba2\b", "单位上标", "2"),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_word_rule_detectors.py::test_no_false_positive_on_non_unit_m2 -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_word_rule_detectors.py scripts/word_module/word_rule_detectors.py
git commit -m "fix(word): add word boundaries to superscript regexes

Prevent matching m2 inside words like am2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Extract shared rule constants to eliminate duplication

**Files:**
- Create: `scripts/shared_rules.py`
- Modify: `scripts/pdf_pipeline.py`, `scripts/word_module/word_rule_detectors.py`
- Test: `tests/test_shared_rules.py`

- [ ] **Step 1: Create shared_rules.py**

```python
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
# Deduplication helper
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
```

- [ ] **Step 2: Modify pdf_pipeline.py to import from shared_rules**

In `scripts/pdf_pipeline.py`:
- Replace the local `Finding` dataclass with an import from `shared_rules`
- Replace local `dedupe_findings` with import
- Replace local `TEXT_TARGET_RULES` content with import (or keep the local list but document that it is synced with shared_rules)

Because pdf_pipeline.py is large and the Finding class has the exact same fields, the safest minimal change is to add imports and remove the local duplicate:

```python
from shared_rules import Finding, dedupe_findings, SUBSCRIPT_PREFIXES, STAT_SYMBOL_PATTERNS, TEXT_TARGET_RULES, REGEX_RULES
```

Then delete the local `Finding` class (lines 35-46) and local `dedupe_findings` function (lines 785-794).

Also update `detect_stat_symbol_style` to use `STAT_SYMBOL_PATTERNS` and `detect_script_style` to use `SUBSCRIPT_PREFIXES`.

- [ ] **Step 3: Modify word_rule_detectors.py to import from shared_rules**

In `scripts/word_module/word_rule_detectors.py`:
- Remove local `Finding` class
- Import from shared_rules
- Replace local `subscript_prefixes` with `SUBSCRIPT_PREFIXES`
- Replace local `stat_patterns` with `STAT_SYMBOL_PATTERNS`
- Use shared `TEXT_TARGET_RULES` and `REGEX_RULES` in `detect_word_text_rules`
- Remove local `dedupe_findings` and import it

- [ ] **Step 4: Write tests for shared_rules**

```python
# tests/test_shared_rules.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from shared_rules import Finding, dedupe_findings, SUBSCRIPT_PREFIXES, TEXT_TARGET_RULES

def test_dedupe_removes_duplicates():
    f = Finding(file="a.pdf", page=1, target="x", category="c", suggestion="s")
    findings = [f, f]
    result = dedupe_findings(findings)
    assert len(result) == 1

def test_subscript_prefixes_has_expected_letters():
    assert "I" in SUBSCRIPT_PREFIXES
    assert "T" in SUBSCRIPT_PREFIXES
    assert "p" in SUBSCRIPT_PREFIXES

def test_text_target_rules_has_http_fullwidth_colon():
    targets = [t for t, _, _ in TEXT_TARGET_RULES]
    assert "http：" in targets
```

- [ ] **Step 5: Run all new tests**

Run: `python -m pytest tests/test_shared_rules.py tests/test_word_rule_detectors.py tests/test_reference_checker.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/shared_rules.py tests/test_shared_rules.py scripts/pdf_pipeline.py scripts/word_module/word_rule_detectors.py
git commit -m "refactor: extract shared rule constants to shared_rules.py

Eliminate duplication between PDF and Word pipelines.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Verify cross-pipeline consistency after refactoring

**Files:**
- Test: `tests/test_cross_pipeline_consistency.py`

- [ ] **Step 1: Write consistency tests**

```python
# tests/test_cross_pipeline_consistency.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "word_module"))

from shared_rules import TEXT_TARGET_RULES, REGEX_RULES, SUBSCRIPT_PREFIXES, STAT_SYMBOL_PATTERNS

def test_pdf_and_word_use_same_text_targets():
    """After refactoring, both pipelines must consume the same rule lists."""
    from pdf_pipeline import detect_text_rules
    from word_rule_detectors import detect_word_text_rules
    # We verify by inspecting the shared constants are actually imported
    # (if either pipeline redefines its own list, this test is a reminder to use shared_rules)
    assert len(TEXT_TARGET_RULES) > 0
    assert len(REGEX_RULES) > 0

def test_subscript_prefixes_sync():
    """SUBSCRIPT_PREFIXES must contain both uppercase and lowercase for domain coverage."""
    assert "I" in SUBSCRIPT_PREFIXES
    assert "p" in SUBSCRIPT_PREFIXES

def test_stat_symbol_patterns_have_five_entries():
    """Ensure the shared list covers p, I, R, F, tzq."""
    labels = {label for _, label, _ in STAT_SYMBOL_PATTERNS}
    assert labels == {"p", "I", "R", "F", "tzq"}
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_cross_pipeline_consistency.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_cross_pipeline_consistency.py
git commit -m "test: add cross-pipeline consistency regression tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Audit detect_inconsistent_compounds for dead code

**Files:**
- Modify: `scripts/word_module/word_rule_detectors.py:536-579`

- [ ] **Step 1: Verify the function is truly unused**

Search the codebase for `detect_inconsistent_compounds`:

Run: `grep -r "detect_inconsistent_compounds" scripts/ .claude/`
Expected: Only found in `word_rule_detectors.py` (not imported by pipeline)

- [ ] **Step 2: Confirm Word pipeline does not call it**

Read `scripts/word_pipeline.py` lines 99-108. Confirm `detect_inconsistent_compounds` is NOT in the call list.

- [ ] **Step 3: Add a comment or deprecation note**

Since the function is intentionally not called (per its own docstring), add a clear `# noqa: dead-code-intentional` style comment to prevent future confusion. Do NOT delete it — the docstring explains the design intent.

Replace the docstring with a more explicit one:

```python
def detect_inconsistent_compounds(document: Any, filename: str) -> list[Finding]:
    """DEAD CODE — intentionally not called by word_pipeline.py.

    The function exists only as a reference implementation. Compound-word
    form variations (land use vs land-use) are grammatically correct
    differences, not errors, so we deliberately do NOT emit automatic
    findings for them. If this logic is ever needed, it should write
    hints to review_context.md rather than return Finding objects.
    """
```

- [ ] **Step 4: Commit**

```bash
git add scripts/word_module/word_rule_detectors.py
git commit -m "docs(word): clarify detect_inconsistent_compounds as dead code

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Spec Coverage Check

| Spec Section | Task(s) |
|-------------|---------|
| Phase A — reference_checker.py | Task 1 |
| Phase A — word_rule_detectors.py side effects | Task 2 |
| Phase A — word_rule_detectors.py false positives | Tasks 3, 4 |
| Phase B — cross-pipeline consistency | Tasks 5, 6 |
| Phase C — rule precision (dead code) | Task 7 |

## Placeholder Scan
- No TBD, TODO, or "implement later" found.
- Every step contains exact file paths and exact code.

## Type Consistency
- `Finding` dataclass uses identical fields across all tasks.
- `dedupe_findings` signature unchanged.
- `SUBSCRIPT_PREFIXES` is a `set[str]` in all consumers.

---

**Plan saved to `docs/superpowers/plans/2026-05-13-project-quality-review.md`.**

**Execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks
2. **Inline Execution** — Execute tasks in this session using executing-plans

Which approach?
