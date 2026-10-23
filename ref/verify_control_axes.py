"""True Windows Qt acceptance flow with fake telemetry, fake Xbox and fake transport only."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

GS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GS))
import stereo_runtime
from PyQt5.QtCore import QPoint, QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QAbstractSpinBox

from controllers.depth_axis import DepthAxisController
from controllers.xbox import XboxController, XboxInputState, XINPUT_GAMEPAD_X
from ui.connection_store import ConnectionStore
from ui.main_window import MainWindow


class FakeTransport:
    """Record copied serialized commands without opening a socket."""

    def __init__(self):
        """Provide a connected in-memory endpoint for UI command gates."""
        self.connected = True
        self.commands = []

    def send_control_command(self, command):
        """Store every final actuator frame for inspection after widget cleanup."""
        self.commands.append({key: getattr(command, key) for key in
            ('tail_frequency', 'tail_amplitude', 'tail_offset', 'tail_phase_diff', 'pec_angle')})
        return True

    def disconnect(self):
        """Support normal production cleanup with no network effects."""
        self.connected = False


def main():
    """Exercise independent start/stop, source switching and real Xbox emergency wiring."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--sidebar-width', type=int, default=460)
    parser.add_argument('--font-size', type=int)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    config_files = [GS/name for name in ('connections.json', 'keyboard_params.json', 'xbox_params.json', 'depth_zero.json')]
    fingerprints = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in config_files}
    app = QApplication([])
    if args.font_size is not None:
        app.setFont(QFont('Microsoft YaHei', args.font_size))
    settings = QSettings(str(output/'settings.ini'), QSettings.IniFormat)
    clock = Mock(return_value=100.)
    backend = Mock(available=True)
    backend.poll.return_value = XboxInputState(connected=True, controller_index=0)
    backend.set_vibration.return_value = True
    xbox = XboxController(backend=backend, time_source=clock)
    xbox._poll_timer.stop()
    depth = DepthAxisController(time_source=clock, params_path=output/'unused-depth.json')
    depth._depth_params.update(target_depth=20., kp=10., ki=0., kd=0., direction=-1,
        neutral_pwm=1500, minimum_pwm=500, maximum_pwm=2500)
    depth._pid.configure(10, 0, 0, 1000)
    with patch('ui.main_window.QSettings', return_value=settings), \
            patch('ui.stereo_camera_widget.QSettings', return_value=settings), \
            patch('ui.main_window.ConnectionStore', return_value=ConnectionStore(output/'profiles.json')), \
            patch('ui.main_window.XboxController', return_value=xbox), \
            patch('ui.main_window.DepthAxisController', return_value=depth):
        window = MainWindow('dual')
    transport = FakeTransport()
    stages = []

    def capture(name, target=None):
        """Capture the current visible control section and exact axis ownership."""
        if target is not None:
            position = target.mapTo(window.axis_control_scroll.widget(), QPoint(0, 0))
            window.axis_control_scroll.verticalScrollBar().setValue(max(0, position.y()-8))
            window.axis_control_scroll.horizontalScrollBar().setValue(0)
        app.processEvents()
        assert window.controller_widget_container.isEnabled() == window.axis_coordinator.heading_enabled
        assert window.depth_widget_container.isEnabled() == window.axis_coordinator.depth_enabled
        assert depth._kp_input.isEnabled() == window.axis_coordinator.depth_enabled
        assert depth._apply_pid_button.isEnabled() == window.axis_coordinator.depth_enabled
        for spin in window.current_controller.get_control_widget().findChildren(QAbstractSpinBox):
            assert spin.lineEdit().contentsRect().width() >= spin.fontMetrics().horizontalAdvance(spin.text()), spin.text()
        assert window.grab().save(str(output/(name+'.png')))
        group = window.depth_group if target is window.depth_group else window.heading_group
        assert group.grab().save(str(output/(name+'_controls.png')))
        stages.append(dict(name=name, heading=window.axis_coordinator.heading_name,
            heading_enabled=window.axis_coordinator.heading_enabled,
            depth_enabled=window.axis_coordinator.depth_enabled,
            heading_parameters_enabled=window.controller_widget_container.isEnabled(),
            depth_parameters_enabled=depth._kp_input.isEnabled(),
            numeric_layout=[dict(text=spin.text(), width=spin.width(),
                text_width=spin.fontMetrics().horizontalAdvance(spin.text()),
                editor_width=spin.lineEdit().contentsRect().width(),
                size_hint=spin.sizeHint().width(), minimum_hint=spin.minimumSizeHint().width())
                for spin in group.findChildren(QAbstractSpinBox)],
            last_command=transport.commands[-1] if transport.commands else None))

    def click_checkbox(checkbox):
        """Use an actual mouse click on the indicator, after scrolling it into view."""
        window.axis_control_scroll.ensureWidgetVisible(checkbox, 0, 20)
        app.processEvents()
        QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(8, checkbox.height()//2))
        app.processEvents()

    try:
        window.setWindowTitle('离线界面验收 · 假通信/假手柄 · 不连接机器鱼')
        window.resize(1760, 1000)
        window.show()
        app.processEvents()
        window.main_splitter.setSizes([args.sidebar_width, 980, 300])
        capture('01_idle')
        assert not transport.commands
        window.communication = transport
        window._fish_connection_state = 'connected'
        window.connection_status_label.setText('离线假连接（未连接机器鱼）')
        window._apply_main_ui_state()
        window._log_message('仅本地假通信验收，未连接机器鱼/相机')
        click_checkbox(window.heading_enable_checkbox)
        assert window.axis_coordinator.heading_enabled
        keyboard = window.controllers['keyboard']
        keyboard.handle_key_press('w')
        keyboard._update_control()
        click_checkbox(window.depth_enable_checkbox)
        assert window.axis_coordinator.depth_enabled
        depth.update_depth(10., 1)
        depth._update_control()
        assert transport.commands[-1]['tail_amplitude'] > 0
        assert transport.commands[-1]['pec_angle'] == 1400
        capture('02_keyboard_pid_heading', window.heading_group)
        capture('03_keyboard_pid_depth', window.depth_group)
        click_checkbox(window.heading_enable_checkbox)
        assert window.axis_coordinator.depth_enabled and not window.axis_coordinator.heading_enabled
        assert transport.commands[-1]['tail_amplitude'] == 0
        capture('04_depth_only', window.depth_enable_checkbox)
        window.controller_combo.setCurrentIndex(window.controller_combo.findData('xbox'))
        click_checkbox(window.heading_enable_checkbox)
        backend.poll.return_value = replace(backend.poll.return_value, left_y=1.)
        clock.return_value += .1
        xbox._poll_controller()
        clock.return_value += .1
        depth.update_depth(12., 2)
        depth._update_control()
        assert transport.commands[-1]['tail_amplitude'] > 0
        assert transport.commands[-1]['pec_angle'] == 1420
        capture('05_xbox_pid_heading', window.heading_group)
        capture('06_xbox_pid_depth', window.depth_group)
        backend.poll.return_value = replace(backend.poll.return_value, buttons=XINPUT_GAMEPAD_X)
        xbox._poll_controller()
        assert not window.axis_coordinator.heading_enabled and not window.axis_coordinator.depth_enabled
        assert transport.commands[-1]['tail_amplitude'] == 0 and transport.commands[-1]['pec_angle'] == 1420
        count = len(transport.commands)
        depth._update_control()
        keyboard._update_control()
        assert len(transport.commands) == count
        capture('07_emergency', window.heading_enable_checkbox)
        assert fingerprints == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in config_files}
        summary = dict(qt_platform=app.platformName(), stages=stages, commands=transport.commands,
            network_opened=False, board_commands_sent=0, user_config_unchanged=True,
            vibration_is_mock=True, video_opened=False)
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding='utf-8')
        print(json.dumps(dict(qt_platform=app.platformName(), stages=len(stages),
            fake_commands=len(transport.commands), user_config_unchanged=True)))
    finally:
        window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
