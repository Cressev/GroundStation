"""Single output authority combining independent heading and depth control channels."""

from copy import deepcopy
import math
import time

from PyQt5.QtCore import QObject, pyqtSignal

from communication.base import ControlCommand


class ControlCoordinator(QObject):
    """Route tail fields from heading and pectoral PWM from exactly one current owner."""

    command_generated = pyqtSignal(object)
    state_changed = pyqtSignal()
    status_changed = pyqtSignal(str)

    def __init__(self, heading_controllers, depth_controller, parent=None):
        """Attach source-tagged slots; inactive/previous sources never gain send authority."""
        super().__init__(parent)
        self.headings = dict(heading_controllers)
        self.depth = depth_controller
        self.heading_name = 'keyboard'
        self.heading_enabled = self.depth_enabled = self.connected = False
        self._heading_snapshot = None
        self._safe_offset = 0.0
        self._safe_phase = 1.57
        self._safe_kappa = 0.5
        self._manual_pwm = self._depth_pwm = self.last_pwm = 1500
        for name, controller in self.headings.items():
            controller.control_command_generated.connect(
                lambda command, source=name: self.receive_heading(source, command))
        self._depth_sources = set()
        self._connect_depth_source(self.depth)

    def _connect_depth_source(self, controller):
        """Tag each depth signal so a previously selected controller cannot send late PWM."""
        if controller not in self._depth_sources:
            controller.control_command_generated.connect(
                lambda command, source=controller: self.receive_depth(command, source))
            self._depth_sources.add(controller)

    def select_depth(self, controller):
        """Switch depth algorithms only while that axis is stopped, keeping heading intact."""
        if controller is self.depth:
            return True
        if self.depth_enabled:
            self.status_changed.emit('请先停止深度控制，再切换深度类型')
            return False
        self.depth = controller
        self._connect_depth_source(controller)
        self.state_changed.emit()
        return True

    @property
    def heading(self):
        """Return the selected heading algorithm, independent of the depth algorithm."""
        return self.headings[self.heading_name]

    def set_connected(self, connected):
        """A disconnected transport revokes both channels; reconnect never rearms them."""
        connected = bool(connected)
        if self.connected == connected:
            return
        self.connected = connected
        if not connected:
            self.stop_all(send=False)
        self.state_changed.emit()

    def select_heading(self, name):
        """Allow idempotent selection only while the heading channel is stopped."""
        if name not in self.headings:
            return False
        if name == self.heading_name:
            return True
        if self.heading_enabled:
            self.status_changed.emit('请先停止航向控制，再切换航向类型')
            return False
        self.heading_name = name
        self._heading_snapshot = None
        self._sync_pectoral_owner()
        self.state_changed.emit()
        return True

    def set_heading_enabled(self, enabled, send=True):
        """Starting/stopping tail control leaves the depth channel and its PID untouched."""
        enabled = bool(enabled)
        if enabled == self.heading_enabled:
            return True
        if enabled and not self.connected:
            self.status_changed.emit('未连接机器鱼，不能启动航向控制')
            return False
        if enabled:
            self._heading_snapshot = None
            if not self.depth_enabled:
                self._manual_pwm = int(self.heading._pec_angle)
            self._sync_pectoral_owner()
            if not self.heading.activate():
                return False
            self.heading_enabled = True
            self._sync_pectoral_owner()
            self._safe_offset = self.heading.get_base_bias()
            if hasattr(self.heading, 'stop_motion'):
                self.heading.stop_motion()
            elif send:
                self._publish()
        else:
            self.heading_enabled = False
            self._safe_offset = self.heading.get_base_bias()
            self.heading.deactivate()
            self._sync_pectoral_owner()
            if send:
                self._publish(force=True)
        self.state_changed.emit()
        return True

    def set_depth_enabled(self, enabled):
        """Acquire or release pectoral PWM without changing the selected/active tail source."""
        enabled = bool(enabled)
        if enabled == self.depth_enabled:
            return True
        if enabled and not self.connected:
            self.status_changed.emit('未连接机器鱼，不能启动深度控制')
            return False
        if enabled:
            self.depth_enabled = True
            self._depth_pwm = int(self.depth._depth_params['neutral_pwm'])
            self._sync_pectoral_owner()
            if not self.depth.activate():
                self.depth_enabled = False
                self._sync_pectoral_owner()
                return False
        else:
            self._manual_pwm = self.last_pwm
            self.depth_enabled = False
            self.depth.deactivate()
            self._sync_pectoral_owner()
            self._publish(force=True)
        self.state_changed.emit()
        return True

    def _sync_pectoral_owner(self):
        """Synchronize actual PWM in all manual sources so releasing PID cannot jump back."""
        pwm = self._depth_pwm if self.depth_enabled else self._manual_pwm
        for name, controller in self.headings.items():
            controller.set_pectoral_override(pwm)
            if not self.depth_enabled:
                controller.set_pectoral_override(None)
            if hasattr(controller, 'set_emergency_monitoring'):
                controller.set_emergency_monitoring(name == self.heading_name and
                    (self.heading_enabled or self.depth_enabled))

    def receive_heading(self, source, command):
        """Keep only the selected live source's copied tail snapshot, ignoring stale signals."""
        if not self.connected or not self.heading_enabled or source != self.heading_name:
            return
        fields = ('tail_frequency', 'tail_amplitude', 'tail_offset', 'tail_phase_diff', 'tail_kappa')
        try:
            valid = all(math.isfinite(float(getattr(command, name, 1.57))) for name in fields)
            valid = valid and 0.1 <= float(getattr(command, 'tail_kappa', 0.5)) <= 0.9
            manual_pwm = float(getattr(command, 'pec_angle', self.heading._pec_angle))
            valid = valid and math.isfinite(manual_pwm)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            self.status_changed.emit('航向指令包含非法数值，已拒绝')
            return
        self._heading_snapshot = deepcopy(command)
        self._safe_phase = getattr(command, 'tail_phase_diff', 1.57)
        self._safe_kappa = getattr(command, 'tail_kappa', 0.5)
        if not self.depth_enabled:
            self._manual_pwm = max(500, min(2500, int(round(manual_pwm))))
        self._publish()

    def receive_depth(self, command, source=None):
        """Use only live depth PWM; no field from a depth frame may overwrite tail motion."""
        if not self.connected or not self.depth_enabled or (source is not None and source is not self.depth):
            return
        try:
            pwm = float(command.pec_angle)
        except (TypeError, ValueError, AttributeError):
            self.status_changed.emit('深度指令包含非法数值，已拒绝')
            return
        if not math.isfinite(pwm):
            self.status_changed.emit('深度指令包含非法数值，已拒绝')
            return
        self._depth_pwm = max(500, min(2500, int(round(pwm))))
        self._sync_pectoral_owner()
        self._publish()

    def receive_remote_pwm(self, pwm, handover=False):
        """Track authoritative board PWM for display/manual handover without emitting it back."""
        try:
            pwm = float(pwm)
        except (TypeError, ValueError):
            return
        if (self.depth_enabled or handover) and math.isfinite(pwm) and 500 <= pwm <= 2500:
            self._depth_pwm = self.last_pwm = int(round(pwm))
            if handover and not self.depth_enabled:
                self._manual_pwm = self.last_pwm
            self._sync_pectoral_owner()

    def _publish(self, force=False):
        """Construct a fresh whole-frame command so later source mutation cannot corrupt it."""
        if not self.connected or not (force or self.heading_enabled or self.depth_enabled):
            return
        source = self._heading_snapshot if self.heading_enabled else None
        command = ControlCommand(freq=0.0, amp=0.0, offset=self._safe_offset)
        command.tail_phase_diff = self._safe_phase
        command.tail_kappa = self._safe_kappa
        if source is not None:
            for key in ('tail_frequency', 'tail_amplitude', 'tail_offset', 'tail_phase_diff', 'tail_kappa'):
                setattr(command, key, getattr(source, key, getattr(command, key)))
        command.pec_angle = self._depth_pwm if self.depth_enabled else self._manual_pwm
        command.timestamp = time.time()
        self.last_pwm = command.pec_angle
        self.command_generated.emit(command)

    def stop_all(self, send=True, neutral=True):
        """Revoke both channels before cleanup; emergency stop can hold actual pectoral PWM."""
        was_active = self.heading_enabled or self.depth_enabled
        self._manual_pwm = 1500 if neutral else self.last_pwm
        self.heading_enabled = self.depth_enabled = False
        for controller in self.headings.values():
            if controller.active:
                controller.deactivate()
        self.depth.deactivate()
        self._heading_snapshot = None
        self._sync_pectoral_owner()
        if send and was_active:
            self._publish(force=True)
        self.state_changed.emit()

    def emergency_stop(self):
        """Latch both channels off while retaining the last pectoral value actually sent."""
        self.stop_all(send=True, neutral=False)
