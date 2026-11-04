"""Verify sidebar folding in a real Windows Qt window without any board connection."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

GS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GS))
import stereo_runtime
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from ui.connection_store import ConnectionStore
from ui.main_window import MainWindow


def main():
    """Save three screenshots and check widths, restart memory and personal hashes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    app.setFont(QFont('Microsoft YaHei', 10))
    configs = [GS/name for name in (
        'connections.json', 'keyboard_params.json', 'xbox_params.json', 'depth_zero.json')]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in configs]
    settings = QSettings(str(output/'settings.ini'), QSettings.IniFormat)
    created = []

    def make_window():
        """Create a disconnected window with isolated settings and no camera scan."""
        with patch('ui.main_window.QSettings', return_value=settings), \
                patch('ui.stereo_camera_widget.QSettings', return_value=settings), \
                patch('ui.main_window.ConnectionStore',
                      return_value=ConnectionStore(output/'profiles.json')):
            window = MainWindow('dual')
        created.append(window)
        window.resize(1360, 800)
        window.setWindowTitle('右侧栏收放验收 · 离线，不连接机器鱼')
        window.show()
        app.processEvents()
        return window

    try:
        window = make_window()
        window.main_splitter.setSizes([420, 600, 300])
        window.right_tabs.setCurrentIndex(1)
        window.info_text.setPlainText('离线验收：收起侧栏不关闭服务，展开后保留当前页和日志。')
        app.processEvents()
        expanded = window.main_splitter.sizes()
        assert window.grab().save(str(output/'expanded.png'))
        QTest.mouseClick(window.right_sidebar_toggle, Qt.LeftButton)
        app.processEvents()
        collapsed = window.main_splitter.sizes()
        assert collapsed[0] == expanded[0] and collapsed[2] == 28
        assert collapsed[1] - expanded[1] == expanded[2] - 28
        assert window.grab().save(str(output/'collapsed.png'))
        window.close()
        restored = make_window()
        assert restored._right_sidebar_collapsed
        assert restored.main_splitter.sizes()[2] == 28
        restored.right_sidebar_toggle.setFocus()
        QTest.keyClick(restored.right_sidebar_toggle, Qt.Key_Space)
        app.processEvents()
        reopened = restored.main_splitter.sizes()
        assert abs(reopened[2] - expanded[2]) <= 2
        assert restored.grab().save(str(output/'reopened.png'))
        result = dict(expanded=expanded, collapsed=collapsed, reopened=reopened,
                      restart_restored=True, keyboard_toggle=True, hardware_connected=False)
    finally:
        for window in created:
            window.close()
        app.processEvents()
    after = [hashlib.sha256(path.read_bytes()).hexdigest() for path in configs]
    assert before == after
    result['personal_configs_unchanged'] = True
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
