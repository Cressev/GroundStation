"""Windows Qt acceptance of parallel depth/pitch controls with fake sensors/transport only."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from unittest.mock import Mock, patch

GS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GS))
import stereo_runtime
from PyQt5.QtCore import QSettings, Qt, QPoint
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont

from communication.base import FishState
from controllers.remote_depth import RemoteParallelDepthController as ParallelDepthController
sys.path.insert(0, str(GS.parents[1]/'gs_bridge'))
from gs_bridge.depth_control import BoardDepthControl
from controllers.xbox import XboxController, XboxInputState, XINPUT_GAMEPAD_X
from ui.main_window import MainWindow
from ui.connection_store import ConnectionStore
from verify_control_axes import FakeTransport


class SensorTransport(FakeTransport):
    """Serve immutable fake sensor snapshots and record composed actuator frames."""

    def __init__(self):
        """Start as a fake connected endpoint with no physical sensor or socket."""
        super().__init__()
        self.state = FishState()
        self.clock = Mock(return_value=100.)
        self.engine = BoardDepthControl(self.clock)

    def send_depth_control(self, request):
        """Simulate the separate Pico service, never any PID call in the desktop proxy."""
        if request['action'] in ('start', 'configure'):
            self.engine.configure(request['mode'], request['params'])
            self.engine.session_id = request['session_id']
            if request['action'] == 'start':
                self.engine.start()
        elif request['action'] == 'stop':
            self.engine.stop()
        self.state.depth_control = self.engine.snapshot()
        return True

    def get_fish_state(self):
        """Return the deliberately prepared sensor frame for production UI ingestion."""
        return self.state


def main():
    """Verify adjacent columns, edit locks, safe composition, timeout and source switching."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--font-size', type=int, default=11)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    configs = [GS/name for name in ('connections.json', 'keyboard_params.json', 'xbox_params.json', 'depth_zero.json')]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in configs}
    app = QApplication([])
    app.setFont(QFont('Microsoft YaHei', args.font_size))
    clock = Mock(return_value=100.)
    parallel = ParallelDepthController(time_source=clock, params_path=output/'parallel-params.json')
    backend = Mock(available=True)
    backend.poll.return_value = XboxInputState(connected=True, controller_index=0)
    xbox = XboxController(backend=backend, time_source=clock)
    xbox._poll_timer.stop()
    settings = QSettings(str(output/'settings.ini'), QSettings.IniFormat)
    with patch('ui.main_window.QSettings', return_value=settings), \
            patch('ui.stereo_camera_widget.QSettings', return_value=settings), \
            patch('ui.main_window.ConnectionStore', return_value=ConnectionStore(output/'profiles.json')), \
            patch('ui.main_window.ParallelDepthController', return_value=parallel), \
            patch('ui.main_window.XboxController', return_value=xbox):
        window = MainWindow('dual')
    transport = SensorTransport()
    stages = []

    def capture(name):
        """Save both full window and complete depth view with measured column geometry."""
        app.processEvents()
        position = window.depth_group.mapTo(window.axis_control_scroll.widget(), QPoint(0, 0))
        window.axis_control_scroll.verticalScrollBar().setValue(position.y())
        window.axis_control_scroll.horizontalScrollBar().setValue(0)
        app.processEvents()
        left, right = parallel._loop_groups['depth'], parallel._loop_groups['pitch']
        assert left.y() == right.y() and left.x() + left.width() <= right.x()
        window.grab().save(str(output/(name+'.png')))
        parallel.get_control_widget().grab().save(str(output/(name+'_parameters.png')))
        stages.append(dict(name=name, heading=window.axis_coordinator.heading_enabled,
                           depth=window.axis_coordinator.depth_enabled,
                           depth_type=window.depth_controller_combo.currentData(),
                           columns=[dict(x=g.x(), y=g.y(), width=g.width()) for g in (left, right)],
                           last_command=transport.commands[-1] if transport.commands else None))

    def click(checkbox):
        """Use real mouse input while keeping all generated commands on a fake transport."""
        window.axis_control_scroll.ensureWidgetVisible(checkbox, 0, 20)
        app.processEvents()
        QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(8, checkbox.height()//2))
        parallel._update_timer.stop()
        window.controllers['keyboard']._update_timer.stop()

    def sample(identity, pitch=5.):
        """Feed both source identities through the production UI snapshot routing."""
        state = transport.state
        state.timestamp = 1000. + identity
        state.depth = dict(fused=window.depth_panel.zero_offset + 10.)
        state.orientation = dict(roll=0., pitch=math.radians(pitch), yaw=0.)
        state.depth_sample = dict(id='d'+str(identity), received_at=clock.return_value, age_s=0.)
        state.imu_sample = dict(id='i'+str(identity), received_at=clock.return_value, age_s=0.)
        transport.clock.return_value = clock.return_value
        transport.engine.update('depth', state.depth['fused'], 'd'+str(identity))
        transport.engine.update('pitch', pitch, 'i'+str(identity))
        transport.engine.tick()
        state.depth_control = transport.engine.snapshot()
        window._update_data()
        parallel._update_control()

    try:
        window.setWindowTitle('并联双闭环离线验收 · 假传感器/假通信 · 不控制机器鱼')
        window.resize(1760, 1000)
        window.show()
        app.processEvents()
        window.main_splitter.setSizes([760, 760, 240])
        window.communication = transport
        window._fish_connection_state = 'connected'
        window._apply_main_ui_state()
        window.depth_controller_combo.setCurrentIndex(window.depth_controller_combo.findData('parallel_pid'))
        assert not parallel._loop_inputs['depth']['kp'].isEnabled()
        capture('01_stopped')
        click(window.depth_enable_checkbox)
        assert parallel._loop_inputs['depth']['kp'].isEnabled()
        parallel._loop_inputs['depth']['target'].setValue(20.)
        parallel._loop_inputs['depth']['kp'].setValue(10.)
        parallel._loop_inputs['pitch']['kp'].setValue(2.)
        assert parallel._apply_depth_parameters()
        sample(1)
        assert window.axis_coordinator.last_pwm == 1410
        click(window.heading_enable_checkbox)
        keyboard = window.controllers['keyboard']
        keyboard.handle_key_press('w')
        keyboard._update_control()
        assert transport.commands[-1]['tail_amplitude'] > 0
        capture('02_keyboard_parallel')
        clock.return_value += .6
        transport.clock.return_value = clock.return_value
        transport.engine.tick()
        transport.state.depth_control = transport.engine.snapshot()
        window._update_data()
        assert window.axis_coordinator.last_pwm == 1500
        assert transport.commands[-1]['tail_amplitude'] > 0
        capture('03_sensor_timeout')
        click(window.depth_enable_checkbox)
        assert not parallel._loop_inputs['pitch']['kp'].isEnabled()
        capture('04_depth_stopped')
        click(window.heading_enable_checkbox)
        window.controller_combo.setCurrentIndex(window.controller_combo.findData('xbox'))
        click(window.heading_enable_checkbox)
        click(window.depth_enable_checkbox)
        clock.return_value += .1
        sample(2)
        backend.poll.return_value = XboxInputState(connected=True, controller_index=0, buttons=XINPUT_GAMEPAD_X)
        xbox._poll_controller()
        assert not window.axis_coordinator.heading_enabled and not window.axis_coordinator.depth_enabled
        capture('05_xbox_emergency')
        window.depth_controller_combo.setCurrentIndex(0)
        assert window.axis_coordinator.depth is window.controllers['depth']
        assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in configs}
        result = dict(qt_platform=app.platformName(), stages=stages, commands=transport.commands,
                      board_commands_sent=0, user_configs_unchanged=True, two_columns=True)
        (output/'summary.json').write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')
        print(json.dumps(dict(qt_platform=app.platformName(), stages=len(stages), two_columns=True,
                              board_commands_sent=0, user_configs_unchanged=True)))
    finally:
        window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
