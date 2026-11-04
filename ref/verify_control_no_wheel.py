"""Real-window, offline verification of all controller number fields without fish commands."""

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stereo_runtime
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QAbstractSpinBox, QHBoxLayout, QScrollArea, QWidget

from controllers.base import KeyboardController
from controllers.depth import DepthController
from controllers.xbox import XboxController


def main():
    """Show all three inactive panels and verify wheel scrolling plus deliberate editing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    root = QWidget()
    root.setWindowTitle('离线控制栏验证 · 滚轮只滚页面 · 不连接/不控制机器鱼')
    layout = QHBoxLayout(root)
    controllers = [KeyboardController(), DepthController(params_path=output/'unused-depth.json'),
                   XboxController(backend=Mock())]
    controllers[-1]._poll_timer.stop()
    areas, rows, commands = [], [], []
    for controller in controllers:
        controller.control_command_generated.connect(commands.append)
        widget = controller.get_control_widget()
        if isinstance(controller, DepthController):
            controller._parameter_unlock_checkbox.setChecked(True)
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setMinimumWidth(360)
        layout.addWidget(area)
        areas.append(area)
    root.resize(1900, 700)
    root.show()
    app.processEvents()
    try:
        for controller, area in zip(controllers, areas):
            for index, spin in enumerate(area.widget().findChildren(QAbstractSpinBox)):
                original = spin.value()
                area.ensureWidgetVisible(spin)
                spin.setFocus()
                app.processEvents()
                bar = area.verticalScrollBar()
                before = bar.value()
                delta = 120 if before > 0 else -120
                point = spin.lineEdit().rect().center()
                event = QWheelEvent(QPointF(point), QPointF(spin.lineEdit().mapToGlobal(point)),
                    QPoint(), QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                QApplication.sendEvent(spin.lineEdit(), event)
                app.processEvents()
                assert spin.value() == original
                assert bar.value() != before
                # Set a middle value so the step can be tested even at original min/max.
                baseline = spin.minimum()+(spin.maximum()-spin.minimum())/2
                if hasattr(spin, 'decimals'):
                    spin.setValue(baseline)
                else:
                    spin.setValue(int(baseline))
                baseline = spin.value()
                QTest.keyClick(spin, Qt.Key_Up)
                assert abs(spin.value()-baseline-spin.singleStep()) < .000001
                QTest.keyClick(spin, Qt.Key_Down)
                assert abs(spin.value()-baseline) < .000001
                spin.lineEdit().selectAll()
                QTest.keyClicks(spin.lineEdit(), str(spin.minimum()))
                QTest.keyClick(spin.lineEdit(), Qt.Key_Return)
                assert spin.value() == spin.minimum()
                spin.setValue(original)
                rows.append(dict(controller=type(controller).__name__, index=index,
                    value=original, wheel_unchanged=True, page_scrolled=True,
                    keyboard_arrows=True, direct_edit=True))
            area.verticalScrollBar().setValue(0)
        assert len(rows) == 40 and not commands
        app.processEvents()
        assert root.grab().save(str(output/'panels.png'))
        summary = dict(qt_platform=app.platformName(), checks=rows, command_count=len(commands),
                       hardware_connected=False, parameters_saved=False)
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding='utf-8')
        print(json.dumps(dict(qt_platform=app.platformName(), controls=len(rows), commands=len(commands))))
    finally:
        root.close()
        app.processEvents()


if __name__ == '__main__':
    main()
