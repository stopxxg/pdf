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
