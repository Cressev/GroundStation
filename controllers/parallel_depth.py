"""Parallel depth/pitch PID: independent feedback loops summed into one pectoral PWM."""

from copy import deepcopy
import json
import math
from pathlib import Path
import time

from PyQt5.QtWidgets import (QComboBox, QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from communication.base import ControlCommand
from controllers.depth import PID, clamp
from controllers.depth_axis import DepthAxisController
from ui.numeric_inputs import NoWheelComboBox


PARAMS_PATH = Path(__file__).resolve().parents[1] / 'parallel_depth_pid_params.json'
DEFAULTS = {
    'depth': dict(target=15., kp=0., ki=0., kd=0., integral_limit=1000., direction=-1, timeout=.5),
    'pitch': dict(target=0., kp=0., ki=0., kd=0., integral_limit=100., direction=-1, timeout=.5),
    'neutral_pwm': 1500, 'minimum_pwm': 1300, 'maximum_pwm': 1700, 'period_ms': 100,
}


class ParallelDepthController(DepthAxisController):
    """Keep depth and pitch targets independent, with explicit sample freshness gates."""

    def __init__(self, time_source=None, params_path=None):
        """Use a separate local parameter file and zero gains until deliberately tuned."""
        super().__init__(time_source=time_source, params_path=params_path or PARAMS_PATH)
        self._parallel_params = self._load_parallel_parameters()
        self._depth_params = self._parallel_params  # Shared actuator limits for the coordinator.
        self._loops = {name: PID() for name in ('depth', 'pitch')}
        self._samples = dict(depth=None, pitch=None)
        self._processed = dict(depth=None, pitch=None)
        self._after_start = dict(depth=None, pitch=None)
        self._last_times = dict(depth=None, pitch=None)
        self._outputs = dict(depth=0., pitch=0.)
        self._faulted = True
        self._pec_angle = self._parallel_params['neutral_pwm']
        self._configure_loops()

    def _load_parallel_parameters(self):
        """Validate saved nested parameters, falling back safely on invalid files."""
        params = deepcopy(DEFAULTS)
        try:
            saved = json.loads(self._params_path.read_text(encoding='utf-8-sig'))
            for name in ('depth', 'pitch'):
                for key, default in params[name].items():
                    value = float(saved.get(name, {}).get(key, default))
                    if not math.isfinite(value):
                        raise ValueError('non-finite parameter')
                    bounds = ((0., 500.) if name == 'depth' else (-60., 60.)) if key == 'target' else {
                        'kp': (-1000., 1000.), 'ki': (-1000., 1000.), 'kd': (-1000., 1000.),
                        'integral_limit': (0., 10000.), 'direction': (-1., 1.), 'timeout': (.2, 5.),
                    }[key]
                    params[name][key] = clamp(value, *bounds)
                params[name]['direction'] = -1 if params[name]['direction'] < 0 else 1
            for key in ('neutral_pwm', 'minimum_pwm', 'maximum_pwm', 'period_ms'):
                value = float(saved.get(key, params[key]))
                if not math.isfinite(value):
                    raise ValueError('non-finite actuator parameter')
                params[key] = int(clamp(value, 50, 1000) if key == 'period_ms' else clamp(value, 500, 2500))
            if not params['minimum_pwm'] <= params['neutral_pwm'] <= params['maximum_pwm']:
                raise ValueError('invalid PWM limits')
        except (OSError, ValueError, TypeError, AttributeError):
            return deepcopy(DEFAULTS)
        return params

    def _configure_loops(self):
        """Apply each loop's own gains and integral limit without mixing their units."""
        for name, loop in self._loops.items():
            p = self._parallel_params[name]
            loop.configure(p['kp'], p['ki'], p['kd'], p['integral_limit'])
        self._update_timer.setInterval(self._parallel_params['period_ms'])

    def _create_keyboard_widget(self):
        """Build two permanently adjacent parameter columns plus compact common settings."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        description = QLabel('并联叠加：中位 PWM + 深度修正 + 俯仰修正；俯仰单位为度，旧弧度增益不能直接照搬。')
        description.setWordWrap(True)
        layout.addWidget(description)
        columns = QHBoxLayout()
        columns.setSpacing(12)
        self._loop_inputs, self._loop_labels, self._loop_groups = {}, {}, {}
        self._pid_parameter_widgets = []
        for name, title, unit in (('depth', '深度 PID', ' cm'), ('pitch', '俯仰 PID', ' °')):
            group = QGroupBox(title)
            self._loop_groups[name] = group
            group_layout = QVBoxLayout(group)
            form = QFormLayout()
            fields = {}
            ranges = dict(target=(0., 500.) if name == 'depth' else (-60., 60.),
                          kp=(-1000., 1000.), ki=(-1000., 1000.), kd=(-1000., 1000.),
                          integral_limit=(0., 10000.), timeout=(.2, 5.))
            titles = dict(target='目标值', kp='Kp', ki='Ki', kd='Kd', integral_limit='积分限幅', timeout='数据超时')
            for key, bounds in ranges.items():
                suffix = unit if key == 'target' else (' s' if key == 'timeout' else unit + '·s' if key == 'integral_limit' else '')
                spin = self._double_spin(*bounds, .1, 3 if key in ('ki', 'kd') else 2, suffix)
                spin.setValue(self._parallel_params[name][key])
                fields[key] = spin
                form.addRow(titles[key], spin)
            direction = NoWheelComboBox()
            direction.addItem('正误差 → 减小PWM', -1)
            direction.addItem('正误差 → 增大PWM', 1)
            direction.setCurrentIndex(direction.findData(self._parallel_params[name]['direction']))
            fields['direction'] = direction
            form.addRow('输出方向', direction)
            self._loop_inputs[name] = fields
            self._pid_parameter_widgets.extend(fields.values())
            group_layout.addLayout(form)
            status = QLabel('反馈: --\nP/I/D: --\n修正: 0 μs')
            status.setWordWrap(True)
            self._loop_labels[name] = status
            group_layout.addWidget(status)
            columns.addWidget(group, 1)
        layout.addLayout(columns)
        common = QGroupBox('公共输出设置')
        grid = QGridLayout(common)
        self._common_inputs = {}
        for index, (key, title) in enumerate((('neutral_pwm', '中位'), ('minimum_pwm', '最小'),
                                            ('maximum_pwm', '最大'), ('period_ms', '周期'))):
            spin = self._integer_spin(50 if key == 'period_ms' else 500,
                                      1000 if key == 'period_ms' else 2500, 10,
                                      ' ms' if key == 'period_ms' else ' μs')
            spin.setValue(self._parallel_params[key])
            self._common_inputs[key] = spin
            self._pid_parameter_widgets.append(spin)
            row, col = divmod(index, 2)
            grid.addWidget(QLabel(title), row, col * 2)
            grid.addWidget(spin, row, col * 2 + 1)
            grid.setColumnStretch(col * 2 + 1, 1)
        layout.addWidget(common)
        self._apply_pid_button = QPushButton('应用并保存两组参数')
        self._apply_pid_button.clicked.connect(self._apply_depth_parameters)
        layout.addWidget(self._apply_pid_button)
        self._pid_status_label = QLabel('未启动；默认两组增益均为0，请确认参数与执行器方向')
        self._pid_status_label.setWordWrap(True)
        self._combined_label = QLabel('胸鳍: 1500 μs')
        layout.addWidget(self._pid_status_label)
        layout.addWidget(self._combined_label)
        self._set_parameter_widgets_enabled(False)
        return widget

    def _apply_depth_parameters(self):
        """Save both columns atomically, retaining the old configuration on invalid limits."""
        params = {name: {key: (field.currentData() if isinstance(field, QComboBox) else field.value())
                         for key, field in fields.items()} for name, fields in self._loop_inputs.items()}
        params.update({key: field.value() for key, field in self._common_inputs.items()})
        if not params['minimum_pwm'] <= params['neutral_pwm'] <= params['maximum_pwm']:
            self._set_pid_status('参数错误：最小脉宽 ≤ 中位 ≤ 最大脉宽')
            return False
        try:
            temporary = self._params_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self._params_path)
        except OSError as exc:
            self._set_pid_status(f'参数保存失败: {exc}')
            return False
        self._parallel_params = self._depth_params = params
        self._configure_loops()
        self._reset_parallel()
        self._set_pid_status('两组参数已应用；等待两路新样本')
        return True

    def _reset_parallel(self):
        """Clear both integrators and require new independent samples after any reset."""
        for loop in self._loops.values():
            loop.reset()
        self._outputs = dict(depth=0., pitch=0.)
        self._last_times = dict(depth=None, pitch=None)
        self._after_start = {name: sample['id'] if sample else None for name, sample in self._samples.items()}
        self._processed = dict(self._after_start)
        self._pec_angle = self._parallel_params['neutral_pwm']
        self._faulted = True

    def activate(self):
        """Acquire pectoral control, initially centered until both post-start samples arrive."""
        if self._active:
            return True
        self._active = self._pid_enabled = True
        self._reset_parallel()
        self._update_timer.start()
        self._update_control()
        return True

    def deactivate(self):
        """Stop without emitting a cleanup frame, leaving handover to the coordinator."""
        self._active = self._pid_enabled = False
        self._update_timer.stop()
        self._reset_parallel()
        self._set_pid_status('并联双闭环已停止')
        return True

    def _accept_sample(self, name, value, sample_id, received_at=None, age_s=0.):
        """Accept finite identified sensor samples; duplicates never refresh their age."""
        try:
            value, age = float(value), float(age_s)
            arrival = self._time_source() if received_at is None else float(received_at)
            if sample_id is None or not all(math.isfinite(v) for v in (value, arrival, age)) or age < 0:
                return False
        except (TypeError, ValueError):
            return False
        current = self._samples[name]
        if current and current['id'] == sample_id:
            return False
        self._samples[name] = dict(value=value, id=sample_id, arrival=arrival - age)
        return True

    def update_depth(self, depth_cm, sample_id=None, received_at=None, age_s=0.):
        """Receive calibrated depth in positive-down centimeters with its own identity."""
        return self._accept_sample('depth', depth_cm, sample_id, received_at, age_s)

    def update_pitch(self, pitch_rad, sample_id=None, received_at=None, age_s=0.):
        """Convert verified radian IMU feedback to the degree-based controller UI."""
        try:
            value = math.degrees(float(pitch_rad))
        except (TypeError, ValueError):
            return False
        if not -90.001 <= value <= 90.001:
            return False
        return self._accept_sample('pitch', value, sample_id, received_at, age_s)

    def _update_control(self):
        """Update each PID once per unique sample; sum held corrections, then clamp once."""
        if not self._active:
            return
        now = self._time_source()
        stale = [name for name, sample in self._samples.items() if sample is None or
                 now - sample['arrival'] > self._parallel_params[name]['timeout']]
        waiting = any(sample is None or sample['id'] == self._after_start[name]
                      for name, sample in self._samples.items())
        if stale or waiting:
            if not self._faulted:
                self._reset_parallel()
            self._set_pid_status('等待两路新鲜反馈/数据超时，胸鳍保持中位')
        else:
            self._faulted = False
            for name, sample in self._samples.items():
                if self._processed[name] == sample['id']:
                    continue
                previous = self._last_times[name]
                dt = self._parallel_params['period_ms'] / 1000 if previous is None else sample['arrival'] - previous
                dt = clamp(dt, .001, 1.)
                p = self._parallel_params[name]
                output = self._loops[name].update(p['target'] - sample['value'], dt)
                self._outputs[name] = p['direction'] * output
                self._processed[name], self._last_times[name] = sample['id'], sample['arrival']
            p = self._parallel_params
            total = p['neutral_pwm'] + sum(self._outputs.values())
            self._pec_angle = int(round(clamp(total, p['minimum_pwm'], p['maximum_pwm'])))
            self._set_pid_status('并联双闭环运行中' + ('（输出限幅）' if self._pec_angle != round(total) else ''))
        self._refresh_parallel_labels()
        command = ControlCommand(freq=0., amp=0., offset=0.)
        command.pec_angle, command.timestamp = self._pec_angle, time.time()
        self._current_command = command
        self.control_command_generated.emit(command)

    def _refresh_parallel_labels(self):
        """Display both loop contributions, feedback ages and the final clipped command."""
        if not hasattr(self, '_loop_labels'):
            return
        for name, label in self._loop_labels.items():
            sample = self._samples[name]
            value = '--' if sample is None else f"{sample['value']:.2f}"
            age = '--' if sample is None else f"{max(0., self._time_source()-sample['arrival']):.2f}"
            terms = '/'.join(f'{term:.1f}' for term in self._loops[name].terms)
            label.setText(f'反馈: {value}  年龄: {age}s\nP/I/D: {terms}\n修正: {self._outputs[name]:+.1f} μs')
        self._combined_label.setText(f'中位 {self._parallel_params["neutral_pwm"]} + 深度 {self._outputs["depth"]:+.1f}'
                                    f' + 俯仰 {self._outputs["pitch"]:+.1f} → 胸鳍 {self._pec_angle} μs')
