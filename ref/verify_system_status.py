"""Verify a real Windows system-status canvas with synthetic data only, without any socket."""

import argparse
import csv
import json
import math
import hashlib
from pathlib import Path
import sys
import time
from unittest.mock import patch

GS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GS))
import stereo_runtime
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QSettings, QPoint
from PyQt5.QtWidgets import QApplication, QLabel
from ui.main_window import MainWindow
from ui.stereo_camera_widget import StereoFishCameraWidget
from ui.connection_store import ConnectionStore
from ui.system_status import SystemStatusWidget
import numpy as np


def main():
    """Render half-hour synthetic traces, verify visible CSV/XLSX/PNG and preserve all history."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    app.setFont(QFont('Microsoft YaHei', 10))
    configs = [GS/name for name in ('connections.json', 'keyboard_params.json', 'xbox_params.json', 'depth_zero.json')]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in configs]
    settings = QSettings(str(output/'settings.ini'), QSettings.IniFormat)
    with patch('ui.main_window.QSettings', return_value=settings), \
            patch('ui.stereo_camera_widget.QSettings', return_value=settings), \
            patch('ui.main_window.ConnectionStore', return_value=ConnectionStore(output/'profiles.json')):
        window = MainWindow('dual')
    page = window.system_status_widget
    window.resize(1900, 1000)
    window.setWindowTitle('系统状态离线验收 · 演示数据，非实测 · 不连接机器鱼')
    window.visualization_widget.tab_widget.setCurrentWidget(page)
    assert not hasattr(page, 'condition_input') and not hasattr(page, 'export_plot_combo')
    page.set_connected(True)
    origin = time.monotonic()-1800.
    try:
        with patch.object(page, '_render'), patch.object(page, '_refresh_status'):
            for index in range(3601):
                second = index/2.
                if 1200. < second < 1220.:
                    continue
                page.add_sample(dict(cpu_percent=25.+7.*math.sin(second/70.),
                    soc_temp_c=42.+24.*(1.-math.exp(-second/500.)),
                    mem_used_mb=1050.+second/20., mem_total_mb=4096., cpu_freq_mhz=1800.),
                    received_at=origin+second, source_timestamp=1700000000.+second)
        window.show()
        page._render()
        page._refresh_status()
        app.processEvents()
        page.grab().save(str(output/'system-status-global.png'))
        window.grab().save(str(output/'nested-system-status.png'))
        page.scroll_area.verticalScrollBar().setValue(page.scroll_area.verticalScrollBar().maximum())
        app.processEvents()
        page.grab().save(str(output/'system-status-scroll-bottom.png'))
        page.export_png(output/'canvas-global.png')
        page.sliding_time_cb.setChecked(True)
        page.sliding_window_input.setValue(300)
        assert page.visible_rows()[0]['time_s'] == 1500.
        page.grab().save(str(output/'system-status-sliding.png'))
        page.plots[0].setXRange(600., 900., padding=0)
        page._on_manual_view_change('cpu_percent')
        assert page.plots[1].getViewBox().viewRange()[0] == [1500., 1800.]
        app.processEvents()
        _, count = page.export_data(output/'visible.csv')
        page.export_data(output/'visible.xlsx')
        page.export_png(output/'canvas-visible.png')
        assert count == 601
        with (output/'visible.csv').open(encoding='utf-8-sig', newline='') as stream:
            saved = list(csv.DictReader(stream))
        assert saved[0]['time_s'] == '600.0' and saved[-1]['time_s'] == '900.0'
        assert 'condition' not in saved[0]
        page.plots[1].setXRange(700., 750., padding=0)
        page._on_manual_view_change('soc_temp_c')
        assert page.visible_rows()[0]['time_s'] == 700.
        assert page.visible_rows()[-1]['time_s'] == 750.
        assert '温度' in page.action_buttons['save_data'].toolTip()
        page.reset_view()
        assert len(page.rows) == 3563
        page.set_connected(False)
        page.grab().save(str(output/'system-status-disconnected.png'))
        compact = SystemStatusWidget()
        toolbar_geometry = []
        try:
            compact.set_connected(True)
            for row in page.rows:
                compact.rows.append(row.copy())
            for width in (1200, 640):
                compact.resize(width, 650 if width == 1200 else 460)
                compact.show()
                compact._render()
                app.processEvents()
                app.processEvents()
                assert compact.width() == width, (width, compact.width(), compact.minimumSizeHint().width())
                assert compact.scroll_area.verticalScrollBar().maximum() > 0
                labels = [label.text() for label in compact.findChildren(QLabel)]
                assert '实验标签' not in labels and '数据导出范围' not in labels
                reference = compact.global_time_cb.mapTo(compact, compact.global_time_cb.rect().center()).y()
                button_centers = []
                for button in compact.action_buttons.values():
                    assert compact.rect().contains(button.mapTo(compact, button.rect().topLeft()))
                    assert compact.rect().contains(button.mapTo(compact, button.rect().bottomRight()))
                    button_centers.append(button.mapTo(compact, button.rect().center()).y())
                if width == 1200:
                    assert all(abs(center-reference) <= 3 for center in button_centers)
                toolbar_geometry.append(dict(width=width, wrapped=compact._toolbar_wrapped,
                                             mode_center_y=reference, action_center_y=button_centers))
                compact.grab().save(str(output/f'compact-toolbar-{width}.png'))
        finally:
            compact.status_timer.stop()
            compact.close()
        centered = []
        with patch('ui.stereo_camera_widget.QSettings', return_value=settings):
            video = StereoFishCameraWidget()
        try:
            frame = np.full((640, 480, 3), (90, 160, 210), np.uint8)
            frame[16:-16, 16:-16] = (80, 90, 110)
            for width in (640, 1000):
                video.resize(width, 800)
                video.show()
                video.video_label.set_frame(frame)
                app.processEvents()
                app.processEvents()
                video.page_scroll.ensureWidgetVisible(video.video_label, 0, 0)
                app.processEvents()
                viewport = video.page_scroll.viewport()
                origin = video.video_label.mapTo(viewport, QPoint(0, 0))
                x, _, w, _ = video.video_label.image_rectangle()
                error = origin.x()+x+w/2.-viewport.width()/2.
                assert abs(error) <= 2. and video.page_scroll.horizontalScrollBar().maximum() == 0
                centered.append(dict(width=width, center_error_px=error))
                video.grab().save(str(output/f'video-centered-{width}.png'))
        finally:
            video.shutdown()
            video.close()
        assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in configs]
        result = dict(platform=app.platformName(), synthetic_only=True, physical_commands=0,
                      history_rows=len(page.rows), visible_export_rows=count,
                      export_range_s=[600, 900], gap_rows=sum(r['status']=='gap' for r in page.rows),
                      plots=3, no_personal_config_writes=True, nested_system_tab=True,
                      independent_canvases=True, vertical_scroll=True, video_centered=centered,
                      annotation_removed=True, export_selector_removed=True,
                      automatic_export_reference=True, toolbar_geometry=toolbar_geometry)
        (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        page.status_timer.stop()
        window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
