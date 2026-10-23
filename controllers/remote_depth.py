"""Display/configuration proxies only: depth PID arithmetic executes exclusively on Pico."""

import json
import time
import uuid

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFormLayout

from controllers.depth_axis import DepthAxisController
from controllers.parallel_depth import ParallelDepthController


class _RemoteDepthProxy:
    """Share remote lifecycle and feedback rendering without generating actuator frames."""

    def _remote_init(self, mode):
        """Initialize request/session gates; a Qt timer only watches board acknowledgement age."""
        self.remote_mode = mode
        self.remote_sender = None
        self.remote_session = None
        self._remote_last_seen = 0.
        self._remote_request_number = 0

    def _request_remote(self, action):
        """Send configuration/intent, never a locally computed pectoral PWM."""
        if self.remote_sender is None:
            return False
        self._remote_request_number += 1
        return self.remote_sender(dict(type='depth_control', action=action, mode=self.remote_mode,
            params=self.remote_parameters(), session_id=self.remote_session, request_id=self._remote_request_number))

    def activate(self):
        """Request a board-local start and await a matching board session acknowledgement."""
        if self._active:
            return True
        self.remote_session = uuid.uuid4().hex
        self._active = self._pid_enabled = True
        self._remote_last_seen = time.monotonic()
        if not self._request_remote('start'):
            self._active = self._pid_enabled = False
            self._set_pid_status('Pico定深启动请求发送失败')
            return False
        self._set_pid_status('等待Pico确认；控制器在Pico计算')
        self._update_timer.start(100)
        return True

    def deactivate(self):
        """Revoke local authority first, then request board stop while retaining last actual PWM."""
        was_active = self._active
        self._active = self._pid_enabled = False
        self._update_timer.stop()
        if was_active:
            self._request_remote('stop')
        self._set_pid_status('Pico定深控制已停止')
        return True

    def _update_control(self):
        """Watch remote acknowledgement only; never call PID.update or emit actuator commands."""
        if self._active and time.monotonic()-self._remote_last_seen > 1.5:
            self.remote_fault.emit('Pico定深状态超时，已撤销本机启用状态')

    def receive_remote_state(self, state):
        """Render only the matching board session and report actual board PWM for handover."""
        if not self._active or state.get('session_id') != self.remote_session or state.get('execution') != 'pico':
            return
        self._remote_last_seen = time.monotonic()
        if state.get('ok') is False or not state.get('enabled'):
            self.remote_fault.emit(state.get('error', 'Pico已停止定深控制'))
            return
        self._pec_angle = int(state['pwm'])
        self._set_pid_status('Pico计算 · '+state.get('status', '--'))
        loops = state.get('loops', {})
        if self.remote_mode == 'parallel':
            for name, label in getattr(self, '_loop_labels', {}).items():
                loop = loops.get(name, {})
                terms = '/'.join(f'{term:.1f}' for term in loop.get('terms', [0, 0, 0]))
                value, age = loop.get('value'), loop.get('age_s')
                label.setText(f'反馈: {value if value is not None else "--"}  年龄: {age if age is not None else "--"}s'
                              f'\nP/I/D: {terms}\n修正: {loop.get("output", 0):+.1f} μs')
            if hasattr(self, '_combined_label'):
                self._combined_label.setText(f'Pico输出: {self._pec_angle} μs · 控制周期 {state.get("period_ms")} ms')
        else:
            loop = loops.get('depth', {})
            if hasattr(self, '_depth_status_label'):
                self._depth_status_label.setText(f'当前深度: {loop.get("value", "--")} cm')
                self._error_status_label.setText(f'误差: {loop.get("error", "--")} cm')
                self._terms_status_label.setText('P/I/D: '+str(loop.get('terms', [])))
                self._output_status_label.setText(f'Pico胸鳍: {self._pec_angle} μs · {state.get("period_ms")} ms')


class RemoteDepthController(_RemoteDepthProxy, DepthAxisController):
    """Keep the single-loop parameter UI while computing no depth PID on the desktop."""

    remote_fault = pyqtSignal(str)

    def __init__(self, time_source=None, params_path=None):
        """Load the existing single-loop settings, plus an explicit board period."""
        super().__init__(time_source=time_source, params_path=params_path)
        self._remote_init('single')
        try:
            period = float(json.loads(self._params_path.read_text(encoding='utf-8-sig')).get('period_ms', 100))
        except (OSError, ValueError, TypeError):
            period = 100
        self._depth_params['period_ms'] = max(50, min(1000, int(period))) if 50 <= period <= 1000 else 100

    def _create_keyboard_widget(self):
        """Append the board control period to the familiar single-loop form."""
        widget = super()._create_keyboard_widget()
        self._period_input = self._integer_spin(50, 1000, 10, ' ms')
        self._period_input.setValue(self._depth_params['period_ms'])
        widget.findChildren(QFormLayout)[0].addRow('控制周期', self._period_input)
        self._pid_parameter_widgets.append(self._period_input)
        return widget

    def remote_parameters(self):
        """Convert existing flat single-loop settings into the board protocol schema."""
        p = self._depth_params
        return dict(depth=dict(target=p['target_depth'], kp=p['kp'], ki=p['ki'], kd=p['kd'],
                               integral_limit=p['integral_limit'], direction=p['direction'], timeout=p['sensor_timeout']),
                    **{key: p[key] for key in ('neutral_pwm', 'minimum_pwm', 'maximum_pwm', 'period_ms')})

    def _apply_depth_parameters(self):
        """Persist edits and send board configuration, without executing local control math."""
        if not super()._apply_depth_parameters():
            return False
        self._depth_params['period_ms'] = self._period_input.value()
        self._save_depth_parameters()
        return self._request_remote('configure') if self._active else True


class RemoteParallelDepthController(_RemoteDepthProxy, ParallelDepthController):
    """Use the side-by-side parallel parameter view solely as a board configuration client."""

    remote_fault = pyqtSignal(str)

    def __init__(self, time_source=None, params_path=None):
        """Retain separate saved parallel settings and remote-only lifecycle."""
        super().__init__(time_source=time_source, params_path=params_path)
        self._remote_init('parallel')

    def remote_parameters(self):
        """Return independent depth/pitch targets and common board actuator settings."""
        return self._parallel_params

    def _apply_depth_parameters(self):
        """Save both columns and atomically update the active board controller."""
        if not super()._apply_depth_parameters():
            return False
        return self._request_remote('configure') if self._active else True
