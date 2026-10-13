#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间序列全局/滑动窗口模式的离线回归测试。"""

import os
import sys

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
