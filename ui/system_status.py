"""Pico system telemetry trends with independent history and viewport-only exports."""

import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import time

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
                             QButtonGroup, QPushButton, QFileDialog, QMessageBox, QLineEdit,
                             QScrollArea, QSplitter, QFrame, QSizePolicy)
from ui.numeric_inputs import NoWheelSpinBox, NoWheelComboBox


class SystemStatusWidget(QWidget):
    """Show board-wide CPU/load, SoC temperature and memory, never desktop process usage."""

    def __init__(self):
        """Keep all real packet samples since clear; viewing does not truncate storage."""
        super().__init__()
        self.rows = []
        self.connected = False
        self._following = {key: True for key in ('cpu_percent', 'soc_temp_c', 'memory_percent')}
        self.follow_latest = True
        self.sliding_time = False
        self._origin = self._last_arrival = self._last_source = None
        self._outage = False
        self._session = 0
        self._build_ui()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start(1000)

    def _build_ui(self):
        """Put three independent, height-adjustable canvases in a vertically scrollable page."""
        layout = QVBoxLayout(self)
        mode_row, action_row = QHBoxLayout(), QHBoxLayout()
        self.global_time_cb = QRadioButton('全局时间序列')
        self.sliding_time_cb = QRadioButton('滑动窗口')
        group = QButtonGroup(self)
        for button in (self.global_time_cb, self.sliding_time_cb):
            group.addButton(button)
            mode_row.addWidget(button)
            button.toggled.connect(self._change_mode)
        self.global_time_cb.setChecked(True)
        self.sliding_window_input = NoWheelSpinBox()
        self.sliding_window_input.setRange(1, 86400)
        self.sliding_window_input.setValue(300)
        self.sliding_window_input.setSuffix(' 秒')
        self.sliding_window_input.setKeyboardTracking(False)
        self.sliding_window_input.setEnabled(False)
        self.sliding_window_input.valueChanged.connect(self._change_window)
        mode_row.addWidget(QLabel('窗口大小'))
        mode_row.addWidget(self.sliding_window_input)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        for text, callback in (('清除曲线', self.clear_data), ('重置全部', self.reset_view),
                               ('保存数据', self._save_data), ('保存图像', self._save_image)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            action_row.addWidget(button)
        action_row.addStretch()
        layout.addLayout(action_row)
        condition = QHBoxLayout()
        condition.addWidget(QLabel('实验标签'))
        self.condition_input = QLineEdit()
        self.condition_input.setPlaceholderText('例如：充电宝 / 无风扇 / 室温25℃；仅标记，不切换硬件')
        condition.addWidget(self.condition_input)
        layout.addLayout(condition)
        self.status_label = QLabel('未连接；数据源为机器鱼控制板，不是本地电脑')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel('数据导出范围'))
        self.export_plot_combo = NoWheelComboBox()
        self.export_plot_combo.addItems(['CPU画布', '温度画布', '内存画布'])
        self.export_plot_combo.setToolTip('以所选画布的可见时间范围导出全部指标；不改变其他画布。')
        export_row.addWidget(self.export_plot_combo)
        export_row.addStretch()
        layout.addLayout(export_row)
        self.canvas = QWidget()
        canvas = QVBoxLayout(self.canvas)
        canvas.setContentsMargins(0, 0, 0, 0)
        self.plot_splitter = QSplitter(Qt.Vertical)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.setHandleWidth(8)
        self.plot_splitter.setToolTip('拖动图与图之间的分隔条，调整各画布显示高度。')
        canvas.addWidget(self.plot_splitter)
        self.plots, self.curves = [], {}
        self._plot_keys = []
        for key, title, unit, color in (
                ('cpu_percent', 'CPU占用率', '%', '#41a5ff'),
                ('soc_temp_c', 'CPU温度', '℃', '#ff9c44'),
                ('memory_percent', '内存占用率', '%', '#48c78e')):
            plot = pg.PlotWidget(title=title)
            plot.setLabel('left', title, units=unit)
            plot.setLabel('bottom', '时间', units='s')
            plot.getAxis('bottom').enableAutoSIPrefix(False)
            plot.showGrid(x=True, y=True, alpha=.3)
            curve = plot.plot(pen=pg.mkPen(color, width=2), connect='finite')
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method='peak')
            self.curves[key] = curve
            self.plots.append(plot)
            self._plot_keys.append(key)
            plot.getViewBox().sigRangeChangedManually.connect(
                lambda *args, metric=key: self._on_manual_view_change(metric))
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            reset = QPushButton('重置此图')
            reset.setMaximumWidth(100)
            reset.clicked.connect(lambda checked=False, metric=key: self.reset_plot(metric))
            panel_layout.addWidget(reset, 0, Qt.AlignRight)
            plot.setMinimumHeight(180)
            panel_layout.addWidget(plot, 1)
            self.plot_splitter.addWidget(panel)
        self.plot_splitter.setSizes([240, 240, 240])
        self.canvas.setMinimumHeight(720)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, 1)

    @property
    def follow_latest(self):
        """Keep the existing all-following API while storing each canvas's own follow state."""
        return all(self._following.values())

    @follow_latest.setter
    def follow_latest(self, value):
        """Explicit global mode/reset commands may restore all canvases at once."""
        for key in self._following:
            self._following[key] = bool(value)

    @staticmethod
    def _number(value, minimum=0., maximum=float('inf')):
        """Return a finite plausible value or None, never a fake zero on missing data."""
        try:
            result = float(value)
            return result if math.isfinite(result) and minimum <= result <= maximum else None
        except (ValueError, TypeError, OverflowError):
            return None

    def set_connected(self, connected):
        """Preserve histories across sessions, marking outages without inventing samples."""
        connected = bool(connected)
        if connected != self.connected:
            self._outage = bool(self.rows)
            if connected:
                self._session += 1
                self._last_source = None
        self.connected = connected
        self._refresh_status()

    def add_sample(self, telemetry, received_at=None, source_timestamp=None):
        """Append exactly one new received board state, using local monotonic elapsed time."""
        if not self.connected or not isinstance(telemetry, dict) or not telemetry:
            return False
        arrival = time.monotonic() if received_at is None else received_at
        arrival = self._number(arrival)
        if arrival is None or (self._last_arrival is not None and arrival <= self._last_arrival):
            return False
        source = self._number(source_timestamp)
        if source is not None and source == self._last_source:
            return False
        if self._origin is None:
            self._origin = arrival
        elapsed = arrival - self._origin
        if self.rows and (self._outage or arrival-self._last_arrival > 2.):
            self.rows.append(dict(time_s=(self.rows[-1]['time_s']+elapsed)/2, status='gap'))
        used, total = (self._number(telemetry.get(key)) for key in ('mem_used_mb', 'mem_total_mb'))
        memory = 100.*used/total if used is not None and total and used <= total else None
        receipt_wall = time.time()+arrival-time.monotonic()
        row = dict(time_s=elapsed, received_utc=datetime.fromtimestamp(receipt_wall, timezone.utc).isoformat(timespec='milliseconds'),
                   source_timestamp=source, session=self._session, condition=self.condition_input.text().strip(),
                   status='sample', cpu_percent=self._number(telemetry.get('cpu_percent'), maximum=100.),
                   soc_temp_c=self._number(telemetry.get('soc_temp_c'), minimum=-40., maximum=150.),
                   memory_percent=memory, mem_used_mb=used, mem_total_mb=total,
                   cpu_freq_mhz=self._number(telemetry.get('cpu_freq_mhz')))
        self.rows.append(row)
        self._last_arrival, self._last_source, self._outage = arrival, source, False
        self._render()
        self._refresh_status()
        return True

    def _refresh_status(self):
        """Show receipt age and outage explicitly; do not keep stale numbers labelled live."""
        if not self.connected:
            self.status_label.setText('未连接；保留已有曲线，重连不会自动清除')
        elif self._last_arrival is None:
            self.status_label.setText('等待控制板遥测；旧服务可能不提供CPU/温度/内存')
        else:
            age = max(0., time.monotonic()-self._last_arrival)
            if age > 2.:
                self.status_label.setText(f'遥测超时：{age:.1f} 秒无新数据；旧读数不再追加')
                return
            row = self.rows[-1]
            values = ['--' if row[key] is None else f'{row[key]:.1f}'
                      for key in ('cpu_percent', 'soc_temp_c', 'memory_percent')]
            used, total = row['mem_used_mb'], row['mem_total_mb']
            memory = '--' if used is None or total is None else f'{used:.0f}/{total:.0f} MiB'
            self.status_label.setText(f'控制板 CPU {values[0]}% · 温度 {values[1]}℃ · '
                                      f'内存 {values[2]}%（{memory}）· {len(self.rows)} 行 · 更新 {age:.1f}s前')

    def _render(self):
        """Plot full stored data; viewport clipping/downsampling only changes drawing work."""
        times = np.array([row['time_s'] for row in self.rows])
        for key, curve in self.curves.items():
            values = np.array([np.nan if row.get(key) is None else row[key] for row in self.rows])
            curve.setData(times, values, connect='finite')
        if self.rows:
            end = self.rows[-1]['time_s']
            start = max(0., end-self.sliding_window_input.value()) if self.sliding_time else 0.
            for key, plot in zip(self._plot_keys, self.plots):
                if self._following[key]:
                    plot.setXRange(start, max(end, start+1.), padding=0)

    def _change_mode(self, checked):
        """Switch view modes without clearing or pruning collected samples."""
        if not checked or not hasattr(self, 'sliding_window_input'):
            return
        self.sliding_time = self.sliding_time_cb.isChecked()
        self.sliding_window_input.setEnabled(self.sliding_time)
        self.follow_latest = True
        self._render()

    def _change_window(self, value):
        """Resume following when the user deliberately changes the sliding duration."""
        if self.sliding_time:
            self.follow_latest = True
            self._render()

    def _on_manual_view_change(self, metric=None, *args):
        """Freeze only the canvas manually zoomed/panned, not its neighboring views."""
        if metric in self._following:
            self._following[metric] = False
        else:
            self.follow_latest = False

    def reset_plot(self, metric):
        """Restore the selected canvas alone; retain all other view ranges and follow flags."""
        self._following[metric] = True
        self.plots[self._plot_keys.index(metric)].enableAutoRange(axis='y')
        self._render()

    def reset_view(self):
        """Return to the selected global/sliding X mode and automatic Y ranges."""
        self.follow_latest = True
        for plot in self.plots:
            plot.enableAutoRange(axis='y')
        self._render()

    def clear_data(self):
        """Clear only system history and reset its elapsed origin, not depth/video/control."""
        self.rows.clear()
        self._origin = self._last_arrival = self._last_source = None
        self._outage = False
        self.follow_latest = True
        self._render()
        self._refresh_status()

    def visible_rows(self):
        """Export all metrics using the explicitly selected canvas's actual visible interval."""
        if not self.rows:
            return []
        plot = self.plots[self.export_plot_combo.currentIndex()]
        start, end = sorted(plot.getViewBox().viewRange()[0])
        return [row.copy() for row in self.rows if start-1e-8 <= row['time_s'] <= end+1e-8]

    def export_data(self, filepath):
        """Save only the real visible interval to UTF-8 CSV or Excel, leaving missing cells blank."""
        rows = self.visible_rows()
        if not rows:
            raise ValueError('当前画布时间范围内没有可保存的数据')
        headers = ('time_s', 'cpu_percent', 'soc_temp_c', 'memory_percent', 'mem_used_mb',
                   'mem_total_mb', 'cpu_freq_mhz', 'received_utc', 'source_timestamp', 'session', 'condition', 'status')
        path = Path(filepath)
        if path.suffix.lower() == '.csv':
            with path.open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.DictWriter(stream, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        elif path.suffix.lower() == '.xlsx':
            import xlsxwriter
            with xlsxwriter.Workbook(str(path), {'strings_to_formulas': False, 'strings_to_urls': False}) as book:
                sheet = book.add_worksheet('系统状态')
                sheet.write_row(0, 0, headers)
                for index, row in enumerate(rows, 1):
                    sheet.write_row(index, 0, [row.get(key) for key in headers])
                sheet.freeze_panes(1, 1)
                sheet.autofilter(0, 0, len(rows), len(headers)-1)
                sheet.set_column(0, len(headers)-1, 20)
        else:
            raise ValueError('仅支持CSV或Excel (.xlsx)')
        return str(path), len(rows)

    def export_png(self, filepath):
        """Save the current three-plot canvas exactly as viewed, without controls."""
        path = Path(filepath).with_suffix('.png')
        if not self.canvas.grab().save(str(path), 'PNG'):
            raise OSError('PNG保存失败')
        return str(path)

    def _save_data(self):
        """Ask for a path/type before exporting the current visible telemetry interval."""
        path, kind = QFileDialog.getSaveFileName(self, '保存当前系统状态数据',
            '系统状态_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.csv',
            'CSV 文件 (*.csv);;Excel 工作簿 (*.xlsx)')
        if not path:
            return
        if Path(path).suffix.lower() not in ('.csv', '.xlsx'):
            path = str(Path(path).with_suffix('.xlsx' if 'Excel' in kind else '.csv'))
        try:
            saved, count = self.export_data(path)
            QMessageBox.information(self, '保存成功', f'已保存 {count} 行当前范围数据\n{saved}')
        except Exception as exc:
            QMessageBox.critical(self, '保存失败', str(exc))

    def _save_image(self):
        """Ask for a PNG path and report any write error without changing live history."""
        path, _ = QFileDialog.getSaveFileName(self, '保存当前系统状态画布',
            '系统状态_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.png', 'PNG 图像 (*.png)')
        if path:
            try:
                self.export_png(path)
            except Exception as exc:
                QMessageBox.critical(self, '保存失败', str(exc))
