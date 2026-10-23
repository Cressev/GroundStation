"""Independent depth actuator channel reusing the existing single-loop PID math."""

import time

from communication.base import ControlCommand
from controllers.depth import DepthController


class DepthAxisController(DepthController):
    """Own only pectoral PWM; no keyboard/tail widget and no tail command authority."""

    def __init__(self, time_source=None, params_path=None):
        """Keep legacy calibration, gain limits and PID timing behavior unchanged."""
        super().__init__(time_source=time_source, params_path=params_path)
        self._waiting_for_fresh_sample = True

    def _create_keyboard_widget(self):
        """Return only the shared depth view; the outer axis checkbox owns start/stop."""
        widget = self._create_depth_widget()
        self._pid_enable_checkbox.hide()
        self._parameter_unlock_checkbox.hide()
        self._parameter_unlock_checkbox.setEnabled(False)
        return widget

    def activate(self):
        """Start from neutral, requiring a unique post-start depth sample before PID."""
        if self._active:
            return True
        self._waiting_for_fresh_sample = True
        self._active = True
        self.set_pid_enabled(True)
        self._update_timer.start()
        return True

    def deactivate(self):
        """Revoke this channel before clearing PID so cleanup cannot emit stale output."""
        self._active = False
        self._update_timer.stop()
        self._key_states.clear()
        self.set_pid_enabled(False)
        self._waiting_for_fresh_sample = True
        return True

    def update_depth(self, depth_cm, sample_id=None):
        """Accept each sensor sample only once and release the post-start gate."""
        accepted = super().update_depth(depth_cm, sample_id)
        if accepted and self._active:
            self._waiting_for_fresh_sample = False
        return accepted

    def _update_control(self):
        """Emit only this axis's current pectoral result, never inherited keyboard motion."""
        if not self._active:
            return
        if self._waiting_for_fresh_sample:
            self._pec_angle = int(self._depth_params['neutral_pwm'])
            self._set_pid_status('等待启动后的新深度数据，胸鳍保持中位')
            self._refresh_pid_labels()
        else:
            self._update_pectoral_control()
        command = ControlCommand(freq=0.0, amp=0.0, offset=0.0)
        command.pec_angle = self._pec_angle
        command.timestamp = time.time()
        self._current_command = command
        self.control_command_generated.emit(command)
