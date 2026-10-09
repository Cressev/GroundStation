#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据可视化组件
Data Visualization Components
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                             QLabel, QGroupBox, QGridLayout, QSizePolicy)
from PyQt5.QtCore import QTimer, pyqtSignal, Qt
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
            'yaw': deque(maxlen=PLOT_HISTORY_LENGTH),
            # 双目鱼深度五路序列（米；d_cal 为扣零点后的标定值）
            'd_raw1': deque(maxlen=PLOT_HISTORY_LENGTH),
            'd_raw2': deque(maxlen=PLOT_HISTORY_LENGTH),
            'd_filt1': deque(maxlen=PLOT_HISTORY_LENGTH),
            'd_filt2': deque(maxlen=PLOT_HISTORY_LENGTH),
            'd_cal': deque(maxlen=PLOT_HISTORY_LENGTH),
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
        
        # 添加图例（在创建曲线之前）
        self.xy_plot.addLegend()
        
        # 轨迹线
        self.xy_curve = self.xy_plot.plot(pen=pg.mkPen(color='blue', width=2), name='轨迹')
        # 当前位置点
        self.xy_point = self.xy_plot.plot(
            pen=None,
            symbol='o',
            symbolSize=10,
            symbolBrush=pg.mkBrush(color='red'),
            name='当前位置'
        )
        
        layout.addWidget(self.xy_plot)
        
        # 底部状态栏显示当前位置
        self.xy_status_label = QLabel("当前位置: X: 0.000 m, Y: 0.000 m")
        self.xy_status_label.setStyleSheet("font-size: 11pt; padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(self.xy_status_label)
        
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
        
        # 添加图例（在创建曲线之前）
        self.z_plot.addLegend()
        
        self.z_curve = self.z_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["z"], width=2), name='深度')

        # 双目鱼深度五路曲线（10Hz，标定后=融合值扣零点）
        self._depth_curves = {
            'd_raw1': self.z_plot.plot(pen=pg.mkPen(color='#7f7f7f', width=1), name='原始1'),
            'd_raw2': self.z_plot.plot(pen=pg.mkPen(color='#c49c94', width=1), name='原始2'),
            'd_filt1': self.z_plot.plot(pen=pg.mkPen(color='#1f77b4', width=2), name='滤波1'),
            'd_filt2': self.z_plot.plot(pen=pg.mkPen(color='#2ca02c', width=2), name='滤波2'),
            'd_cal': self.z_plot.plot(pen=pg.mkPen(color='#d62728', width=2), name='标定后'),
        }
        
        layout.addWidget(self.z_plot)
        
        # 底部状态栏显示当前深度
        self.z_status_label = QLabel("当前深度: Z: 0.000 m")
        self.z_status_label.setStyleSheet("font-size: 11pt; padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(self.z_status_label)
        
        # RPY-t图
        self.rpy_plot = pg.PlotWidget(title="姿态角-时间图")
        self.rpy_plot.setLabel('left', '角度 (rad)')
        self.rpy_plot.setLabel('bottom', '时间 (s)')
        self.rpy_plot.showGrid(x=True, y=True)
        
        # 添加图例（在创建曲线之前）
        self.rpy_plot.addLegend()
        
        self.roll_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["roll"], width=2), name='Roll')
        self.pitch_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["pitch"], width=2), name='Pitch')
        self.yaw_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["yaw"], width=2), name='Yaw')
        
        layout.addWidget(self.z_plot)
        layout.addWidget(self.rpy_plot)
        
        # 底部状态栏显示当前姿态角
        self.rpy_status_label = QLabel("当前姿态: Roll: 0.000, Pitch: 0.000, Yaw: 0.000")
        self.rpy_status_label.setStyleSheet("font-size: 11pt; padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(self.rpy_status_label)
        
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
        
        
        # 3D姿态可视化（使用OpenGL）
        attitude_group = QGroupBox("3D姿态可视化 (鼠标拖拽旋转视角)")
        attitude_layout = QVBoxLayout(attitude_group)
        
        self._3d_enabled = False
        try:
            import pyqtgraph.opengl as gl
            print("PyQtGraph OpenGL导入成功")
            
            # 创建3D视图
            self.gl_widget = gl.GLViewWidget()
            self.gl_widget.setCameraPosition(distance=5, elevation=30, azimuth=45)
            self.gl_widget.setBackgroundColor('w')  # 白色背景
            # 设置最小尺寸，确保视图可见
            self.gl_widget.setMinimumSize(300, 220)
            self.gl_widget.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Expanding
            )
            print("GLViewWidget创建成功")
            
            # 添加坐标网格
            grid = gl.GLGridItem()
            grid.scale(1, 1, 1)
            grid.setDepthValue(10)
            self.gl_widget.addItem(grid)
            print("坐标网格添加成功")
            
            # 添加坐标轴
            axis = gl.GLAxisItem()
            axis.setSize(2, 2, 2)
            self.gl_widget.addItem(axis)
            print("坐标轴添加成功")
            
            # 创建鱼形3D模型
            self._create_fish_3d_model()
            print("3D鱼形模型创建成功")
            
            # 确保视图可见
            self.gl_widget.show()
            attitude_layout.addWidget(self.gl_widget)
            self._3d_enabled = True
            print("3D视图启用成功")
            
        except ImportError as e:
            print(f"OpenGL导入失败: {e}")
            fallback_label = QLabel(f"3D显示不可用 (需要PyOpenGL)\n请安装: pip install PyOpenGL PyOpenGL_accelerate\n错误: {e}")
            fallback_label.setAlignment(Qt.AlignCenter)
            attitude_layout.addWidget(fallback_label)
        except Exception as e:
            print(f"3D视图创建失败: {e}")
            import traceback
            traceback.print_exc()
            fallback_label = QLabel(f"3D显示初始化失败\n错误: {str(e)[:100]}")
            fallback_label.setAlignment(Qt.AlignCenter)
            attitude_layout.addWidget(fallback_label)
        
        layout.addWidget(attitude_group)
        layout.addStretch()
        
        return widget
    
    def _create_fish_3d_model(self):
        """创建3D鱼形模型（兼容版）"""
        import pyqtgraph.opengl as gl
        
        # 鱼身体参数
        body_length = 1.2
        body_width = 0.3
        body_height = 0.25
        
        # 创建更流线型的鱼身体（增加顶点让形状更圆滑）
        verts = np.array([
            # 鱼头尖端
            [body_length/2, 0, 0],
            
            # 头部截面（较小）
            [body_length/3, body_width*0.4, body_height*0.3],
            [body_length/3, body_width*0.2, body_height*0.5],
            [body_length/3, -body_width*0.2, body_height*0.5],
            [body_length/3, -body_width*0.4, body_height*0.3],
            [body_length/3, -body_width*0.4, -body_height*0.3],
            [body_length/3, -body_width*0.2, -body_height*0.5],
            [body_length/3, body_width*0.2, -body_height*0.5],
            [body_length/3, body_width*0.4, -body_height*0.3],
            
            # 身体中部（最粗）
            [0, body_width*0.7, body_height*0.5],
            [0, body_width*0.5, body_height*0.8],
            [0, -body_width*0.5, body_height*0.8],
            [0, -body_width*0.7, body_height*0.5],
            [0, -body_width*0.7, -body_height*0.5],
            [0, -body_width*0.5, -body_height*0.8],
            [0, body_width*0.5, -body_height*0.8],
            [0, body_width*0.7, -body_height*0.5],
            
            # 尾部收窄
            [-body_length*0.35, body_width*0.3, body_height*0.2],
            [-body_length*0.35, -body_width*0.3, body_height*0.2],
            [-body_length*0.35, -body_width*0.3, -body_height*0.2],
            [-body_length*0.35, body_width*0.3, -body_height*0.2],
            
            # 尾巴根部
            [-body_length/2, 0, 0],
            
            # 月牙形尾巴上叶
            [-body_length/2 - 0.15, 0, 0.15],
            [-body_length/2 - 0.3, 0, 0.25],
            [-body_length/2 - 0.4, 0, 0.2],
            
            # 尾巴尖端
            [-body_length/2 - 0.45, 0, 0],
            
            # 月牙形尾巴下叶
            [-body_length/2 - 0.4, 0, -0.2],
            [-body_length/2 - 0.3, 0, -0.25],
            [-body_length/2 - 0.15, 0, -0.15],
        ], dtype=float)
        
        # 定义三角面
        faces = []
        
        # 头部锥形（0是尖端，1-8是第一圈）
        for i in range(1, 9):
            next_i = i + 1 if i < 8 else 1
            faces.append([0, i, next_i])
        
        # 第一圈到第二圈（1-8 到 9-16）
        for i in range(8):
            curr = i + 1
            next = (i + 1) % 8 + 1
            curr2 = i + 9
            next2 = (i + 1) % 8 + 9
            faces.append([curr, curr2, next2])
            faces.append([curr, next2, next])
        
        # 第二圈到第三圈（9-16 到 17-20）
        faces.extend([
            [9, 17, 10], [10, 17, 18], [10, 18, 11],
            [11, 18, 19], [11, 19, 12], [12, 19, 13],
            [13, 19, 20], [13, 20, 14], [14, 20, 15],
            [15, 20, 17], [15, 17, 16], [16, 17, 9],
        ])
        
        # 第三圈到尾根（17-20 到 21）
        faces.extend([
            [17, 21, 18], [18, 21, 19],
            [19, 21, 20], [20, 21, 17],
        ])
        
        # 尾巴上叶（21-22-23-24-25）
        faces.extend([
            [21, 22, 23], [21, 23, 24],
            [21, 24, 25],
        ])
        
        # 尾巴下叶（21-28-27-26-25）
        faces.extend([
            [21, 28, 27], [21, 27, 26],
            [21, 26, 25],
        ])
        
        faces = np.array(faces, dtype=np.uint32)
        
        # 橙红色锦鲤配色
        colors = np.ones((len(faces), 4))
        colors[:, 0] = 0.9   # R
        colors[:, 1] = 0.45  # G
        colors[:, 2] = 0.15  # B
        colors[:, 3] = 0.95  # Alpha
        
        # 尾巴颜色稍深
        tail_start_face = len(faces) - 6
        colors[tail_start_face:, 0] = 0.8
        colors[tail_start_face:, 1] = 0.35
        colors[tail_start_face:, 2] = 0.1
        
        # 创建鱼身网格（启用轮廓线）
        self.fish_mesh = gl.GLMeshItem(
            vertexes=verts,
            faces=faces,
            faceColors=colors,
            smooth=True,
            drawEdges=True,  # 启用边缘绘制
            edgeColor=(0.3, 0.15, 0.05, 1)  # 深褐色轮廓
        )
        self.gl_widget.addItem(self.fish_mesh)
        
        # === 添加胸鳍（两侧） ===
        fin_base_x = body_length/4  # 胸鳍位置（靠前）
        fin_length = 0.3
        fin_width = 0.15
        
        # 右侧胸鳍
        right_fin_verts = np.array([
            [fin_base_x, body_width/2, 0],  # 基座
            [fin_base_x - 0.1, body_width/2 + fin_length, -fin_width],  # 鳍尖
            [fin_base_x + 0.1, body_width/2 + fin_length, -fin_width],
        ])
        right_fin_faces = np.array([[0, 1, 2]], dtype=np.uint32)
        right_fin_colors = np.array([[0.85, 0.4, 0.1, 0.9]])
        
        self.right_pec_fin = gl.GLMeshItem(
            vertexes=right_fin_verts,
            faces=right_fin_faces,
            faceColors=right_fin_colors,
            smooth=True,
            drawEdges=True,
            edgeColor=(0.3, 0.15, 0.05, 1)
        )
        self.gl_widget.addItem(self.right_pec_fin)
        
        # 左侧胸鳍
        left_fin_verts = np.array([
            [fin_base_x, -body_width/2, 0],
            [fin_base_x - 0.1, -body_width/2 - fin_length, -fin_width],
            [fin_base_x + 0.1, -body_width/2 - fin_length, -fin_width],
        ])
        left_fin_faces = np.array([[0, 1, 2]], dtype=np.uint32)
        left_fin_colors = np.array([[0.85, 0.4, 0.1, 0.9]])
        
        self.left_pec_fin = gl.GLMeshItem(
            vertexes=left_fin_verts,
            faces=left_fin_faces,
            faceColors=left_fin_colors,
            smooth=True,
            drawEdges=True,
            edgeColor=(0.3, 0.15, 0.05, 1)
        )
        self.gl_widget.addItem(self.left_pec_fin)
        
        # === 添加背鳍（鱼背标识） ===
        dorsal_fin_x = body_length/8  # 背鳍位置在鱼背中部
        dorsal_fin_height = 0.35  # 背鳍高度
        dorsal_fin_width = 0.25  # 背鳍宽度
        
        # 三角形背鳍（垂直向上）
        dorsal_fin_verts = np.array([
            [dorsal_fin_x + dorsal_fin_width/2, 0, body_height/2],  # 基座前端
            [dorsal_fin_x - dorsal_fin_width/2, 0, body_height/2],  # 基座后端
            [dorsal_fin_x, 0, body_height/2 + dorsal_fin_height],  # 鳍尖（向上）
        ])
        dorsal_fin_faces = np.array([[0, 1, 2]], dtype=np.uint32)
        # 背鳍使用深色以便区分
        dorsal_fin_colors = np.array([[0.7, 0.3, 0.05, 0.95]])
        
        self.dorsal_fin = gl.GLMeshItem(
            vertexes=dorsal_fin_verts,
            faces=dorsal_fin_faces,
            faceColors=dorsal_fin_colors,
            smooth=True,
            drawEdges=True,
            edgeColor=(0.3, 0.15, 0.05, 1)
        )
        self.gl_widget.addItem(self.dorsal_fin)
        
        print("3D鱼形模型创建成功")
        
        # 方向箭头
        arrow_verts = np.array([
            [body_length/2 + 0.1, 0, 0],
            [body_length/2 + 0.5, 0, 0],
        ])
        self.direction_line = gl.GLLinePlotItem(
            pos=arrow_verts,
            color=(1, 0, 0, 1),
            width=4,
            antialias=True
        )
        self.gl_widget.addItem(self.direction_line)
        
        # 箭头尖
        arrow_head = np.array([
            [body_length/2 + 0.5, 0, 0],
            [body_length/2 + 0.35, 0.08, 0],
            [body_length/2 + 0.35, -0.08, 0],
            [body_length/2 + 0.5, 0, 0],
        ])
        self.arrow_head = gl.GLLinePlotItem(
            pos=arrow_head,
            color=(1, 0, 0, 1),
            width=4,
            antialias=True,
            mode='line_strip'
        )
        self.gl_widget.addItem(self.arrow_head)


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

        # 双目鱼深度五路（无数据时补 None 断线，pyqtgraph 自动留空）
        d = getattr(fish_state, 'depth', None) or {}
        for key, field in (('d_raw1', 'raw_1'), ('d_raw2', 'raw_2'),
                           ('d_filt1', 'filtered_1'), ('d_filt2', 'filtered_2'),
                           ('d_cal', 'calibrated')):
            self.data_history[key].append(d.get(field))
        
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
            # 更新底部状态栏
            self.xy_status_label.setText(f'当前位置: X: {x_data[-1]:.3f} m, Y: {y_data[-1]:.3f} m')
        
        # 更新Z-t图
        z_data = list(self.data_history['z'])
        self.z_curve.setData(times, z_data)
        # 更新双目鱼深度五路曲线（None 值段自动断线）
        for key, curve in self._depth_curves.items():
            y = list(self.data_history[key])
            pts = [(t, v) for t, v in zip(times, y) if v is not None]
            if pts:
                curve.setData([p[0] for p in pts], [p[1] for p in pts])
            else:
                curve.setData([], [])
        # 更新底部状态栏（优先显示标定后深度）
        cal = list(self.data_history['d_cal'])
        if cal and cal[-1] is not None:
            self.z_status_label.setText(f'当前深度(标定后): {cal[-1]:.3f} m')
        elif z_data:
            self.z_status_label.setText(f'当前深度: Z: {z_data[-1]:.3f} m')
        
        # 更新RPY-t图
        roll_data = list(self.data_history['roll'])
        pitch_data = list(self.data_history['pitch'])
        yaw_data = list(self.data_history['yaw'])
        
        self.roll_curve.setData(times, roll_data)
        self.pitch_curve.setData(times, pitch_data)
        self.yaw_curve.setData(times, yaw_data)
        
        # 更新底部状态栏
        if roll_data and pitch_data and yaw_data:
            self.rpy_status_label.setText(f'当前姿态: Roll: {roll_data[-1]:.3f}, Pitch: {pitch_data[-1]:.3f}, Yaw: {yaw_data[-1]:.3f}')
        
        # 更新姿态可视化
        if roll_data and pitch_data and yaw_data:
            self._update_attitude_visualization(
                roll_data[-1], pitch_data[-1], yaw_data[-1]
            )
    
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
    
    def _update_attitude_visualization(self, roll: float, pitch: float, yaw: float):
        """更新3D姿态可视化"""
        if not hasattr(self, '_3d_enabled') or not self._3d_enabled:
            return
        
        try:
            from pyqtgraph.opengl import GLMeshItem
            from PyQt5.QtGui import QMatrix4x4
            
            # 创建QMatrix4x4旋转矩阵
            transform = QMatrix4x4()
            transform.setToIdentity()
            
            # 应用旋转 - ZYX顺序 (yaw -> pitch -> roll)
            # 注意: pyqtgraph使用度数
            transform.rotate(np.degrees(-yaw), 0, 0, 1)    # 绕Z轴旋转 (yaw，反转)
            transform.rotate(np.degrees(-pitch), 0, 1, 0)  # 绕Y轴旋转 (pitch，反转)
            transform.rotate(np.degrees(roll), 1, 0, 0)   # 绕X轴旋转 (roll)
            
            # 应用变换到鱼身网格和背鳍
            self.fish_mesh.setTransform(transform)
            if hasattr(self, 'dorsal_fin'):
                self.dorsal_fin.setTransform(transform)
            if hasattr(self, 'right_pec_fin'):
                self.right_pec_fin.setTransform(transform)
            if hasattr(self, 'left_pec_fin'):
                self.left_pec_fin.setTransform(transform)
            
            # 更新方向箭头
            # 计算旋转后的箭头位置
            body_length = 1.5
            arrow_start = np.array([body_length/2 + 0.1, 0, 0])
            arrow_end = np.array([body_length/2 + 0.6, 0, 0])
            
            # 使用numpy计算旋转
            cos_r, sin_r = np.cos(roll), np.sin(roll)
            cos_p, sin_p = np.cos(-pitch), np.sin(-pitch)  # 反转pitch
            cos_y, sin_y = np.cos(-yaw), np.sin(-yaw)      # 反转yaw
            
            # ZYX旋转矩阵
            R = np.array([
                [cos_y*cos_p, cos_y*sin_p*sin_r - sin_y*cos_r, cos_y*sin_p*cos_r + sin_y*sin_r],
                [sin_y*cos_p, sin_y*sin_p*sin_r + cos_y*cos_r, sin_y*sin_p*cos_r - cos_y*sin_r],
                [-sin_p, cos_p*sin_r, cos_p*cos_r]
            ])
            
            rotated_start = R @ arrow_start
            rotated_end = R @ arrow_end
            
            self.direction_line.setData(pos=np.array([rotated_start, rotated_end]))
            
            # 箭头头部
            head1 = np.array([body_length/2 + 0.4, 0.1, 0])
            head2 = np.array([body_length/2 + 0.4, -0.1, 0])
            rotated_head1 = R @ head1
            rotated_head2 = R @ head2
            
            self.arrow_head.setData(pos=np.array([rotated_end, rotated_head1, rotated_head2]))
            
        except Exception as e:
            print(f"姿态更新异常: {e}")
    
    def clear_data(self):
        """清空数据"""
        for key in self.data_history:
            self.data_history[key].clear()
        self.start_time = time.time()
        
        # 清空图表显示
        self.xy_curve.setData([], [])
        self.xy_point.setData([], [])
        self.z_curve.setData([], [])
        for curve in self._depth_curves.values():
            curve.setData([], [])
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
