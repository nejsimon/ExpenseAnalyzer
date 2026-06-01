from types import SimpleNamespace
from unittest.mock import MagicMock

from expense_analyzer.ui import _contrast_color


def test_contrast_color_light_bg_gives_black():
    assert _contrast_color("#ffffff") == "#000000"


def test_contrast_color_dark_bg_gives_white():
    assert _contrast_color("#000000") == "#ffffff"


def test_contrast_color_pure_blue_gives_white():
    # pure blue: L = 0.0722 * 1.0 = 0.0722 < 0.179 → white text
    assert _contrast_color("#0000ff") == "#ffffff"
