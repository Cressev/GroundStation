"""Connected feedback must not enlarge the window or hide bottom controls."""
from unittest.mock import Mock
import pytest
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QSizePolicy
from controllers.xbox import XboxInputState
from test_last_connection import windows
from test_ui_state_machine import ensure_app


@pytest.fixture
def connected_layout(windows, monkeypatch):
    """Use disposable settings and synthetic statuses with no hardware polling."""
    monkeypatch.setattr('controllers.xbox.XInputBackend', lambda: Mock(
        available=False, poll=Mock(return_value=XboxInputState())))
    make, _, _ = windows
    window = make()
    panel = window.depth_panel
    panel._parent_connection_available = True
    panel._on_connection_status(True, '')
    panel._on_line(dict(type='depth', raw_1=123.4, filtered_1=123.3, fused=123.3))
    panel.calib_status_label.setText('当前零点: +6.663 m')
    window.control_ownership_label.setText('尾鳍：已停止\n胸鳍：单闭环 PID · 1200 μs')
    window.show()
    ensure_app().processEvents()
    return window


@pytest.mark.parametrize('height', [900, 720, 650])
def test_connected_window_keeps_requested_height(connected_layout, height):
    """Feedback and hidden pages cannot force the status bar below the screen."""
    window = connected_layout
    window.resize(1280, height)
    window.main_splitter.setSizes([370, 610, 300])
    ensure_app().processEvents()
    assert window.height() <= height
    assert window.statusBar().mapTo(window, QPoint()).y()+window.statusBar().height() <= height
    assert window.axis_control_scroll.minimumHeight() <= 120


def test_depth_status_and_values_do_not_compete_in_one_row(connected_layout):
    """Connection, zero offset and record status occupy full-width rows."""
    window = connected_layout
    window.resize(1280, 720)
    ensure_app().processEvents()
    panel = window.depth_panel
    assert panel.conn_status_label.y() > panel.connect_btn.y()
    assert panel.calib_status_label.y() > panel.calib_btn.y()
    assert panel.record_status_label.y() > panel.record_btn.y()
    assert panel.raw_label.y() < panel.filtered_label.y() < panel.fused_label.y()
    assert panel.conn_status_label.width() >= panel.conn_status_label.fontMetrics().horizontalAdvance('状态: 已连接')


def test_sidebar_scroll_reaches_system_info_after_feedback(connected_layout):
    """The lower log panel can always be reached without enlarging the window."""
    window = connected_layout
    window.resize(1280, 650)
    ensure_app().processEvents()
    scroll = window.right_sidebar_scroll
    assert scroll.widget() is window.right_sidebar_content
    scroll.ensureWidgetVisible(window.info_text)
    ensure_app().processEvents()
    center = window.info_text.mapTo(scroll.viewport(), window.info_text.rect().center())
    assert scroll.viewport().rect().contains(center)


def test_short_time_canvas_scrolls_without_changing_export_target(connected_layout):
    """Keep both complete plots in the same exportable canvas and scroll it."""
    window = connected_layout
    view = window.visualization_widget
    view.time_series_scroll.setMaximumHeight(180)
    ensure_app().processEvents()
    scroll = view.time_series_scroll
    assert scroll.widget() is view.time_series_canvas
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(view.rpy_status_label)
    ensure_app().processEvents()
    center = view.rpy_status_label.mapTo(scroll.viewport(), view.rpy_status_label.rect().center())
    assert scroll.viewport().rect().contains(center)
    assert view.z_plot.height() >= 150 and view.rpy_plot.height() >= 150


def test_fold_unfold_retains_scroll_and_content(connected_layout):
    """Repeated sidebar operations leave data, status and scroll state intact."""
    window = connected_layout
    text = window.depth_panel.depth_big_label.text()
    window.set_right_sidebar_collapsed(True, persist=False)
    window.set_right_sidebar_collapsed(True, persist=False)
    assert window.right_sidebar_scroll.isHidden()
    assert window.main_splitter.sizes()[2] == 28
    window.set_right_sidebar_collapsed(False, persist=False)
    window.set_right_sidebar_collapsed(False, persist=False)
    assert window.right_sidebar_scroll.isVisible()
    assert window.depth_panel.depth_big_label.text() == text
