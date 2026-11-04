"""System telemetry history, time-range export and GUI-thread connection ownership."""

import csv
import math
import zipfile
from unittest.mock import patch

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QLabel
from ui.system_status import SystemStatusWidget
from test_ui_state_machine import ensure_app
from test_control_axes import window


@pytest.fixture
def status():
    """Create a disposable page with no network or experiment side effects."""
    ensure_app()
    page = SystemStatusWidget()
    page.set_connected(True)
    yield page
    page.close()


def feed(page, second, **values):
    """Supply identified real-arrival-like packets, not periodic copies of one snapshot."""
    payload = dict(cpu_percent=25., soc_temp_c=45.+second/10,
                   mem_used_mb=1024, mem_total_mb=4096, cpu_freq_mhz=1800)
    payload.update(values)
    return page.add_sample(payload, received_at=100.+second, source_timestamp=1000.+second)


def test_metrics_units_missing_values_and_duplicate_packets(status):
    """Missing readings remain missing; same source sample cannot create a new point."""
    assert feed(status, 0)
    assert not status.add_sample({}, received_at=101., source_timestamp=1000.)
    assert status.rows[0]['memory_percent'] == 25.
    assert status.rows[0]['time_s'] == 0.
    assert feed(status, 1, cpu_percent=float('nan'), soc_temp_c=None, mem_total_mb=0)
    assert status.rows[-1]['cpu_percent'] is None
    assert status.rows[-1]['soc_temp_c'] is None
    assert status.rows[-1]['memory_percent'] is None
    assert status.rows[0]['cpu_percent'] == 25.


def test_global_sliding_and_free_range_keep_entire_history(status):
    """Windows affect viewing only; manual inspection retains earlier curves and true exports."""
    for second in range(31):
        feed(status, second)
    status.sliding_window_input.setValue(10)
    status.sliding_time_cb.setChecked(True)
    assert len(status.rows) == 31
    assert [r['time_s'] for r in status.visible_rows()] == list(range(20, 31))
    status.global_time_cb.setChecked(True)
    assert len(status.visible_rows()) == 31
    status.plots[1].setXRange(7.2, 12.8, padding=0)
    status._on_manual_view_change('soc_temp_c')
    assert [r['time_s'] for r in status.visible_rows()] == [8., 9., 10., 11., 12.]
    feed(status, 31)
    assert [r['time_s'] for r in status.visible_rows()] == [8., 9., 10., 11., 12.]
    status.reset_view()
    assert len(status.visible_rows()) == 32


def test_exports_real_visible_range_csv_and_excel(status, tmp_path):
    """CSV/XLSX include only current viewport rows, units and raw receipt/source metadata."""
    for second in range(20):
        feed(status, second)
    status.follow_latest = False
    status.plots[0].setXRange(3.2, 6.8, padding=0)
    path, count = status.export_data(tmp_path/'samples.csv')
    with open(path, encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert count == 3 and [float(r['time_s']) for r in rows] == [4., 5., 6.]
    assert rows[0]['memory_percent'] == '25.0'
    assert 'received_utc' in rows[0] and 'source_timestamp' in rows[0]
    assert 'condition' not in rows[0]
    assert all('condition' not in row for row in status.rows)
    path, count = status.export_data(tmp_path/'samples.xlsx')
    assert count == 3 and zipfile.is_zipfile(path)


def test_disconnect_timeout_gaps_clear_and_fresh_start(status):
    """An outage leaves a NaN gap, keeps history and never plots a stale repeated value."""
    feed(status, 0)
    status.set_connected(False)
    assert not feed(status, 1)
    status.set_connected(True)
    feed(status, 10)
    assert len(status.rows) == 3
    assert status.rows[1]['status'] == 'gap'
    _, values = status.curves['cpu_percent'].getData()
    assert math.isnan(values[1])
    status.clear_data()
    assert status.rows == []
    feed(status, 11)
    assert status.rows[0]['time_s'] == 0.


def test_out_of_order_and_invalid_payloads_never_create_fake_readings(status):
    """Bad types and impossible utilization are missing data, not zero temperature/load."""
    assert not status.add_sample(None, received_at=100.)
    assert feed(status, 0)
    assert not feed(status, -1)
    assert feed(status, 1, cpu_percent=101., mem_used_mb=5000, soc_temp_c=float('inf'))
    assert status.rows[-1]['cpu_percent'] is None
    assert status.rows[-1]['memory_percent'] is None


def test_main_telemetry_is_queued_and_old_connection_is_ignored(window):
    """Worker callbacks never touch widgets, and delayed packets from replaced sockets are dropped."""
    current = window.communication
    window.system_status_widget.set_connected(True)
    payload = dict(telemetry=dict(cpu_percent=10., soc_temp_c=42., mem_used_mb=100, mem_total_mb=1000), timestamp=1.)
    window._on_board_state(current, payload)
    assert not window.system_status_widget.rows
    ensure_app().processEvents()
    assert len(window.system_status_widget.rows) == 1
    window._on_board_state(object(), dict(payload, timestamp=2.))
    ensure_app().processEvents()
    assert len(window.system_status_widget.rows) == 1
    assert not any(window.center_tabs.tabText(i) == '系统状态' for i in range(window.center_tabs.count()))
    tabs = window.visualization_widget.tab_widget
    assert any(tabs.tabText(i) == '系统状态' for i in range(tabs.count()))
    assert window.system_status_widget is window.visualization_widget.system_status_widget


def test_independent_pan_follow_reset_and_export_reference(status):
    """Panning CPU leaves others following; export follows the last manually viewed canvas."""
    for second in range(31):
        feed(status, second)
    status.plots[0].setXRange(4., 8., padding=0)
    status._on_manual_view_change('cpu_percent')
    feed(status, 31)
    assert status.plots[0].getViewBox().viewRange()[0] == [4., 8.]
    assert status.plots[1].getViewBox().viewRange()[0] == [0., 31.]
    assert status.plots[2].getViewBox().viewRange()[0] == [0., 31.]
    assert [r['time_s'] for r in status.visible_rows()] == list(range(4, 9))
    status.plots[1].setXRange(10., 12., padding=0)
    status._on_manual_view_change('soc_temp_c')
    assert [r['time_s'] for r in status.visible_rows()] == [10., 11., 12.]
    status.reset_plot('soc_temp_c')
    assert len(status.visible_rows()) == 32
    assert status.plots[0].getViewBox().viewRange()[0] == [4., 8.]


def test_top_toolbar_has_one_row_without_label_or_range_inputs(status):
    """Normal-width pages place the four actions beside time controls, not on another row."""
    app = ensure_app()
    assert not hasattr(status, 'condition_input')
    assert not hasattr(status, 'export_plot_combo')
    labels = [label.text() for label in status.findChildren(QLabel)]
    assert '实验标签' not in labels and '数据导出范围' not in labels
    status.resize(1200, 650)
    status.show()
    app.processEvents()
    app.processEvents()
    from PyQt5.QtCore import QPoint
    reference = status.global_time_cb.mapTo(status, status.global_time_cb.rect().center()).y()
    assert len(status.action_buttons) == 4
    for button in status.action_buttons.values():
        assert abs(button.mapTo(status, button.rect().center()).y()-reference) <= 3
        assert status.rect().contains(button.mapTo(status, QPoint(button.width()-1, button.height()-1)))


def test_small_toolbar_wraps_without_forcing_the_page_wider(status):
    """Narrow pages keep every button reachable and expand the toolbar vertically only."""
    app = ensure_app()
    status.resize(1200, 650)
    status.show()
    app.processEvents()
    status.resize(640, 460)
    app.processEvents()
    app.processEvents()
    assert status.width() == 640, (status.width(), status.minimumSizeHint().width())
    for button in status.action_buttons.values():
        rectangle = button.rect()
        assert status.rect().contains(button.mapTo(status, rectangle.topLeft()))
        assert status.rect().contains(button.mapTo(status, rectangle.bottomRight()))


def test_export_reference_tracks_manual_canvas_and_global_reset(status):
    """Saving uses the last inspected actual viewport; rendering never steals that reference."""
    for second in range(21):
        feed(status, second)
    status.plots[2].setXRange(5., 7., padding=0)
    status._on_manual_view_change('memory_percent')
    assert '内存' in status.action_buttons['save_data'].toolTip()
    feed(status, 21)
    assert [r['time_s'] for r in status.visible_rows()] == [5., 6., 7.]
    status.reset_view()
    assert 'CPU' in status.action_buttons['save_data'].toolTip()
    assert len(status.visible_rows()) == 22
    status.clear_data()
    assert status.visible_rows() == []


def test_short_window_can_scroll_to_all_three_resizable_canvases(status):
    """A small screen exposes a real scrollbar and the third plot, not clipped fixed canvases."""
    app = ensure_app()
    status.resize(640, 460)
    status.show()
    app.processEvents()
    bar = status.scroll_area.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    app.processEvents()
    from PyQt5.QtCore import QPoint
    lower = status.plots[2].mapTo(status.scroll_area.viewport(), QPoint(0, status.plots[2].height()))
    assert lower.y() <= status.scroll_area.viewport().height()+2
    assert status.plot_splitter.count() == 3
    assert not status.plot_splitter.childrenCollapsible()
