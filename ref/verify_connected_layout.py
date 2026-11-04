"""Inspect connected UI geometry using real Windows Qt and synthetic feedback only."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'windows'
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import stereo_runtime
from PyQt5.QtCore import QPoint, QSettings, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QScrollArea, QWidget
from ui.connection_store import ConnectionStore
from ui.main_window import MainWindow
from controllers.xbox import XboxInputState


def settle(app):
    """Run deferred layout passes without opening a network connection."""
    for _ in range(8):
        app.processEvents()


def describe(widget):
    """Record actual geometry and effective minimum hints for one widget."""
    return dict(size=[widget.width(), widget.height()],
        minimum=[widget.minimumWidth(), widget.minimumHeight()],
        hint=[widget.minimumSizeHint().width(), widget.minimumSizeHint().height()])


def main():
    """Reproduce long feedback, narrow sidebars and short windows safely."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--assert-fit', action='store_true')
    parser.add_argument('--baseline', type=Path,
                        help='Read backed-up ui/*.py in memory; never overwrite workspace files')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    personal = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in PROJECT.glob('*.json')}
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Microsoft YaHei UI', 10))
    metrics = []
    window_class = MainWindow
    if args.baseline:
        for name in ('depth_panel', 'visualization', 'main_window'):
            spec = importlib.util.spec_from_file_location('ui.'+name, args.baseline/(name+'.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules['ui.'+name] = module
            setattr(sys.modules['ui'], name, module)
            spec.loader.exec_module(module)
        window_class = sys.modules['ui.main_window'].MainWindow
    with tempfile.TemporaryDirectory() as directory:
        settings_path = str(Path(directory)/'settings.ini')
        settings = QSettings(settings_path, QSettings.IniFormat)
        profiles = ConnectionStore(Path(directory)/'profiles.json')
        with patch('ui.main_window.QSettings', return_value=settings), \
                patch('ui.stereo_camera_widget.QSettings', return_value=settings), \
                patch('ui.main_window.ConnectionStore', return_value=profiles), \
                patch('controllers.xbox.XInputBackend', return_value=Mock(
                    available=False, poll=Mock(return_value=XboxInputState()))), \
                patch('ui.video_display.VideoDisplayWidget._detect_cameras'):
            window = window_class('dual')
        window.setWindowTitle('GroundStation offline layout verification')
        window.video_widget.connect_stream = Mock(return_value=False)
        panel = window.depth_panel
        window._fish_connection_state = 'connected'
        window._apply_main_ui_state()
        window.connection_status_label.setText('已连接（离线模拟）')
        window.connection_time_label.setText('离线模拟')
        window.ip_input.setText('192.168.137.2')
        panel._parent_connection_available = True
        panel._on_connection_status(True, '')
        panel._on_line(dict(type='depth', raw_1=123.456, filtered_1=123.45, fused=123.45))
        panel.calib_status_label.setText('当前零点: +6.663 m')
        window.control_ownership_label.setText('尾鳍：已停止\n胸鳍：单闭环 PID · 1200 μs')
        try:
            window.show()
            settle(app)
            for width, height in ((1600, 1000), (1400, 900), (1280, 720), (1100, 650)):
                window.resize(width, height)
                window.main_splitter.setSizes([370, width-670, 300])
                settle(app)
                row = dict(request=[width, height], actual=describe(window),
                    central=describe(window.centralWidget()),
                    depth_panel=describe(panel), center_tabs=describe(window.center_tabs),
                    center_pages=[describe(window.center_tabs.widget(i)) for i in range(window.center_tabs.count())],
                    right=describe(window.right_panel), status=describe(window.statusBar()),
                    sidebar_sizes=window.main_splitter.sizes())
                row['scrolls'] = [dict(name=scroll.objectName(),
                    range=scroll.verticalScrollBar().maximum(),
                    viewport_height=scroll.viewport().height())
                    for scroll in window.findChildren(QScrollArea)]
                row['status_bottom'] = window.statusBar().mapTo(window, QPoint()).y()+window.statusBar().height()
                window.grab().save(str(output/f'window-{width}x{height}.png'))
                metrics.append(row)
            if args.assert_fit:
                for row in metrics:
                    assert row['actual']['size'][1] <= row['request'][1], row
                    assert row['status_bottom'] <= row['request'][1], row
                assert panel.conn_status_label.width() >= panel.conn_status_label.fontMetrics().horizontalAdvance(panel.conn_status_label.text())
        finally:
            window._fish_connection_state = 'disconnected'
            window.communication = None
            panel._connection_state = 'locked'
            panel._parent_connection_available = False
            window.close()
            settle(app)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in personal.items())
    result = dict(synthetic_only=True, sockets_opened=False, hardware_touched=False,
        dpi=app.primaryScreen().logicalDotsPerInch(),
        device_pixel_ratio=app.primaryScreen().devicePixelRatio(),
        personal_json_unchanged=True, metrics=metrics)
    (output/'metrics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
