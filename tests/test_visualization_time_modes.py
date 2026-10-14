#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间序列全局/滑动窗口模式的离线回归测试。"""

import csv
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from ui.visualization import DataVisualizationWidget


_APP = None


def ensure_app():
    """创建并持有唯一 QApplication。"""
    global _APP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _APP = app
    return app


def populate_history(widget, seconds):
    """直接填入从 0 到 seconds 的每秒测试点。"""
    for second in range(seconds + 1):
        widget.data_history["time"].append(float(second))
        for key in ("x", "y", "z", "roll", "pitch", "yaw"):
            widget.data_history[key].append(float(second))
        for key in ("d_raw1", "d_raw2", "d_filt1", "d_filt2", "d_cal"):
            widget.data_history[key].append(float(second))


def test_global_mode_keeps_complete_history_independent_of_sliding_window():
    """滑动窗口只影响显示，切回全局后必须恢复全部数据。"""
    ensure_app()
    widget = DataVisualizationWidget()
    widget.update_timer.stop()
    populate_history(widget, 30)

    widget._update_plots()
    global_x, _ = widget.z_curve.getData()
    assert global_x[0] == 0.0
    assert global_x[-1] == 30.0
    assert len(global_x) == 31

    widget.sliding_window_input.setValue(10)
    widget.sliding_time_cb.setChecked(True)
    sliding_x, _ = widget.z_curve.getData()
    assert sliding_x[0] == 20.0
    assert sliding_x[-1] == 30.0
    assert widget.sliding_window_input.isEnabled()

    widget.follow_latest = False
    widget.global_time_cb.setChecked(True)
    restored_x, _ = widget.z_curve.getData()
    assert restored_x[0] == 0.0
    assert restored_x[-1] == 30.0
    assert widget.follow_latest
    assert not widget.sliding_window_input.isEnabled()
    widget.close()


def test_reselecting_time_modes_is_idempotent():
    """重复选择同一时间模式不得改变最终状态。"""
    ensure_app()
    widget = DataVisualizationWidget()
    widget.update_timer.stop()

    widget.global_time_cb.setChecked(True)
    widget.global_time_cb.setChecked(True)
    assert widget.global_time_cb.isChecked()
    assert not widget.sliding_time

    widget.sliding_time_cb.setChecked(True)
    widget.sliding_time_cb.setChecked(True)
    assert widget.sliding_time_cb.isChecked()
    assert widget.sliding_time
    widget.close()


def test_visible_range_export_contains_only_canvas_depth_and_attitude_data():
    """用户缩放后只导出当前可见时间内的深度和姿态角。"""
    app = ensure_app()
    widget = DataVisualizationWidget()
    widget.update_timer.stop()
    populate_history(widget, 30)
    widget._update_plots()

    widget.follow_latest = False
    widget.z_plot.setXRange(7.2, 12.8, padding=0)
    app.processEvents()
    rows = widget.current_visible_time_series_rows()
    assert [row["time_s"] for row in rows] == [8.0, 9.0, 10.0, 11.0, 12.0]
    assert rows[0]["depth_calibrated_cm"] == 8.0
    assert rows[-1]["roll_rad"] == 12.0
    assert widget.rpy_plot.getViewBox().viewRange()[0] == \
        widget.z_plot.getViewBox().viewRange()[0]

    with tempfile.TemporaryDirectory() as directory:
        csv_path = Path(directory) / "visible.csv"
        saved_csv, count, start, end = widget.export_visible_time_series(csv_path)
        assert Path(saved_csv).exists()
        assert (count, start, end) == (5, 8.0, 12.0)
        with Path(saved_csv).open("r", encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        assert len(csv_rows) == 5
        assert csv_rows[0]["time_s"] == "8.0"
        assert "depth_filtered_1_cm" in csv_rows[0]
        assert "yaw_rad" in csv_rows[0]

        xlsx_path = Path(directory) / "visible.xlsx"
        saved_xlsx, count, start, end = widget.export_visible_time_series(xlsx_path)
        assert Path(saved_xlsx).exists()
        assert zipfile.is_zipfile(saved_xlsx)
        assert (count, start, end) == (5, 8.0, 12.0)
    widget.close()


def test_export_dialog_extensions_follow_selected_format():
    """文件对话框中选择的格式决定缺省后缀。"""
    assert DataVisualizationWidget._normalize_data_export_path(
        "test_export", "CSV 文件 (*.csv)").endswith(".csv")
    assert DataVisualizationWidget._normalize_data_export_path(
        "test_export", "Excel 工作簿 (*.xlsx)").endswith(".xlsx")
    assert DataVisualizationWidget._normalize_png_path(
        "time_series_canvas").endswith(".png")
