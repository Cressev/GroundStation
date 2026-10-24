"""Verify sidebar visibility and persistence without connecting to any hardware."""

from unittest.mock import Mock

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from test_last_connection import windows
from test_ui_state_machine import ensure_app


def show_window(make, variant='dual'):
    """Finish deferred layout restoration before manipulating the splitter."""
    window = make(variant)
    window.resize(1400, 900)
    window.show()
    ensure_app().processEvents()
    return window


@pytest.mark.parametrize('variant', ['dual', 'single'])
def test_toggle_releases_center_space_and_restores_width(windows, variant):
    """Both variants retain their left width and original right width."""
    make, _, _ = windows
    window = show_window(make, variant)
    window.main_splitter.setSizes([400, 650, 300])
    before = window.main_splitter.sizes()
    QTest.mouseClick(window.right_sidebar_toggle, Qt.LeftButton)
    ensure_app().processEvents()
    collapsed = window.main_splitter.sizes()
    assert collapsed[0] == before[0]
    assert collapsed[2] == 28
    assert collapsed[1] == before[1] + before[2] - 28
    assert window.right_sidebar_toggle.isVisible()
    assert window.right_sidebar_content.isHidden()
    assert window.right_sidebar_toggle.arrowType() == Qt.LeftArrow
    window.right_sidebar_toggle.setFocus()
    QTest.keyClick(window.right_sidebar_toggle, Qt.Key_Space)
    assert window.main_splitter.sizes() == before
    assert window.right_sidebar_content.isVisible()


def test_repeated_requests_keep_tabs_logs_and_connection_untouched(windows):
    """Collapsing is idempotent and never invokes a service or control command."""
    make, _, _ = windows
    window = show_window(make)
    communication = Mock()
    window.communication = communication
    window.right_tabs.setCurrentIndex(1)
    window.info_text.setPlainText('sidebar state marker')
    depth = window.depth_panel
    before = window.main_splitter.sizes()
    for _ in range(5):
        window.set_right_sidebar_collapsed(True)
        window.set_right_sidebar_collapsed(True)
        assert window.main_splitter.sizes()[2] == 28
        window.set_right_sidebar_collapsed(False)
        window.set_right_sidebar_collapsed(False)
        assert window.main_splitter.sizes() == before
    assert window.depth_panel is depth
    assert window.right_tabs.currentIndex() == 1
    assert window.info_text.toPlainText() == 'sidebar state marker'
    assert window.communication is communication
    assert communication.mock_calls == []
    window.communication = None


def test_restart_retains_collapsed_state_and_expanded_width(windows):
    """Closing while folded must not replace the remembered width with 28px."""
    make, _, _ = windows
    first = show_window(make)
    first.main_splitter.setSizes([400, 650, 330])
    width = first.main_splitter.sizes()[2]
    first.set_right_sidebar_collapsed(True)
    first.close()
    second = show_window(make)
    assert second._right_sidebar_collapsed
    assert second.main_splitter.sizes()[2] == 28
    second.set_right_sidebar_collapsed(False)
    assert abs(second.main_splitter.sizes()[2] - width) <= 2


def test_variants_have_independent_collapse_settings(windows):
    """Pico sidebar preferences must not collapse the OrangePi sidebar."""
    make, _, _ = windows
    show_window(make).set_right_sidebar_collapsed(True)
    single = show_window(make, 'single')
    assert not single._right_sidebar_collapsed
    assert single.main_splitter.sizes()[2] >= 220


def test_restart_retains_manually_narrowed_sidebar(windows):
    """A width below the default must also survive a folded restart."""
    make, _, _ = windows
    first = show_window(make)
    first.main_splitter.setSizes([400, 800, 180])
    width = first.main_splitter.sizes()[2]
    first.set_right_sidebar_collapsed(True)
    first.close()
    second = show_window(make)
    second.set_right_sidebar_collapsed(False)
    assert abs(second.main_splitter.sizes()[2] - width) <= 2


def test_parallel_controller_layout_does_not_reopen_sidebar(windows):
    """Selecting two-column PID must retain the narrow right rail."""
    make, _, _ = windows
    window = show_window(make)
    window.set_right_sidebar_collapsed(True)
    window.depth_controller_combo.setCurrentIndex(
        window.depth_controller_combo.findData('parallel_pid'))
    ensure_app().processEvents()
    assert window._right_sidebar_collapsed
    assert window.main_splitter.sizes()[2] == 28
    assert window.right_sidebar_content.isHidden()


@pytest.mark.parametrize('value', ['false', 'broken', None])
def test_invalid_or_false_preference_keeps_sidebar_open(windows, value):
    """Text false and corrupt preferences must not accidentally hide the sidebar."""
    make, settings, _ = windows
    settings.setValue('layout/right_sidebar_collapsed/dual', value)
    settings.sync()
    window = show_window(make)
    assert not window._right_sidebar_collapsed


def test_expanding_after_small_window_resize_is_bounded(windows):
    """The rail remains reachable after resizing and expansion remains usable."""
    make, _, _ = windows
    window = show_window(make)
    window.set_right_sidebar_collapsed(True)
    window.resize(1000, 700)
    ensure_app().processEvents()
    assert window.right_sidebar_toggle.isVisible()
    assert window.main_splitter.sizes()[2] == 28
    window.set_right_sidebar_collapsed(False)
    assert 170 <= window.main_splitter.sizes()[2] <= 300
    assert window.main_splitter.sizes()[1] >= 300
