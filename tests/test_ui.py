from types import SimpleNamespace
from unittest.mock import MagicMock

from utgiftsanalys.ui import _make_color_col_config


def test_returns_none_when_color_column_absent():
    cfg = SimpleNamespace()  # no ColorColumn attribute
    assert _make_color_col_config(cfg) is None


def test_builds_dict_when_color_column_present():
    mock_cls = MagicMock(return_value="sentinel")
    cfg = SimpleNamespace(ColorColumn=mock_cls)
    result = _make_color_col_config(cfg)
    assert result is not None
    assert "Color" in result
    mock_cls.assert_called_once_with("Color", width="small")


def test_returns_none_for_installed_streamlit_when_color_column_missing():
    import streamlit as st

    # ColorColumn is absent in the installed version; confirm the real code path
    result = _make_color_col_config(st.column_config)
    assert getattr(st.column_config, "ColorColumn", None) is None
    assert result is None
