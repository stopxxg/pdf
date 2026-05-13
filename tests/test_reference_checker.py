import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "pdf_module"))

from reference_checker import _check_ref_format

def test_bilingual_ref_no_false_positive_on_year_in_title():
    """A Chinese ref with year-like numbers should NOT be flagged as extra serial number."""
    text = "张三, 李四. 水土保持研究[J]. 2024, 31(2): 123-130."
    issues = _check_ref_format(1, text)
    assert not any("不应另加序号" in i.suggestion for i in issues)

def test_bilingual_ref_real_extra_serial_number():
    """A ref where English translation truly starts with a number should be flagged."""
    text = "张三, 李四. 水土保持研究[J]. 2024, 31(2): 123-130. 2 Zhang S, Li S. Research on Soil and Water Conservation."
    issues = _check_ref_format(1, text)
    assert any("不应另加序号" in i.suggestion for i in issues)

def test_no_false_positive_on_hyphenated_name():
    """A hyphenated English name with a preceding year should NOT be flagged."""
    text = "张三. 标题[J]. 2024. Zhang-S, Li S. Paper Title."
    issues = _check_ref_format(1, text)
    assert not any("不应另加序号" in i.suggestion for i in issues)

def test_real_extra_serial_with_hyphenated_name():
    """A real extra serial number followed by hyphenated surname should be flagged."""
    text = "张三. 标题[J]. 2024. 2 Zhang-S, Li S. Paper Title."
    issues = _check_ref_format(1, text)
    assert any("不应另加序号" in i.suggestion for i in issues)

def test_no_false_positive_on_apostrophe_name():
    """An apostrophe surname with preceding year should NOT be flagged."""
    text = "张三. 标题[J]. 2024. O'Connor S. Paper Title."
    issues = _check_ref_format(1, text)
    assert not any("不应另加序号" in i.suggestion for i in issues)

def test_no_false_positive_4digit_number():
    """A 4-digit number like 2024 should not match as serial number."""
    text = "张三. 标题[J]. 2024 Zhang S. Paper Title."
    issues = _check_ref_format(1, text)
    assert not any("不应另加序号" in i.suggestion for i in issues)

def test_no_false_positive_lowercase_after_number():
    """A number followed by lowercase should not match."""
    text = "张三. 标题[J]. 2nd edition."
    issues = _check_ref_format(1, text)
    assert not any("不应另加序号" in i.suggestion for i in issues)
