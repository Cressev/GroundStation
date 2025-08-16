#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口界面
Main Window Interface
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QMenuBar, QStatusBar, QAction, QTabWidget,
                             QGroupBox, QGridLayout, QLabel, QPushButton,
                             QComboBox, QMessageBox, QSplitter, QTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence, QIcon

from ui.visualization import DataVisualizationWidget
from ui.keyboard_status import KeyboardStatusWidget
from ui.video_display import VideoDisplayWidget
from controllers.base import KeyboardController
from communication.ssh_ros import SSHROSCommunication
from communication.base import FishState, ControlCommand
from config import UI_CONFIG, KEYBOARD_MAPPING

class MainWindow(QMainWindow):
    """主窗口类"""
    
    def __init__(self):
        super().__init__()
        
        # 初始化组件
        self.communication = None
        self.current_controller = None
        self.controllers = {}
        
        # 初始化界面
        self._init_ui()
        self._init_controllers()
        self._init_connections()
        
        # 数据更新定时器
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self._update_data)
        
    def _init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle(UI_CONFIG["window_title"])
        self.setGeometry(100, 100, *UI_CONFIG["window_size"])
        
        # 创建菜单栏
        self._create_menu_bar()
        
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("系统启动完成")
        
        # 创建中央组件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 创建分割器
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)
        
        # 左侧控制面板
        control_panel = self._create_control_panel()
        main_splitter.addWidget(control_panel)
        
        # 中央区域 - 包含数据可视化和视频显示
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建中央标签页
        center_tabs = QTabWidget()
        
        # 数据可视化标签页
        self.visualization_widget = DataVisualizationWidget()
        center_tabs.addTab(self.visualization_widget, "数据可视化")
        
        # 视频监控标签页
        self.video_widget = VideoDisplayWidget()
        center_tabs.addTab(self.video_widget, "视频监控")
        
        center_layout.addWidget(center_tabs)
        main_splitter.addWidget(center_widget)
        
        # 右侧按键状态面板
        self.keyboard_status_widget = KeyboardStatusWidget()
        main_splitter.addWidget(self.keyboard_status_widget)
        
        # 设置分割器比例 (控制面板:中央区域:按键状态 = 2:6:2)
        main_splitter.setSizes([250, 700, 250])
        
    def _create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu('文件(&F)')
        
        exit_action = QAction('退出(&X)', self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 连接菜单
        connection_menu = menubar.addMenu('连接(&C)')
        
        self.connect_action = QAction('连接机器鱼(&C)', self)
        self.connect_action.triggered.connect(self._toggle_connection)
        connection_menu.addAction(self.connect_action)
        
        # 视频菜单
        video_menu = menubar.addMenu('视频(&V)')
        
        start_video_action = QAction('启动摄像头(&S)', self)
        start_video_action.triggered.connect(lambda: self.video_widget._start_camera())
        video_menu.addAction(start_video_action)
        
        stop_video_action = QAction('停止摄像头(&T)', self)
        stop_video_action.triggered.connect(lambda: self.video_widget._stop_camera())
        video_menu.addAction(stop_video_action)
        
        video_menu.addSeparator()
        
        snapshot_action = QAction('保存快照(&P)', self)
        snapshot_action.triggered.connect(self._save_video_snapshot)
        video_menu.addAction(snapshot_action)
        
        # 控制菜单
        control_menu = menubar.addMenu('控制(&O)')
        
        keyboard_action = QAction('键盘控制(&K)', self)
        keyboard_action.triggered.connect(lambda: self._switch_controller('keyboard'))
        control_menu.addAction(keyboard_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu('帮助(&H)')
        
        about_action = QAction('关于(&A)', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 连接状态组
        connection_group = QGroupBox("连接状态")
        connection_layout = QGridLayout(connection_group)
        
        self.connection_status_label = QLabel("未连接")
        self.connection_button = QPushButton("连接")
        self.connection_button.clicked.connect(self._toggle_connection)
        
        connection_layout.addWidget(QLabel("状态:"), 0, 0)
        connection_layout.addWidget(self.connection_status_label, 0, 1)
        connection_layout.addWidget(self.connection_button, 1, 0, 1, 2)
        
        layout.addWidget(connection_group)
        
        # 控制方式选择组
        control_group = QGroupBox("控制方式")
        control_layout = QVBoxLayout(control_group)
        
        self.controller_combo = QComboBox()
        self.controller_combo.addItem("键盘控制", "keyboard")
        self.controller_combo.addItem("Xbox控制器", "xbox")  # 预留
        self.controller_combo.addItem("自主控制", "autonomous")  # 预留
        self.controller_combo.currentIndexChanged.connect(self._on_controller_changed)
        
        control_layout.addWidget(QLabel("选择控制方式:"))
        control_layout.addWidget(self.controller_combo)
        
        # 控制器专用界面容器
        self.controller_widget_container = QWidget()
        self.controller_widget_layout = QVBoxLayout(self.controller_widget_container)
        control_layout.addWidget(self.controller_widget_container)
        
        layout.addWidget(control_group)
        
        # 系统信息组
        info_group = QGroupBox("系统信息")
        info_layout = QVBoxLayout(info_group)
        
        self.info_text = QTextEdit()
        self.info_text.setMaximumHeight(150)
        self.info_text.setReadOnly(True)
        info_layout.addWidget(self.info_text)
        
        layout.addWidget(info_group)
        
        layout.addStretch()
        
        return panel
    
    def _init_controllers(self):
        """初始化控制器"""
        # 键盘控制器
        self.controllers['keyboard'] = KeyboardController()
        
        # 默认选择键盘控制器
        self._switch_controller('keyboard')
        
    def _init_connections(self):
        """初始化信号连接"""
        # 控制器信号连接
        for controller in self.controllers.values():
            controller.control_command_generated.connect(self._on_control_command)
            controller.status_changed.connect(self._on_controller_status_changed)
        
        # 按键状态组件信号连接
        self.keyboard_status_widget.plot_toggled.connect(self._on_plot_toggled)
        self.keyboard_status_widget.plot_cleared.connect(self._on_plot_cleared)
    
    def _switch_controller(self, controller_name: str):
        """切换控制器"""
        if controller_name not in self.controllers:
            self._log_message(f"未知控制器: {controller_name}")
            return
            
        # 停用当前控制器
        if self.current_controller:
            self.current_controller.deactivate()
            
        # 切换到新控制器
        self.current_controller = self.controllers[controller_name]
        
        # 更新控制器界面
        self._update_controller_widget()
        
        # 激活新控制器
        self.current_controller.activate()
        
        self._log_message(f"已切换到{controller_name}控制器")
    
    def _update_controller_widget(self):
        """更新控制器界面"""
        # 清空当前界面
        for i in reversed(range(self.controller_widget_layout.count())):
            self.controller_widget_layout.itemAt(i).widget().setParent(None)
        
        # 添加新的控制器界面
        if self.current_controller:
            widget = self.current_controller.get_control_widget()
            self.controller_widget_layout.addWidget(widget)
    
    def _on_controller_changed(self, index):
        """控制器选择改变事件"""
        controller_name = self.controller_combo.itemData(index)
        self._switch_controller(controller_name)
    
    def _toggle_connection(self):
        """切换连接状态"""
        if self.communication is None or not self.communication.connected:
            self._connect_to_fish()
        else:
            self._disconnect_from_fish()
    
    def _connect_to_fish(self):
        """连接到机器鱼"""
        try:
            self.communication = SSHROSCommunication()
            self.connection_button.setEnabled(False)
            self.connection_button.setText("连接中...")
            self.status_bar.showMessage("正在连接机器鱼...")
            
            # 异步连接（简化处理，实际应该使用线程）
            if self.communication.connect():
                self.connection_status_label.setText("已连接")
                self.connection_button.setText("断开")
                self.connection_button.setEnabled(True)
                self.connect_action.setText("断开连接(&D)")
                self.status_bar.showMessage("机器鱼连接成功")
                
                # 启动数据更新
                self.data_timer.start(50)  # 20Hz
                
                self._log_message("机器鱼连接成功")
            else:
                self.connection_status_label.setText("连接失败")
                self.connection_button.setText("连接")
                self.connection_button.setEnabled(True)
                self.status_bar.showMessage("机器鱼连接失败")
                self._log_message("机器鱼连接失败")
                
        except Exception as e:
            self.connection_button.setEnabled(True)
            self.connection_button.setText("连接")
            self._log_message(f"连接异常: {e}")
            QMessageBox.critical(self, "连接错误", f"连接失败: {e}")
    
    def _disconnect_from_fish(self):
        """断开机器鱼连接"""
        try:
            self.data_timer.stop()
            
            if self.communication:
                self.communication.disconnect()
                self.communication = None
                
            self.connection_status_label.setText("未连接")
            self.connection_button.setText("连接")
            self.connect_action.setText("连接机器鱼(&C)")
            self.status_bar.showMessage("已断开连接")
            
            self._log_message("已断开机器鱼连接")
            
        except Exception as e:
            self._log_message(f"断开连接异常: {e}")
    
    def _update_data(self):
        """更新数据"""
        if self.communication and self.communication.connected:
            try:
                fish_state = self.communication.get_fish_state()
                if fish_state:
                    self.visualization_widget.update_data(fish_state)
            except Exception as e:
                self._log_message(f"数据更新异常: {e}")
    
    def _on_control_command(self, command: ControlCommand):
        """处理控制命令"""
        if self.communication and self.communication.connected:
            try:
                success = self.communication.send_control_command(command)
                if not success:
                    self._log_message("控制命令发送失败")
            except Exception as e:
                self._log_message(f"控制命令发送异常: {e}")
    
    def _on_controller_status_changed(self, message: str):
        """控制器状态改变事件"""
        self._log_message(message)
    
    def _on_plot_toggled(self, enabled: bool):
        """绘图开关切换事件"""
        self.visualization_widget.set_plot_enabled(enabled)
        status = "开启" if enabled else "暂停"
        self._log_message(f"绘图状态已{status}")
    
    def _on_plot_cleared(self):
        """清空绘图数据事件"""
        self.visualization_widget.clear_data()
        self._log_message("绘图数据已清空")
    
    def _save_video_snapshot(self):
        """保存视频快照"""
        try:
            filename = self.video_widget.save_snapshot()
            if filename:
                self._log_message(f"视频快照已保存: {filename}")
                QMessageBox.information(self, "快照保存", f"快照已保存到: {filename}")
            else:
                self._log_message("保存快照失败: 没有可用的视频帧")
                QMessageBox.warning(self, "保存失败", "没有可用的视频帧")
        except Exception as e:
            self._log_message(f"保存快照异常: {e}")
            QMessageBox.critical(self, "保存错误", f"保存快照失败: {e}")
    
    def _log_message(self, message: str):
        """记录消息"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.info_text.append(formatted_message)
        print(formatted_message)  # 同时输出到控制台
    
    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于", 
                         "机器鱼控制系统\n"
                         "Fish Robot Control System\n\n"
                         "版本: 1.0\n"
                         "作者: 开发团队")
    
    def keyPressEvent(self, event):
        """键盘按下事件"""
        if isinstance(self.current_controller, KeyboardController):
            key_text = event.text().upper()
            if not key_text:
                # 处理特殊键
                key_map = {
                    Qt.Key_Space: "Space",
                    Qt.Key_Up: "Up",
                    Qt.Key_Down: "Down", 
                    Qt.Key_Left: "Left",
                    Qt.Key_Right: "Right"
                }
                key_text = key_map.get(event.key(), "")
            
            if key_text:
                # 更新控制器
                self.current_controller.handle_key_press(key_text)
                # 更新按键状态显示
                self.keyboard_status_widget.update_key_state(key_text, True)
                # 处理特殊功能键
                self.keyboard_status_widget.handle_special_keys(key_text, True)
        
        super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event):
        """键盘释放事件"""
        if isinstance(self.current_controller, KeyboardController):
            key_text = event.text().upper()
            if not key_text:
                # 处理特殊键
                key_map = {
                    Qt.Key_Space: "Space",
                    Qt.Key_Up: "Up",
                    Qt.Key_Down: "Down",
                    Qt.Key_Left: "Left", 
                    Qt.Key_Right: "Right"
                }
                key_text = key_map.get(event.key(), "")
            
            if key_text:
                # 更新控制器
                self.current_controller.handle_key_release(key_text)
                # 更新按键状态显示
                self.keyboard_status_widget.update_key_state(key_text, False)
        
        super().keyReleaseEvent(event)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停用控制器
        if self.current_controller:
            self.current_controller.deactivate()
            
        # 断开连接
        if self.communication and self.communication.connected:
            self.communication.disconnect()
        
        # 停止视频
        if hasattr(self, 'video_widget'):
            self.video_widget._stop_camera()
            
        event.accept()
