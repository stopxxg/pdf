import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "word_module"))

from unittest.mock import MagicMock
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
