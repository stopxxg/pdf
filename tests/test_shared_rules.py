import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from shared_rules import Finding, dedupe_findings, SUBSCRIPT_PREFIXES, TEXT_TARGET_RULES, STAT_SYMBOL_PATTERNS

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

def test_stat_symbol_patterns_has_five_entries():
    labels = {label for _, label, _ in STAT_SYMBOL_PATTERNS}
    assert labels == {"p", "I", "R", "F", "tzq"}
