import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from shared_rules import TEXT_TARGET_RULES, REGEX_RULES, SUBSCRIPT_PREFIXES, STAT_SYMBOL_PATTERNS


def test_text_target_rules_not_empty():
    assert len(TEXT_TARGET_RULES) > 0
    targets = [t for t, _, _ in TEXT_TARGET_RULES]
    assert "http：" in targets


def test_regex_rules_not_empty():
    assert len(REGEX_RULES) > 0


def test_subscript_prefixes_has_both_cases():
    assert "I" in SUBSCRIPT_PREFIXES
    assert "p" in SUBSCRIPT_PREFIXES


def test_stat_symbol_patterns_has_five_entries():
    labels = {label for _, label, _ in STAT_SYMBOL_PATTERNS}
    assert labels == {"p", "I", "R", "F", "tzq"}
