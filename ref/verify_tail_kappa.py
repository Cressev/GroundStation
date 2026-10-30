"""Render both real Windows parameter panels with isolated settings and fake Xbox."""
from pathlib import Path
import sys
from unittest.mock import Mock, patch

GS = Path(__file__).resolve().parents[1]
ROOT = GS.parents[1]
sys.path.insert(0, str(GS))

from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from controllers.base import KeyboardController
from controllers.xbox import XboxController


def main():
    """Capture actual Qt widgets without connecting to a fish or changing saved settings."""
    output = ROOT / 'docs/test-reports/stm32/kappa_20261028_2043/assets'
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont('Microsoft YaHei', 9))
    with patch('controllers.base.PARAMS_FILE', str(output/'unused-keyboard.json')):
        keyboard = KeyboardController()
    keyboard.set_keyboard_parameters(0, 1, .1745, .1, 2, .3, .2, .7854, .3)
    widget = keyboard.get_control_widget()
    keyboard.activate()
    keyboard.handle_key_press('w')
    keyboard._update_control()
    widget.resize(500, 1060)
    widget.setWindowTitle('快摆慢回参数验收（假通信）')
    widget.show()
    QTest.qWait(150)
    assert keyboard._param_inputs['tail_kappa'].value() == .3
    assert widget.grab().save(str(output/'keyboard-kappa.png'))
    keyboard.deactivate()
    widget.close()
    with patch('controllers.xbox.PARAMS_FILE', str(output/'unused-xbox.json')):
        xbox = XboxController(backend=Mock(available=True))
    xbox._poll_timer.stop()
    xbox._parameters['tail_kappa'] = .7
    panel = xbox.get_control_widget()
    panel.resize(500, 1060)
    panel.setWindowTitle('Xbox快慢比例验收（假手柄）')
    panel.show()
    QTest.qWait(150)
    assert xbox._parameter_inputs['tail_kappa'].value() == .7
    assert panel.grab().save(str(output/'xbox-kappa.png'))
    panel.close()
    xbox._vibration_timer.stop()
    print('Two Windows Qt panels captured; no real fish connection or parameter writes')


if __name__ == '__main__':
    main()
