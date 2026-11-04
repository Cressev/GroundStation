"""Timed open-loop straight-and-turn experiments for the dual-tail fish."""

import math
import time

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QGridLayout, QGroupBox, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from config import CONTROL_LIMITS
from controllers.base import ControllerBase
from ui.numeric_inputs import NoWheelDoubleSpinBox


class AutonomousController(ControllerBase):
    """A separate heading source; this does not perform obstacle avoidance."""

    def __init__(self, time_source=None):
        super().__init__()
        self._clock = time_source or time.monotonic
        self._control_widget = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_control)
        self._pec_angle = int(CONTROL_LIMITS['pec_angle']['default'])
        self._pectoral_override = None
        self._base_bias = 0.0
        self._current_command.tail_phase_diff = math.pi / 4
        self._run = None
        self._last_sent = None

    def activate(self):
        self._active = True
        self._timer.start()
        self.status_changed.emit('自主定时控制已启用，等待开始实验')
        return True

    def deactivate(self):
        self._active = False
        self._run = None
        self._timer.stop()
        self._set_status('已停用')
        return True

    def get_base_bias(self):
        return self._base_bias

    def set_pectoral_override(self, pulse_width):
        self._pectoral_override = pulse_width
        if pulse_width is not None:
            self._pec_angle = max(500, min(2500, int(pulse_width)))

    def get_control_widget(self):
        if self._control_widget is not None:
            return self._control_widget
        widget = QWidget()
        layout = QVBoxLayout(widget)
        group = QGroupBox('自主定时实验')
        grid = QGridLayout(group)
        self._inputs = {}
        fields = (
            ('frequency', '摆尾频率 f', 0, 4, 1.0, ' Hz'),
            ('amplitude', '关节幅值 A', 0, .5, .17, ' rad'),
            ('base_bias', '基础偏置', -.5, .5, 0, ' rad'),
            ('turn_bias', '转弯偏置 b', -.5, .5, 0, ' rad'),
            ('kappa', '转弯 κ', .1, .9, .5, ''),
            ('straight', '直游时长', 0, 300, 1, ' s'),
            ('turn', '转弯时长', 0, 300, 10, ' s'),
        )
        for row, (key, label, lo, hi, value, suffix) in enumerate(fields):
            spin = NoWheelDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(lo, hi)
            spin.setSingleStep(.1 if key in ('straight', 'turn', 'frequency') else .01)
            spin.setValue(value)
            spin.setSuffix(suffix)
            self._inputs[key] = spin
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(spin, row, 1)
        self._inputs['turn_bias'].setToolTip('转弯时发送 基础偏置 + b；正负方向以实鱼标定为准。')
        self._inputs['kappa'].setToolTip('转弯时直接发送所设 κ；0.5 为对称摆动。')
        grid.addWidget(QLabel('关节相位差'), len(fields), 0)
        grid.addWidget(QLabel('45°（固定）'), len(fields), 1)
        start = QPushButton('开始实验')
        start.clicked.connect(self.start_experiment)
        stop = QPushButton('停止实验')
        stop.clicked.connect(self.stop_motion)
        grid.addWidget(start, len(fields) + 1, 0)
        grid.addWidget(stop, len(fields) + 1, 1)
        layout.addWidget(group)
        self._status_label = QLabel('实验状态：待机')
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)
        hint = QLabel('直游时使用基础偏置和 κ=0.5；转弯时使用基础偏置+b及所设 κ。参数在开始时锁定。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self._control_widget = widget
        return widget

    def _set_status(self, message):
        if hasattr(self, '_status_label'):
            self._status_label.setText('实验状态：' + message)

    def start_experiment(self):
        if not self._active:
            self.status_changed.emit('请先连接机器鱼并启动自主航向控制')
            return False
        if self._run is not None:
            self.status_changed.emit('实验正在运行，请先停止')
            return False
        p = {key: spin.value() for key, spin in self._inputs.items()}
        p['phase'] = math.pi / 4
        if p['frequency'] <= 0 or p['amplitude'] <= 0 or p['straight'] + p['turn'] <= 0:
            self.status_changed.emit('频率和幅值必须大于零，直游与转弯时长不能同时为零')
            return False
        self._base_bias = p['base_bias']
        self._run = {'params': p, 'started': self._clock(), 'stage': None}
        self._last_sent = None
        self.status_changed.emit(f'自主实验开始，地面站时间 {time.time():.3f}')
        self._update_control()
        return True

    def stop_motion(self):
        self._run = None
        self._set_status('已停止')
        if self._active:
            self._emit_command(0, 0, self._base_bias, .5,
                               self._current_command.tail_phase_diff, force=True)

    def _update_control(self):
        if not self._active or self._run is None:
            return
        run = self._run
        p = run['params']
        elapsed = max(0.0, self._clock() - run['started'])
        if elapsed >= p['straight'] + p['turn']:
            self._run = None
            self._set_status('完成并停止')
            self._emit_command(0, 0, self._base_bias, .5, p['phase'], force=True)
            self.status_changed.emit(f'自主实验完成，地面站时间 {time.time():.3f}')
            return
        stage = 'straight' if elapsed < p['straight'] else 'turn'
        if stage != run['stage']:
            run['stage'] = stage
            name = '直游' if stage == 'straight' else '转弯'
            self.status_changed.emit(f'自主实验进入{name}，地面站时间 {time.time():.3f}')
        self._set_status(f"{'直游' if stage == 'straight' else '转弯'}，已运行 {elapsed:.1f} s")
        offset = p['base_bias'] + (p['turn_bias'] if stage == 'turn' else 0)
        kappa = p['kappa'] if stage == 'turn' else .5
        self._emit_command(p['frequency'], p['amplitude'], offset, kappa, p['phase'])

    def _emit_command(self, frequency, amplitude, offset, kappa, phase, force=False):
        cmd = self._current_command
        cmd.tail_frequency = frequency
        cmd.tail_amplitude = amplitude
        cmd.tail_offset = offset
        cmd.tail_kappa = kappa
        cmd.tail_phase_diff = phase
        cmd.pec_angle = self._pec_angle
        cmd.timestamp = time.time()
        values = (frequency, amplitude, offset, kappa, phase, self._pec_angle)
        if force or values != self._last_sent:
            self._last_sent = values
            self.control_command_generated.emit(cmd)
