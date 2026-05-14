import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "word_module"))

from unittest.mock import MagicMock, patch
from docx.oxml.ns import qn
from word_rule_detectors import _is_italic, _is_subscript

def test_is_italic_does_not_mutate_document():
    """_is_italic must be read-only; it must not add rPr elements."""
    run = MagicMock()
    run.font.italic = None
    run._r.findall.return_value = []
    run._r.find.return_value = None
    result = _is_italic(run)
    run._r.get_or_add_rPr.assert_not_called()
    assert result is False

def test_is_subscript_does_not_mutate_document():
    """_is_subscript must be read-only; it must not add rPr elements."""
    run = MagicMock()
    run._r.find.return_value = None
    result = _is_subscript(run)
    run._r.get_or_add_rPr.assert_not_called()
    assert result is False

def test_is_italic_true_when_font_italic_set():
    run = MagicMock()
    run.font.italic = True
    assert _is_italic(run) is True

def test_is_italic_false_when_no_rpr():
    run = MagicMock()
    run.font.italic = None
    run._r.find.return_value = None
    assert _is_italic(run) is False

def test_is_italic_false_when_rpr_without_i():
    run = MagicMock()
    run.font.italic = None
    rPr = MagicMock()
    rPr.find.return_value = None
    run._r.find.return_value = rPr
    assert _is_italic(run) is False

def test_is_italic_true_when_rpr_has_i():
    run = MagicMock()
    run.font.italic = None
    rPr = MagicMock()
    rPr.find.return_value = MagicMock()  # w:i element exists
    run._r.find.return_value = rPr
    assert _is_italic(run) is True

def test_is_subscript_false_when_no_rpr():
    run = MagicMock()
    run._r.find.return_value = None
    assert _is_subscript(run) is False

def test_is_subscript_false_when_rpr_without_vertalign():
    run = MagicMock()
    rPr = MagicMock()
    rPr.find.return_value = None
    run._r.find.return_value = rPr
    assert _is_subscript(run) is False

def test_is_subscript_false_when_vertalign_is_superscript():
    run = MagicMock()
    rPr = MagicMock()
    vertAlign = MagicMock()
    vertAlign.get.return_value = "superscript"
    rPr.find.return_value = vertAlign
    run._r.find.return_value = rPr
    assert _is_subscript(run) is False

def test_is_subscript_true_when_vertalign_is_subscript():
    run = MagicMock()
    rPr = MagicMock()
    vertAlign = MagicMock()
    vertAlign.get.return_value = "subscript"
    rPr.find.return_value = vertAlign
    run._r.find.return_value = rPr
    assert _is_subscript(run) is True

def test_no_false_positive_on_kuaisu_di():
    """快速地 + verb is grammatically correct; do not flag it."""
    from word_rule_detectors import detect_common_typos
    doc = MagicMock()
    doc.paragraphs = [MagicMock(text="快速地完成了实验。")]
    findings = detect_common_typos(doc, "test.docx")
    assert not any("快速地" in f.suggestion for f in findings)

def test_no_false_positive_on_non_unit_m2():
    """m2 should only match as a standalone unit, not inside a word like am2."""
    from word_rule_detectors import detect_superscript_errors
    doc = MagicMock()
    para = MagicMock()
    run = MagicMock()
    run.text = "The sample am2 was collected."
    para.runs = [run]
    doc.paragraphs = [para]
    findings = detect_superscript_errors(doc, "test.docx")
    assert not any("m2" in f.target for f in findings)
