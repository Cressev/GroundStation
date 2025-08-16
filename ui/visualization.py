#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据可视化组件
Data Visualization Components
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                             QLabel, QGroupBox, QGridLayout)
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtGui import QFont
import time
from collections import deque

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.base import FishState
from config import PLOT_UPDATE_RATE, PLOT_HISTORY_LENGTH, UI_CONFIG

class DataVisualizationWidget(QWidget):
    """数据可视化主组件"""
    
    def __init__(self):
        super().__init__()
        self.data_history = {
            'time': deque(maxlen=PLOT_HISTORY_LENGTH),
            'x': deque(maxlen=PLOT_HISTORY_LENGTH),
            'y': deque(maxlen=PLOT_HISTORY_LENGTH), 
            'z': deque(maxlen=PLOT_HISTORY_LENGTH),
            'roll': deque(maxlen=PLOT_HISTORY_LENGTH),
            'pitch': deque(maxlen=PLOT_HISTORY_LENGTH),
            'yaw': deque(maxlen=PLOT_HISTORY_LENGTH)
        }
        
        self.start_time = time.time()
        self.plot_enabled = True  # 绘图开关状态
        self._init_ui()
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_plots)
        self.update_timer.start(1000 // PLOT_UPDATE_RATE)  # 转换为毫秒
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # XY平面图标签
        xy_tab = self._create_xy_plot_tab()
        tab_widget.addTab(xy_tab, "XY轨迹图")
        
        # 时间序列图标签
        time_series_tab = self._create_time_series_tab()
        tab_widget.addTab(time_series_tab, "时间序列")
        
        # 姿态显示标签
        attitude_tab = self._create_attitude_tab()
        tab_widget.addTab(attitude_tab, "姿态显示")
        
        layout.addWidget(tab_widget)
        
    def _create_xy_plot_tab(self):
        """创建XY轨迹图标签"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # XY轨迹图
        self.xy_plot = pg.PlotWidget(title="XY平面轨迹")
        self.xy_plot.setLabel('left', 'Y位置 (m)')
        self.xy_plot.setLabel('bottom', 'X位置 (m)')
        self.xy_plot.setAspectLocked(True)
        self.xy_plot.showGrid(x=True, y=True)
        
        # 轨迹线
        self.xy_curve = self.xy_plot.plot(pen=pg.mkPen(color='blue', width=2))
        # 当前位置点
        self.xy_point = self.xy_plot.plot(pen=None, symbol='o', symbolBrush='red', symbolSize=8)
        
        layout.addWidget(self.xy_plot)
        
        return widget
    
    def _create_time_series_tab(self):
        """创建时间序列图标签"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Z-t图
        self.z_plot = pg.PlotWidget(title="深度-时间图")
        self.z_plot.setLabel('left', 'Z位置 (m)')
        self.z_plot.setLabel('bottom', '时间 (s)')
        self.z_plot.showGrid(x=True, y=True)
        self.z_curve = self.z_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["z"], width=2))
        
        # RPY-t图
        self.rpy_plot = pg.PlotWidget(title="姿态角-时间图")
        self.rpy_plot.setLabel('left', '角度 (rad)')
        self.rpy_plot.setLabel('bottom', '时间 (s)')
        self.rpy_plot.showGrid(x=True, y=True)
        
        self.roll_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["roll"], width=2), name='Roll')
        self.pitch_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["pitch"], width=2), name='Pitch')
        self.yaw_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["yaw"], width=2), name='Yaw')
        
        # 添加图例
        self.rpy_plot.addLegend()
        
        layout.addWidget(self.z_plot)
        layout.addWidget(self.rpy_plot)
        
        return widget
    
    def _create_attitude_tab(self):
        """创建姿态显示标签"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 数值显示区域
        values_group = QGroupBox("当前数值")
        values_layout = QGridLayout(values_group)
        
        # 位置显示
        values_layout.addWidget(QLabel("位置 (m):"), 0, 0)
        self.pos_x_label = QLabel("X: 0.000")
        self.pos_y_label = QLabel("Y: 0.000") 
        self.pos_z_label = QLabel("Z: 0.000")
        values_layout.addWidget(self.pos_x_label, 0, 1)
        values_layout.addWidget(self.pos_y_label, 0, 2)
        values_layout.addWidget(self.pos_z_label, 0, 3)
        
        # 姿态显示
        values_layout.addWidget(QLabel("姿态 (rad):"), 1, 0)
        self.roll_label = QLabel("Roll: 0.000")
        self.pitch_label = QLabel("Pitch: 0.000")
        self.yaw_label = QLabel("Yaw: 0.000")
        values_layout.addWidget(self.roll_label, 1, 1)
        values_layout.addWidget(self.pitch_label, 1, 2)
        values_layout.addWidget(self.yaw_label, 1, 3)
        
        layout.addWidget(values_group)
        
        # 3D姿态可视化（简化版，使用方块表示）
        attitude_group = QGroupBox("姿态可视化")
        attitude_layout = QVBoxLayout(attitude_group)
        
        self.attitude_plot = pg.PlotWidget()
        self.attitude_plot.setAspectLocked(True)
        self.attitude_plot.setXRange(-2, 2)
        self.attitude_plot.setYRange(-2, 2)
        self.attitude_plot.hideAxis('left')
        self.attitude_plot.hideAxis('bottom')
        self.attitude_plot.setTitle("机器鱼姿态 (俯视图)")
        
        # 鱼的形状表示（简化为椭圆）
        from PyQt5.QtWidgets import QGraphicsEllipseItem
        self.fish_shape = QGraphicsEllipseItem(-0.5, -0.2, 1.0, 0.4)
        self.fish_shape.setBrush(pg.mkBrush(color='lightblue'))
        self.fish_shape.setPen(pg.mkPen(color='blue', width=2))
        self.attitude_plot.addItem(self.fish_shape)
        
        # 方向指示器
        self.direction_arrow = pg.ArrowItem(angle=0, tipAngle=30, baseAngle=20, 
                                          headLen=20, tailLen=20, tailWidth=5,
                                          pen=pg.mkPen(color='red', width=3),
                                          brush=pg.mkBrush(color='red'))
        self.attitude_plot.addItem(self.direction_arrow)
        
        attitude_layout.addWidget(self.attitude_plot)
        layout.addWidget(attitude_group)
        
        layout.addStretch()
        
        return widget
    
    def update_data(self, fish_state: FishState):
        """更新数据"""
        # 检查绘图是否开启
        if not self.plot_enabled:
            return
            
        current_time = time.time() - self.start_time
        
        # 添加新数据
        self.data_history['time'].append(current_time)
        self.data_history['x'].append(fish_state.position['x'])
        self.data_history['y'].append(fish_state.position['y'])
        self.data_history['z'].append(fish_state.position['z'])
        self.data_history['roll'].append(fish_state.orientation['roll'])
        self.data_history['pitch'].append(fish_state.orientation['pitch'])
        self.data_history['yaw'].append(fish_state.orientation['yaw'])
        
        # 更新数值标签
        self._update_value_labels(fish_state)
        
    def _update_plots(self):
        """更新图表"""
        if len(self.data_history['time']) < 2:
            return
            
        times = list(self.data_history['time'])
        
        # 更新XY轨迹图
        x_data = list(self.data_history['x'])
        y_data = list(self.data_history['y'])
        self.xy_curve.setData(x_data, y_data)
        
        # 更新当前位置点
        if x_data and y_data:
            self.xy_point.setData([x_data[-1]], [y_data[-1]])
        
        # 更新Z-t图
        z_data = list(self.data_history['z'])
        self.z_curve.setData(times, z_data)
        
        # 更新RPY-t图
        roll_data = list(self.data_history['roll'])
        pitch_data = list(self.data_history['pitch'])
        yaw_data = list(self.data_history['yaw'])
        
        self.roll_curve.setData(times, roll_data)
        self.pitch_curve.setData(times, pitch_data)
        self.yaw_curve.setData(times, yaw_data)
        
        # 更新姿态可视化
        if yaw_data:
            self._update_attitude_visualization(yaw_data[-1])
    
    def _update_value_labels(self, fish_state: FishState):
        """更新数值标签"""
        # 位置标签
        self.pos_x_label.setText(f"X: {fish_state.position['x']:.3f}")
        self.pos_y_label.setText(f"Y: {fish_state.position['y']:.3f}")
        self.pos_z_label.setText(f"Z: {fish_state.position['z']:.3f}")
        
        # 姿态标签
        self.roll_label.setText(f"Roll: {fish_state.orientation['roll']:.3f}")
        self.pitch_label.setText(f"Pitch: {fish_state.orientation['pitch']:.3f}")
        self.yaw_label.setText(f"Yaw: {fish_state.orientation['yaw']:.3f}")
    
    def _update_attitude_visualization(self, yaw_angle: float):
        """更新姿态可视化"""
        # 旋转鱼的形状
        from PyQt5.QtGui import QTransform
        transform = QTransform()
        transform.rotate(np.degrees(yaw_angle))
        self.fish_shape.setTransform(transform)
        
        # 更新方向箭头
        self.direction_arrow.setStyle(angle=np.degrees(yaw_angle))
    
    def clear_data(self):
        """清空数据"""
        for key in self.data_history:
            self.data_history[key].clear()
        self.start_time = time.time()
        
        # 清空图表显示
        self.xy_curve.setData([], [])
        self.xy_point.setData([], [])
        self.z_curve.setData([], [])
        self.roll_curve.setData([], [])
        self.pitch_curve.setData([], [])
        self.yaw_curve.setData([], [])
    
    def set_plot_enabled(self, enabled: bool):
        """设置绘图开关状态"""
        self.plot_enabled = enabled
        
        # 如果禁用绘图，可以添加一些视觉提示
        if not enabled:
            # 为所有图表添加暂停提示
            for plot_widget in [self.xy_plot, self.z_plot, self.rpy_plot]:
                if not hasattr(plot_widget, '_pause_text'):
                    pause_text = pg.TextItem("绘图已暂停", color='red', anchor=(0.5, 0.5))
                    pause_text.setPos(0, 0)
                    plot_widget.addItem(pause_text)
                    plot_widget._pause_text = pause_text
                else:
                    plot_widget._pause_text.show()
        else:
            # 移除暂停提示
            for plot_widget in [self.xy_plot, self.z_plot, self.rpy_plot]:
                if hasattr(plot_widget, '_pause_text'):
                    plot_widget._pause_text.hide()
    
    def get_plot_enabled(self) -> bool:
        """获取绘图开关状态"""
        return self.plot_enabled
