"""Verify compact time legends in real Windows Qt with synthetic data only."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['QT_QPA_PLATFORM'] = 'windows'
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import stereo_runtime
import numpy as np
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication
from ui.visualization import DataVisualizationWidget


def settle(app):
    """Flush several deferred Qt/graphics layout passes without touching a connection."""
    for _ in range(4):
        app.processEvents()


def main():
    """Capture the tab order and legends, validating native export and stable anchors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    output = Path(parser.parse_args().output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    personal = ['connections.json', 'depth_zero.json', 'keyboard_params.json', 'xbox_params.json']
    before = {name: hashlib.sha256((PROJECT/name).read_bytes()).hexdigest() for name in personal}
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Microsoft YaHei UI', 10))
    view = DataVisualizationWidget()
    view.update_timer.stop()
    try:
        for second in range(31):
            for index, (key, values) in enumerate(view.data_history.items()):
                values.append(float(second) if key == 'time' else 12+index*.3+np.sin(second*.3))
        x = np.linspace(0, 30, 301)
        for index, curve in enumerate([view.z_curve, *view._depth_curves.values()]):
            curve.setData(x, 10+index*2+np.sin(x*.5+index*.2))
        for index, curve in enumerate([view.roll_curve, view.pitch_curve, view.yaw_curve]):
            curve.setData(x, np.sin(x*.3+index)*20)
        view.z_plot.setXRange(0, 30, padding=0)
        view.z_plot.setYRange(7, 24, padding=0)
        view.rpy_plot.setYRange(-25, 25, padding=0)
        view.resize(1200, 900)
        view.show()
        settle(app)
        assert [view.tab_widget.tabText(i) for i in range(4)] == ['时间序列', 'XY轨迹图', '姿态显示', '系统状态']
        assert view.tab_widget.currentIndex() == 0
        view.grab().save(str(output/'time-series-1200.png'))
        view.export_time_series_png(str(output/'canvas.png'))
        view.z_plot.grab().save(str(output/'depth-legend.png'))
        view.rpy_plot.grab().save(str(output/'attitude-legend.png'))
        metrics = []
        for width in (1200, 760):
            view.resize(width, 900)
            settle(app)
            for name, plot in [('depth', view.z_plot), ('attitude', view.rpy_plot)]:
                legend = plot.plotItem.legend
                origin = legend.mapToParent(QPointF())
                assert abs(origin.x()-6) <= 1 and abs(origin.y()-6) <= 1
                metrics.append(dict(window_width=width, legend=name, x=origin.x(), y=origin.y(),
                    width=legend.boundingRect().width(), height=legend.boundingRect().height(),
                    labels=[label.text for sample, label in legend.items]))
        view.grab().save(str(output/'time-series-760.png'))
        view.follow_latest = False
        view.z_plot.setXRange(7.2, 12.8, padding=0)
        settle(app)
        view.export_visible_time_series(str(output/'visible.csv'))
        with (output/'visible.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        assert [float(row['time_s']) for row in rows] == [8., 9., 10., 11., 12.]
        assert all(hashlib.sha256((PROJECT/name).read_bytes()).hexdigest() == digest for name, digest in before.items())
        result = dict(synthetic_data=True, sockets_opened=False, hardware_touched=False,
            qt_platform=app.platformName(), tab_order=[view.tab_widget.tabText(i) for i in range(4)],
            legend_metrics=metrics, exported_rows=len(rows), personal_files_unchanged=True)
        (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))
    finally:
        view.close()


if __name__ == '__main__':
    main()
