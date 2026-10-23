#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据可视化组件
Data Visualization Components
"""

import csv
import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                             QLabel, QGroupBox, QGridLayout, QSizePolicy,
                             QPushButton, QRadioButton, QButtonGroup, QSpinBox,
                             QFileDialog, QMessageBox)
from PyQt5.QtCore import QTimer, pyqtSignal, Qt
from PyQt5.QtGui import QFont
import time

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.base import FishState
from ui.system_status import SystemStatusWidget
from config import PLOT_UPDATE_RATE, UI_CONFIG

class DataVisualizationWidget(QWidget):
    """数据可视化主组件"""
    
    def __init__(self):
        """初始化完整历史缓存、绘图组件和刷新定时器。"""
        super().__init__()
        self.data_history = {
            # 全局模式必须保留从上次清除到现在的完整时域。
            # 滑动窗口只筛选显示范围，不得截断底层历史。
            'time': [],
            'x': [],
            'y': [],
            'z': [],
            'roll': [],
            'pitch': [],
            'yaw': [],
            # 双目鱼深度五路序列（米；d_cal 为扣零点后的标定值）
            'd_raw1': [],
            'd_raw2': [],
            'd_filt1': [],
            'd_filt2': [],
            'd_cal': [],
        }
        
        self.start_time = time.time()
        self.plot_enabled = True  # 绘图开关状态
        self.sliding_time = False  # 时间轴模式：False=全局，True=滑动窗口
        self.sliding_window_seconds = 10.0
        self.follow_latest = True  # 视图跟随最新数据；用户缩放/拖动后转自由视察
        self._syncing_time_axes = False
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
        self.tab_widget = tab_widget
        
        # XY平面图标签
        xy_tab = self._create_xy_plot_tab()
        tab_widget.addTab(xy_tab, "XY轨迹图")
        
        # 时间序列图标签
        time_series_tab = self._create_time_series_tab()
        tab_widget.addTab(time_series_tab, "时间序列")
        
        # 姿态显示标签
        attitude_tab = self._create_attitude_tab()
        tab_widget.addTab(attitude_tab, "姿态显示")
        self.system_status_widget = SystemStatusWidget()
        tab_widget.addTab(self.system_status_widget, '系统状态')
        
        layout.addWidget(tab_widget)
        
    def _create_xy_plot_tab(self):
        """创建XY轨迹图标签"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 清除按钮：清空历史数据，时间归零从头开始
        clear_row = QHBoxLayout()
        clear_btn = QPushButton("清除曲线（从头开始）")
        clear_btn.clicked.connect(self.clear_data)
        clear_row.addWidget(clear_btn)
        clear_row.addStretch()
        layout.addLayout(clear_row)

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

        # 时间轴参数单独一行，操作按钮另一行，避免中央画布较窄时挤压。
        mode_row = QHBoxLayout()
        action_row = QHBoxLayout()
        self.global_time_cb = QRadioButton("全局时间序列")
        self.global_time_cb.setChecked(True)
        self.sliding_time_cb = QRadioButton("滑动窗口")
        self.time_mode_group = QButtonGroup(self)
        self.time_mode_group.setExclusive(True)
        self.time_mode_group.addButton(self.global_time_cb)
        self.time_mode_group.addButton(self.sliding_time_cb)
        self.global_time_cb.toggled.connect(self._on_time_mode_toggled)
        self.sliding_time_cb.toggled.connect(self._on_time_mode_toggled)
        self.sliding_window_input = QSpinBox()
        self.sliding_window_input.setRange(1, 3600)
        self.sliding_window_input.setValue(int(self.sliding_window_seconds))
        self.sliding_window_input.setSuffix(" 秒")
        self.sliding_window_input.setEnabled(False)
        self.sliding_window_input.setKeyboardTracking(False)
        self.sliding_window_input.valueChanged.connect(
            self._on_sliding_window_changed)
        clear_btn = QPushButton("清除曲线")
        clear_btn.clicked.connect(self.clear_data)
        reset_view_btn = QPushButton("重置画布")
        reset_view_btn.setToolTip("取消缩放/拖动，恢复自适应窗口")
        reset_view_btn.clicked.connect(self._reset_time_series_view)
        self.save_time_data_btn = QPushButton("保存数据")
        self.save_time_data_btn.setToolTip(
            "仅保存当前画布可见时间范围内的深度和姿态角，可选 CSV 或 Excel")
        self.save_time_data_btn.clicked.connect(self._save_visible_time_data)
        self.save_time_image_btn = QPushButton("保存图像")
        self.save_time_image_btn.setToolTip(
            "把当前时间范围内的深度/姿态角画布保存为 PNG")
        self.save_time_image_btn.clicked.connect(self._save_time_series_image)
        mode_row.addWidget(self.global_time_cb)
        mode_row.addWidget(self.sliding_time_cb)
        mode_row.addWidget(QLabel("窗口大小"))
        mode_row.addWidget(self.sliding_window_input)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        action_row.addWidget(clear_btn)
        action_row.addWidget(reset_view_btn)
        action_row.addWidget(self.save_time_data_btn)
        action_row.addWidget(self.save_time_image_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        # Z-t图
        self.z_plot = pg.PlotWidget(title="深度-时间图")
        self.z_plot.setLabel('left', '深度')
        self.z_plot.setLabel('bottom', '时间')
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
        
        # 底部状态栏显示当前深度
        self.z_status_label = QLabel("当前深度: Z: 0.000 m")
        self.z_status_label.setStyleSheet("font-size: 11pt; padding: 5px; background-color: #f0f0f0;")
        # RPY-t图
        self.rpy_plot = pg.PlotWidget(title="姿态角-时间图")
        self.rpy_plot.setLabel('left', '角度')
        self.rpy_plot.setLabel('bottom', '时间')
        self.rpy_plot.showGrid(x=True, y=True)
        
        # 添加图例（在创建曲线之前）
        self.rpy_plot.addLegend()
        
        self.roll_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["roll"], width=2), name='Roll')
        self.pitch_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["pitch"], width=2), name='Pitch')
        self.yaw_curve = self.rpy_plot.plot(pen=pg.mkPen(color=UI_CONFIG["plot_colors"]["yaw"], width=2), name='Yaw')
        
        # 底部状态栏显示当前姿态角
        self.rpy_status_label = QLabel("当前姿态: Roll: 0.000, Pitch: 0.000, Yaw: 0.000")
        self.rpy_status_label.setStyleSheet("font-size: 11pt; padding: 5px; background-color: #f0f0f0;")

        # 可导出画布：只包含当前显示的两张时间序列图与数值标签，
        # 不把上方功能按钮一起截入 PNG。
        self.time_series_canvas = QWidget()
        self.time_series_canvas.setObjectName("timeSeriesCanvas")
        canvas_layout = QVBoxLayout(self.time_series_canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self.z_plot)
        canvas_layout.addWidget(self.z_status_label)
        canvas_layout.addWidget(self.rpy_plot)
        canvas_layout.addWidget(self.rpy_status_label)
        layout.addWidget(self.time_series_canvas)

        # 两张图的时间轴始终同步；用户在任一图上缩放/拖动后，
        # “保存数据”就能使用唯一、明确的当前时间范围。
        self.z_plot.getViewBox().sigXRangeChanged.connect(
            self._sync_time_series_x_range)
        self.rpy_plot.getViewBox().sigXRangeChanged.connect(
            self._sync_time_series_x_range)
        for plot in (self.z_plot, self.rpy_plot):
            plot.getViewBox().sigRangeChangedManually.connect(
                self._on_manual_view_change)

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

        # 双目鱼深度五路（数值本身就是 cm，直接入历史；
        # 无数据时补 None 断线，pyqtgraph 自动留空）
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
        
        # 更新 Z-t 图（按时间轴模式：全局 / 用户设定的滑动窗口）
        t_min = self._time_window_min(times)
        z_data = list(self.data_history['z'])
        z_pts = [(t, v) for t, v in zip(times, z_data) if t >= t_min]
        self.z_curve.setData([p[0] for p in z_pts], [p[1] for p in z_pts])
        # 更新双目鱼深度五路曲线（None 值段自动断线）
        for key, curve in self._depth_curves.items():
            y = list(self.data_history[key])
            pts = [(t, v) for t, v in zip(times, y)
                   if v is not None and t >= t_min]
            if pts:
                curve.setData([p[0] for p in pts], [p[1] for p in pts])
            else:
                curve.setData([], [])
        # 更新底部状态栏（优先显示标定后深度）
        cal = list(self.data_history['d_cal'])
        if cal and cal[-1] is not None:
            self.z_status_label.setText(f'标定后深度: {cal[-1]:.1f} cm')
        elif z_data:
            self.z_status_label.setText(f'当前深度: Z: {z_data[-1]:.3f} m')

        # 更新RPY-t图（同一时间轴模式）
        roll_data = list(self.data_history['roll'])
        pitch_data = list(self.data_history['pitch'])
        yaw_data = list(self.data_history['yaw'])

        roll_pts = [(t, v) for t, v in zip(times, roll_data) if t >= t_min]
        pitch_pts = [(t, v) for t, v in zip(times, pitch_data) if t >= t_min]
        yaw_pts = [(t, v) for t, v in zip(times, yaw_data) if t >= t_min]
        self.roll_curve.setData([p[0] for p in roll_pts], [p[1] for p in roll_pts])
        self.pitch_curve.setData([p[0] for p in pitch_pts], [p[1] for p in pitch_pts])
        self.yaw_curve.setData([p[0] for p in yaw_pts], [p[1] for p in yaw_pts])
        
        # 更新底部状态栏
        if roll_data and pitch_data and yaw_data:
            self.rpy_status_label.setText(f'当前姿态: Roll: {roll_data[-1]:.3f}, Pitch: {pitch_data[-1]:.3f}, Yaw: {yaw_data[-1]:.3f}')
        
        # 跟随模式：视窗每帧贴住当前时间窗（自由视察模式下不动，
        # 由 sigRangeChangedManually 感知用户缩放/拖动后切换）
        if self.follow_latest and times:
            t_max = times[-1]
            if getattr(self, "sliding_time", False):
                x0 = max(0.0, t_max - self.sliding_window_seconds)
                x1 = t_max + 0.05
            else:
                x0, x1 = 0.0, max(t_max + 0.5, 5.0)
            for plot in (self.z_plot, self.rpy_plot):
                vb = plot.getViewBox()
                vb.setXRange(x0, x1, padding=0)
                vb.enableAutoRange(y=True)

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
    
    def _on_time_mode_toggled(self, checked):
        """切换全局/滑动模式，并让视图立即回到所选模式。"""
        if not checked:
            return
        self.sliding_time = (self.sender() is self.sliding_time_cb)
        self.sliding_window_input.setEnabled(self.sliding_time)
        self.follow_latest = True
        self._update_plots()

    def _on_sliding_window_changed(self, value):
        """应用用户填写的滑动窗口秒数，并让视图重新跟随最新数据。"""
        self.sliding_window_seconds = float(value)
        if self.sliding_time:
            self.follow_latest = True
            self._update_plots()

    def _on_manual_view_change(self, *args):
        """用户缩放/拖动曲线（pyqtgraph 手动改范围信号）：停止跟随最新数据。"""
        self.follow_latest = False

    def _sync_time_series_x_range(self, source_view, x_range):
        """同步深度图与姿态角图的 X 轴，保证导出时间范围唯一。"""
        if self._syncing_time_axes:
            return
        z_view = self.z_plot.getViewBox()
        rpy_view = self.rpy_plot.getViewBox()
        target = rpy_view if source_view is z_view else z_view
        self._syncing_time_axes = True
        try:
            target.setXRange(float(x_range[0]), float(x_range[1]), padding=0)
        finally:
            self._syncing_time_axes = False

    def _reset_time_series_view(self):
        """重置画布：恢复"跟随最新数据"模式（视窗随曲线滚动）。

        三态语义：默认跟随 -> 用户缩放/拖动后转自由视察(sigRangeChangedManually
        感知) -> 重置画布回到跟随。一次性 autoRange 只在点击瞬间拟合，新数据
        到来后视窗冻结，滑动窗口会"看不到最新"，故必须恢复跟随标志。
        """
        self.follow_latest = True
        for plot in (self.z_plot, self.rpy_plot):
            plot.autoRange()

    def _time_window_min(self, times):
        """滑动窗口模式返回用户设定的时间下限；全局模式返回最早时间。"""
        if not times:
            return 0.0
        if getattr(self, "sliding_time", False):
            return max(0.0, times[-1] - self.sliding_window_seconds)
        return times[0]

    def current_visible_time_range(self):
        """返回当前画布真正可见的时间范围，无数据时返回 None。"""
        times = list(self.data_history["time"])
        if not times:
            return None
        if self.follow_latest:
            return self._time_window_min(times), times[-1]
        view_min, view_max = self.z_plot.getViewBox().viewRange()[0]
        start = max(times[0], float(min(view_min, view_max)))
        end = min(times[-1], float(max(view_min, view_max)))
        if start > end:
            return None
        return start, end

    def current_visible_time_series_rows(self):
        """按当前画布时间范围组装深度与姿态角导出行。"""
        visible_range = self.current_visible_time_range()
        if visible_range is None:
            return []
        start, end = visible_range
        sources = (
            ("time_s", "time"),
            ("depth_z_m", "z"),
            ("depth_raw_1_cm", "d_raw1"),
            ("depth_raw_2_cm", "d_raw2"),
            ("depth_filtered_1_cm", "d_filt1"),
            ("depth_filtered_2_cm", "d_filt2"),
            ("depth_calibrated_cm", "d_cal"),
            ("roll_rad", "roll"),
            ("pitch_rad", "pitch"),
            ("yaw_rad", "yaw"),
        )
        rows = []
        for index, timestamp in enumerate(self.data_history["time"]):
            if not start <= timestamp <= end:
                continue
            row = {}
            for header, key in sources:
                values = self.data_history[key]
                row[header] = values[index] if index < len(values) else None
            rows.append(row)
        return rows

    @staticmethod
    def _normalize_data_export_path(filepath, selected_filter=""):
        """根据文件对话框类型补齐 CSV/XLSX 后缀。"""
        path = Path(filepath)
        suffix = path.suffix.lower()
        if suffix not in (".csv", ".xlsx"):
            suffix = ".xlsx" if "Excel" in selected_filter else ".csv"
            path = path.with_suffix(suffix)
        return str(path)

    def export_visible_time_series(self, filepath):
        """把当前可见时间范围的深度/姿态角写入 CSV 或 XLSX。"""
        rows = self.current_visible_time_series_rows()
        if not rows:
            raise ValueError("当前画布时间范围内没有可保存的数据")
        headers = list(rows[0])
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".csv":
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        elif path.suffix.lower() == ".xlsx":
            import xlsxwriter

            workbook = xlsxwriter.Workbook(str(path))
            try:
                sheet = workbook.add_worksheet("时间序列")
                header_format = workbook.add_format({"bold": True})
                for column, header in enumerate(headers):
                    sheet.write(0, column, header, header_format)
                for row_index, row in enumerate(rows, start=1):
                    for column, header in enumerate(headers):
                        value = row[header]
                        if value is not None:
                            sheet.write(row_index, column, value)
                sheet.freeze_panes(1, 1)
                sheet.autofilter(0, 0, len(rows), len(headers) - 1)
                sheet.set_column(0, len(headers) - 1, 22)
            finally:
                workbook.close()
        else:
            raise ValueError("仅支持 CSV 或 Excel (.xlsx) 格式")
        return str(path), len(rows), rows[0]["time_s"], rows[-1]["time_s"]

    def _save_visible_time_data(self):
        """弹出资源管理器，选择路径和 CSV/Excel 格式后保存可见数据。"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = str(Path.cwd() / f"时间序列_{timestamp}.csv")
        filepath, selected_filter = QFileDialog.getSaveFileName(
            self, "保存当前时间范围数据", default_path,
            "CSV 文件 (*.csv);;Excel 工作簿 (*.xlsx)")
        if not filepath:
            return
        filepath = self._normalize_data_export_path(filepath, selected_filter)
        try:
            saved_path, count, start, end = self.export_visible_time_series(filepath)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        QMessageBox.information(
            self, "保存成功",
            f"已保存 {count} 条数据\n时间范围: {start:.3f} - {end:.3f} s\n{saved_path}")

    @staticmethod
    def _normalize_png_path(filepath):
        """为画布图片路径补齐 PNG 后缀。"""
        path = Path(filepath)
        return str(path if path.suffix.lower() == ".png"
                   else path.with_suffix(".png"))

    def export_time_series_png(self, filepath):
        """把当前时间序列画布按屏幕所见内容保存为 PNG。"""
        path = Path(self._normalize_png_path(filepath))
        path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = self.time_series_canvas.grab()
        if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
            raise OSError("画布 PNG 写入失败")
        return str(path)

    def _save_time_series_image(self):
        """弹出资源管理器，把当前可见画布保存为 PNG。"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = str(Path.cwd() / f"时间序列画布_{timestamp}.png")
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存当前时序画布", default_path, "PNG 图像 (*.png)")
        if not filepath:
            return
        try:
            saved_path = self.export_time_series_png(filepath)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        QMessageBox.information(self, "保存成功", f"画布已保存为:\n{saved_path}")

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
