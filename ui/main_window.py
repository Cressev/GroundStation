#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口界面
Main Window Interface
"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QMenuBar, QStatusBar, QAction, QTabWidget,
                             QGroupBox, QGridLayout, QLabel, QPushButton,
                             QComboBox, QMessageBox, QSplitter, QTextEdit,
                             QLineEdit, QScrollArea, QApplication, QCheckBox,
                             QSizePolicy, QActionGroup)
from PyQt5.QtCore import Qt, QSettings, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QKeySequence, QIcon

from ui.visualization import DataVisualizationWidget
from ui.keyboard_status import KeyboardStatusWidget
from ui.video_display import VideoMonitorWidget
from ui.data_recording import DataRecordingWidget
from ui.stereo_camera_widget import StereoFishCameraWidget
from ui.image_enhancement_widget import ImageEnhancementWidget
from ui.depth_panel import DepthPanel
from ui.connection_store import ConnectionStore
from ui.heartbeat_light import HeartbeatLight
from controllers.base import KeyboardController
from controllers.depth import DepthController
from communication.socket_client import SocketCommunication
from communication.base import FishState, ControlCommand
from config import (UI_CONFIG, KEYBOARD_MAPPING, FISH_IP, SOCKET_PORT,
                    DUAL_FISH_CONFIG)

class MainWindow(QMainWindow):
    """主窗口类"""
    
    # 定义信号用于线程安全的UI更新
    connection_changed_signal = pyqtSignal(object, bool)  # 携带连接实例，可忽略旧线程的迟到信号
    heartbeat_pulse_signal = pyqtSignal(int)      # 心跳拍信号（心跳线程→UI呼吸灯）
    
    def __init__(self, variant="single"):
        """按鱼体变体（dual/single）初始化主窗口与各面板。"""
        super().__init__()

        # 机器鱼变体: "dual"=双尾双目鱼(pico) / "single"=单尾单目鱼(orangepi)
        self.variant = variant
        # 连接档案（本地 JSON，双尾鱼页面使用）
        self.connection_store = ConnectionStore()

        # 初始化组件
        self.communication = None
        self._fish_connection_state = "disconnected"
        self._control_armed = False
        self.current_controller = None
        self._current_controller_name = None
        self.controllers = {}
        self._last_control_command = None  # 最后的控制命令，用于数据记录
        self.connection_start_time = None  # 连接开始时间
        self._settings = QSettings("FishRobot", "GroundStation")
        
        # 初始化界面
        self._init_ui()
        self._init_controllers()
        self._init_connections()
        self._apply_main_ui_state()
        
        # 设置焦点策略以接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()
        
        self._log_message("系统初始化完成")
        
        # 数据更新定时器
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self._update_data)
        
        # 连接时间更新定时器
        self.connection_timer = QTimer()
        self.connection_timer.timeout.connect(self._update_connection_time)
        self.connection_timer.start(1000)  # 每秒更新一次
        
    def _init_ui(self):
        """初始化用户界面"""
        variant_title = ("双尾双目鱼" if self.variant == "dual" else "单尾单目鱼")
        self.setWindowTitle(f'{UI_CONFIG["window_title"]} — {variant_title}')
        # 初始尺寸自适应屏幕(取配置值与屏幕可用区域80%的较小者)，窗口可自由拖拽缩放
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(UI_CONFIG["window_size"][0], int(screen.width() * 0.8))
        h = min(UI_CONFIG["window_size"][1], int(screen.height() * 0.8))
        self.resize(w, h)
        
        # 创建菜单栏
        self._create_menu_bar()
        
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 心跳呼吸灯（左下角）：脉冲只由真实心跳发送事件驱动，不做装饰性空闪
        self.heartbeat_light = HeartbeatLight()
        self.heartbeat_light.set_connected(False)
        self.heartbeat_pulse_signal.connect(self.heartbeat_light.trigger_pulse)
        self.status_bar.insertPermanentWidget(0, self.heartbeat_light)
        
        # 添加连接时间标签到状态栏右侧
        self.connection_time_label = QLabel("未连接")
        self.connection_time_label.setStyleSheet("color: gray; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.connection_time_label)

        # 控制板遥测标签（CPU/温度/内存，2Hz state 回推 + 1Hz 刷新显示）
        self.telemetry_label = QLabel("控制板: --")
        self.telemetry_label.setStyleSheet("color: #2a6496; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.telemetry_label)
        self._last_telemetry = None
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.setInterval(1000)
        self.telemetry_timer.timeout.connect(self._refresh_telemetry_label)

        self.status_bar.showMessage("系统启动完成")
        
        # 创建中央组件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        
        # 创建分割器
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)
        
        # 左侧控制面板
        control_panel = self._create_control_panel()
        self.main_splitter.addWidget(control_panel)
        
        # 中央区域 - 包含数据可视化和视频显示
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建中央标签页
        center_tabs = QTabWidget()
        
        # 数据可视化标签页
        self.visualization_widget = DataVisualizationWidget()
        center_tabs.addTab(self.visualization_widget, "数据可视化")
        
        # 视频页按变体: dual=双目测距组件, single=原视频监控（外部+机载相机）
        if self.variant == "dual":
            self.video_widget = StereoFishCameraWidget()
            center_tabs.addTab(self.video_widget, "双目测距")
            mock_video_path = os.environ.get("GROUNDSTATION_MOCK_VIDEO", "")
            self.enhancement_widget = ImageEnhancementWidget(
                mock_video_path=mock_video_path or None)
            center_tabs.addTab(self.enhancement_widget, "图像增强对比")
            # 复用现有 9998 视频连接，禁止为了增强页面再建立第二条视频流。
            self.video_widget.stream_client.frame_received.connect(
                self.enhancement_widget.push_live_frame, Qt.QueuedConnection)
            self.video_widget.stream_client.connection_status.connect(
                self.enhancement_widget.set_live_connection_status,
                Qt.QueuedConnection)
            if mock_video_path:
                center_tabs.setCurrentWidget(self.enhancement_widget)
        else:
            self.video_widget = VideoMonitorWidget()
            center_tabs.addTab(self.video_widget, "视频监控")
        
        center_layout.addWidget(center_tabs)
        self.main_splitter.addWidget(center_widget)
        
        # 右侧面板 - 包含按键状态和数据记录控制
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(2, 2, 2, 2)
        right_panel.setMinimumWidth(170)   # 可拖窄到此为止，内容自适应
        control_panel.setMinimumWidth(170)
        
        # 创建右侧标签页
        right_tabs = QTabWidget()

        # 深度标签页（双尾鱼变体专属）
        if self.variant == "dual":
            self.depth_panel = DepthPanel(DUAL_FISH_CONFIG["fish_ip"])
            right_tabs.addTab(self.depth_panel, "深度")

        # 按键状态标签页
        self.keyboard_status_widget = KeyboardStatusWidget()
        right_tabs.addTab(self.keyboard_status_widget, "按键状态")
        
        # 数据记录控制标签页
        self.data_recording_widget = DataRecordingWidget()
        right_tabs.addTab(self.data_recording_widget, "数据记录")
        
        right_layout.addWidget(right_tabs)
        # 拖窄时内容自适应面板宽度，而不是被 sizeHint 顶住
        right_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.main_splitter.addWidget(right_panel)

        # 设置分割器比例 (控制面板:中央区域:右侧栏 = 2:8:2)
        self.main_splitter.setSizes([360, 760, 280])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        QTimer.singleShot(0, self._restore_splitter_sizes)
        
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
        
        self.video_actions = {}
        # 视频菜单
        video_menu = menubar.addMenu('视频(&V)')

        if self.variant == "dual":
            start_video_action = QAction('连接视频流(&S)', self)
            start_video_action.triggered.connect(
                lambda: self.video_widget.connect_stream())
            video_menu.addAction(start_video_action)
            self.video_actions["connect"] = start_video_action

            stop_video_action = QAction('断开视频流(&T)', self)
            stop_video_action.triggered.connect(
                lambda: self.video_widget._disconnect())
            video_menu.addAction(stop_video_action)
            self.video_actions["disconnect"] = stop_video_action

            camera_action = QAction('开启摄像头', self)
            camera_action.triggered.connect(
                lambda: self.video_widget._toggle_camera())
            video_menu.addAction(camera_action)
            self.video_actions["camera_toggle"] = camera_action
        else:
            start_video_action = QAction('启动摄像头(&S)', self)
            start_video_action.triggered.connect(self._start_legacy_camera)
            video_menu.addAction(start_video_action)

            stop_video_action = QAction('停止摄像头(&T)', self)
            stop_video_action.triggered.connect(self._stop_legacy_camera)
            video_menu.addAction(stop_video_action)
        
        video_menu.addSeparator()
        
        # 视频记录
        start_video_record_action = QAction('开始录制(&R)', self)
        start_video_record_action.triggered.connect(self._start_video_recording)
        video_menu.addAction(start_video_record_action)
        self.video_actions["record_start"] = start_video_record_action
        
        stop_video_record_action = QAction('停止录制(&E)', self)
        stop_video_record_action.triggered.connect(self._stop_video_recording)
        video_menu.addAction(stop_video_record_action)
        self.video_actions["record_stop"] = stop_video_record_action
        
        video_menu.addSeparator()
        
        snapshot_action = QAction('保存快照(&P)', self)
        snapshot_action.triggered.connect(self._save_video_snapshot)
        video_menu.addAction(snapshot_action)
        self.video_actions["snapshot"] = snapshot_action
        
        # 控制菜单
        control_menu = menubar.addMenu('控制(&O)')
        
        self.controller_action_group = QActionGroup(self)
        self.controller_action_group.setExclusive(True)
        self.controller_actions = {}
        keyboard_action = QAction('键盘控制(&K)', self, checkable=True)
        keyboard_action.triggered.connect(
            lambda checked: checked and self._request_controller("keyboard"))
        self.controller_action_group.addAction(keyboard_action)
        self.controller_actions["keyboard"] = keyboard_action
        control_menu.addAction(keyboard_action)
        if self.variant == "dual":
            depth_action = QAction('深度控制', self, checkable=True)
            depth_action.triggered.connect(
                lambda checked: checked and self._request_controller("depth"))
            self.controller_action_group.addAction(depth_action)
            self.controller_actions["depth"] = depth_action
            control_menu.addAction(depth_action)
        
        # 数据菜单
        data_menu = menubar.addMenu('数据(&D)')
        
        # 记录控制子菜单
        record_submenu = data_menu.addMenu('记录控制(&R)')
        
        start_record_action = QAction('开始记录(&S)', self)
        start_record_action.triggered.connect(lambda: self.data_recording_widget._start_recording())
        record_submenu.addAction(start_record_action)
        
        pause_record_action = QAction('暂停记录(&P)', self)
        pause_record_action.triggered.connect(lambda: self.data_recording_widget._pause_recording())
        record_submenu.addAction(pause_record_action)
        
        stop_record_action = QAction('停止记录(&T)', self)
        stop_record_action.triggered.connect(lambda: self.data_recording_widget._stop_recording())
        record_submenu.addAction(stop_record_action)
        
        data_menu.addSeparator()
        
        # 数据导出子菜单
        export_submenu = data_menu.addMenu('数据导出(&E)')
        
        save_csv_action = QAction('导出CSV(&C)', self)
        save_csv_action.triggered.connect(lambda: self.data_recording_widget._save_csv())
        export_submenu.addAction(save_csv_action)
        
        save_excel_action = QAction('导出Excel(&X)', self)
        save_excel_action.triggered.connect(lambda: self.data_recording_widget._save_excel())
        export_submenu.addAction(save_excel_action)
        
        data_menu.addSeparator()
        
        # 图形导出
        export_graphics_action = QAction('导出图形(&G)', self)
        export_graphics_action.triggered.connect(self._on_export_graphics_requested)
        data_menu.addAction(export_graphics_action)
        
        clear_data_action = QAction('清空数据(&L)', self)
        clear_data_action.triggered.connect(lambda: self.data_recording_widget._clear_data())
        data_menu.addAction(clear_data_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu('帮助(&H)')
        
        about_action = QAction('关于(&A)', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        
        # 连接状态组
        connection_group = QGroupBox("连接状态")
        connection_layout = QGridLayout(connection_group)
        
        # IP地址输入
        self.ip_input = QLineEdit()
        # 双尾鱼默认填 pico IP，单尾鱼默认填 orangepi IP
        self.ip_input.setText(
            DUAL_FISH_CONFIG["fish_ip"] if self.variant == "dual" else FISH_IP)
        self.ip_input.setPlaceholderText("输入机器鱼IP地址")
        
        # 端口输入
        self.port_input = QLineEdit()
        self.port_input.setText(str(
            DUAL_FISH_CONFIG["socket_port"] if self.variant == "dual" else SOCKET_PORT))
        self.port_input.setPlaceholderText("端口")
        self.port_input.setMaximumWidth(60)
        
        self.connection_status_label = QLabel("未连接")
        self.connection_button = QPushButton("连接")
        self.connection_button.clicked.connect(self._toggle_connection)

        # 双尾鱼：连接档案（备注+IP 本地持久化，下拉直选）
        self.saved_combo = None
        self.remark_input = None
        if self.variant == "dual":
            saved_layout = QHBoxLayout()
            saved_layout.addWidget(QLabel("档案:"))
            self.saved_combo = QComboBox()
            self.saved_combo.currentIndexChanged.connect(self._on_saved_selected)
            saved_layout.addWidget(self.saved_combo, 1)
            connection_layout.addWidget(QLabel("已存:"), 0, 0)
            connection_layout.addLayout(saved_layout, 0, 1)

            remark_row = QHBoxLayout()
            remark_row.addWidget(QLabel("备注:"))
            self.remark_input = QLineEdit()
            self.remark_input.setPlaceholderText("如: 实验室有线")
            remark_row.addWidget(self.remark_input, 1)
            self.save_conn_button = QPushButton("保存")
            self.save_conn_button.setToolTip("以当前备注+IP+端口保存到本地连接档案")
            self.save_conn_button.clicked.connect(self._save_current_connection)
            remark_row.addWidget(self.save_conn_button)
            self.del_conn_button = QPushButton("删除")
            self.del_conn_button.setToolTip("删除下拉中当前选中的连接档案")
            self.del_conn_button.clicked.connect(self._delete_saved_connection)
            remark_row.addWidget(self.del_conn_button)
            connection_layout.addLayout(remark_row, 1, 0, 1, 2)
            self._refresh_saved_combo()
        
        # 布局：IP和端口在同一行
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(self.ip_input)
        ip_layout.addWidget(QLabel(":"))
        ip_layout.addWidget(self.port_input)
        
        connection_layout.addWidget(QLabel("地址:"), 2, 0)
        connection_layout.addLayout(ip_layout, 2, 1)
        connection_layout.addWidget(QLabel("状态:"), 3, 0)
        connection_layout.addWidget(self.connection_status_label, 3, 1)
        connection_layout.addWidget(self.connection_button, 4, 0, 1, 2)
        
        layout.addWidget(connection_group)
        
        # 控制方式选择组
        control_group = QGroupBox("控制方式")
        control_layout = QVBoxLayout(control_group)
        
        self.controller_combo = QComboBox()
        self.controller_combo.addItem("键盘控制", "keyboard")
        if self.variant == "dual":
            self.controller_combo.addItem("深度控制", "depth")
        self.controller_combo.currentIndexChanged.connect(self._on_controller_changed)
        
        control_layout.addWidget(QLabel("选择控制方式:"))
        control_layout.addWidget(self.controller_combo)

        # 安全开关：勾选后控制命令才会真正发送，取消勾选会立即发送停止命令
        self.enable_control_checkbox = QCheckBox("启用控制 (默认关闭)")
        self.enable_control_checkbox.setToolTip(
            "勾选后才能控制机器鱼；\n取消勾选将立即发送停止命令")
        self.enable_control_checkbox.toggled.connect(self._on_enable_control_toggled)
        control_layout.addWidget(self.enable_control_checkbox)
        
        # 控制器专用界面容器
        self.controller_widget_container = QWidget()
        self.controller_widget_layout = QVBoxLayout(self.controller_widget_container)
        self.controller_widget_container.setMinimumWidth(240)

        controller_scroll = QScrollArea()
        controller_scroll.setWidgetResizable(True)
        controller_scroll.setWidget(self.controller_widget_container)
        controller_scroll.setMinimumHeight(320)
        controller_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        controller_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        control_layout.addWidget(controller_scroll)
        
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
        if self.variant == "dual":
            self.controllers['depth'] = DepthController()
        
        # 默认选择键盘控制器
        self._switch_controller('keyboard')
        
    def _init_connections(self):
        """初始化信号连接"""
        # 控制器信号连接
        for controller in self.controllers.values():
            controller.control_command_generated.connect(self._on_control_command)
            controller.status_changed.connect(self._on_controller_status_changed)
        
        # 键盘状态组件信号连接  
        self.keyboard_status_widget.plot_cleared.connect(self._on_plot_cleared)
        
        # 数据记录组件信号连接
        self.data_recording_widget.export_graphics_requested.connect(self._on_export_graphics_requested)
        
        # 连接状态变化信号（线程安全）
        self.connection_changed_signal.connect(self._handle_connection_changed, Qt.QueuedConnection)
        if self.variant == "dual":
            self.video_widget.state_changed.connect(self._sync_video_actions)
            self.video_widget.set_fish_connection_available(False)
            self.depth_panel.set_parent_connection_available(False)
        self._sync_video_actions()
    
    def _switch_controller(self, controller_name: str):
        """在未启用控制时切换控制器；重复选择保持幂等。"""
        if controller_name not in self.controllers:
            self._log_message(f"未知控制器: {controller_name}")
            self._sync_controller_selection()
            return False
        if self._control_armed:
            self._log_message("控制已启用，请先关闭控制再切换控制方式")
            self._sync_controller_selection()
            return False
        if controller_name == self._current_controller_name:
            self._sync_controller_selection()
            return True

        # 停用当前控制器
        if self.current_controller and self.current_controller.active:
            self.current_controller.deactivate()
            
        # 切换到新控制器
        self.current_controller = self.controllers[controller_name]
        self._current_controller_name = controller_name
        
        # 更新控制器界面
        self._update_controller_widget()
        
        self._sync_controller_selection()
        self._log_message(f"已切换到{controller_name}控制器")
        return True
    
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
        self._request_controller(controller_name)

    def _request_controller(self, controller_name):
        """统一处理下拉框与菜单发起的控制器选择。"""
        return self._switch_controller(controller_name)

    def _sync_controller_selection(self):
        """使下拉框、菜单和真实控制器永远指向同一项。"""
        if not self._current_controller_name:
            return
        index = self.controller_combo.findData(self._current_controller_name)
        if index >= 0 and self.controller_combo.currentIndex() != index:
            self.controller_combo.blockSignals(True)
            self.controller_combo.setCurrentIndex(index)
            self.controller_combo.blockSignals(False)
        for name, action in self.controller_actions.items():
            action.blockSignals(True)
            action.setChecked(name == self._current_controller_name)
            action.blockSignals(False)
    
    def _refresh_saved_combo(self):
        """用连接档案刷新下拉框（首项为占位提示）。"""
        if self.saved_combo is None:
            return
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("选择已存连接…", None)
        for e in self.connection_store.entries:
            self.saved_combo.addItem(
                f"{e.get('remark') or '未命名'}  [{e['ip']}:{e['port']}]", e)
        self.saved_combo.blockSignals(False)
        # 自动选中最近一条（IP/端口直接预填）
        if self.connection_store.entries:
            self.saved_combo.setCurrentIndex(1)
            self._on_saved_selected(1)

    def _on_saved_selected(self, index):
        """下拉选择已存连接：填充 IP/端口输入框。"""
        if self.saved_combo is None:
            return
        entry = self.saved_combo.itemData(index)
        if not entry:
            return
        self.ip_input.setText(entry["ip"])
        self.port_input.setText(str(entry["port"]))

    def _save_current_connection(self):
        """把当前 IP/端口 连同备注写入本地连接档案。"""
        ip = self.ip_input.text().strip()
        port = self.port_input.text().strip()
        if not ip:
            QMessageBox.warning(self, "保存失败", "IP 为空，无法保存")
            return
        remark = self.remark_input.text().strip() if self.remark_input else ""
        self.connection_store.add(remark, ip, int(port))
        self._refresh_saved_combo()
        self._log_message(f"已保存连接档案: {remark or '未命名'} {ip}:{port}")

    def _delete_saved_connection(self):
        """删除下拉中当前选中的连接档案。"""
        if self.saved_combo is None:
            return
        index = self.saved_combo.currentIndex()
        entry = self.saved_combo.itemData(index)
        if not entry:
            QMessageBox.information(self, "提示", "请先在下拉框选择要删除的连接")
            return
        self.connection_store.remove(index - 1)
        self._refresh_saved_combo()
        self._log_message("已删除连接档案")

    def _restore_splitter_sizes(self):
        """恢复当前鱼体变体的侧栏宽度，无记录时使用宽松默认值。"""
        total = max(self.main_splitter.width(), self.width() - 30, 900)
        default_left, default_right = 360, 280
        raw = self._settings.value(f"layout/main_splitter/{self.variant}")
        saved = []
        if isinstance(raw, (list, tuple)):
            saved = raw
        elif isinstance(raw, str):
            saved = raw.split(",")
        try:
            left = int(saved[0]) if len(saved) == 3 else default_left
            right = int(saved[2]) if len(saved) == 3 else default_right
        except (TypeError, ValueError):
            left, right = default_left, default_right
        left = max(320, min(left, max(320, total - 640)))
        right = max(220, min(right, max(220, total - left - 420)))
        center = max(420, total - left - right)
        self.main_splitter.setSizes([left, center, right])

    def _save_splitter_sizes(self):
        """分变体保存主分割器宽度。"""
        sizes = self.main_splitter.sizes()
        if len(sizes) == 3:
            self._settings.setValue(
                f"layout/main_splitter/{self.variant}",
                ",".join(str(int(value)) for value in sizes))

    def _sync_video_actions(self):
        """使视频菜单与双目页面的真实状态保持一致。"""
        if not getattr(self, "video_actions", None):
            return
        if self.variant != "dual" or not hasattr(self, "video_widget"):
            return
        states = self.video_widget.get_action_states()
        for name, action in self.video_actions.items():
            action.setEnabled(bool(states.get(name, False)))
        camera_action = self.video_actions.get("camera_toggle")
        if camera_action is not None:
            camera_action.setText(states.get("camera_text", "开启摄像头"))

    def _active_legacy_video_widget(self):
        """返回单尾鱼视频页当前标签的实际组件。"""
        tabs = getattr(self.video_widget, "tabs", None)
        return tabs.currentWidget() if tabs is not None else self.video_widget

    def _start_legacy_camera(self):
        """安全转发单尾鱼当前视频页的启动操作。"""
        widget = self._active_legacy_video_widget()
        if hasattr(widget, "_start_camera"):
            widget._start_camera()
        elif hasattr(widget, "_toggle_connection"):
            widget._toggle_connection()

    def _stop_legacy_camera(self):
        """安全转发单尾鱼当前视频页的停止操作。"""
        widget = self._active_legacy_video_widget()
        if hasattr(widget, "_stop_camera"):
            widget._stop_camera()
        elif hasattr(widget, "_disconnect"):
            widget._disconnect()

    def _start_video_recording(self):
        """按鱼体变体启动录制，不调用不存在的组件方法。"""
        widget = self.video_widget if self.variant == "dual" \
            else self._active_legacy_video_widget()
        if self.variant == "dual" and not widget.recording:
            widget._toggle_recording()
        elif hasattr(widget, "_start_recording"):
            widget._start_recording()
        elif hasattr(widget, "_toggle_recording"):
            widget._toggle_recording()

    def _stop_video_recording(self):
        """按鱼体变体停止录制，重复操作保持幂等。"""
        widget = self.video_widget if self.variant == "dual" \
            else self._active_legacy_video_widget()
        if self.variant == "dual":
            if widget.recording:
                widget._stop_recording()
        elif hasattr(widget, "_stop_recording"):
            widget._stop_recording()

    def _apply_main_ui_state(self):
        """根据主连接与总控制状态集中刷新主界面可操作性。"""
        state = self._fish_connection_state
        connected = state == "connected"
        idle = state == "disconnected"
        busy = state in ("connecting", "disconnecting")

        self.connection_button.setEnabled(not busy)
        self.connection_button.setText(
            "断开" if connected else
            "连接中..." if state == "connecting" else
            "断开中..." if state == "disconnecting" else "连接")
        self.connect_action.setEnabled(not busy)
        self.connect_action.setText(
            "断开连接(&D)" if connected else "连接机器鱼(&C)")
        for widget in (self.ip_input, self.port_input):
            widget.setEnabled(idle)
        for widget in (self.saved_combo, self.remark_input,
                       getattr(self, "save_conn_button", None),
                       getattr(self, "del_conn_button", None)):
            if widget is not None:
                widget.setEnabled(idle)

        self.enable_control_checkbox.setEnabled(connected)
        self.controller_combo.setEnabled(not self._control_armed)
        for action in self.controller_actions.values():
            action.setEnabled(not self._control_armed)
        self._sync_controller_selection()
        self._sync_video_actions()

    def _set_control_checkbox(self, checked):
        """不触发回调地同步总控制复选框。"""
        self.enable_control_checkbox.blockSignals(True)
        self.enable_control_checkbox.setChecked(bool(checked))
        self.enable_control_checkbox.blockSignals(False)

    def _set_control_armed(self, armed, send_stop=True):
        """幂等地启用/停用当前控制器，停用前优先发安全停止帧。"""
        armed = bool(armed)
        if armed == self._control_armed:
            self._set_control_checkbox(armed)
            self._apply_main_ui_state()
            return True
        if armed and self._fish_connection_state != "connected":
            self._set_control_checkbox(False)
            self._log_message("未连接机器鱼，不能启用控制")
            self._apply_main_ui_state()
            return False
        if armed:
            self._control_armed = True
            self.current_controller.activate()
            if isinstance(self.current_controller, KeyboardController):
                self.current_controller.stop_motion()
            self._set_control_checkbox(True)
        else:
            if send_stop:
                self._send_stop_command()
            # 先撤销主窗口发送权，再让控制器清理内部状态。
            # 深度控制器关 PID 时会产生回中命令，此顺序可防止
            # 回中命令携带旧的尾鳍运动状态再次发出。
            self._control_armed = False
            if self.current_controller and self.current_controller.active:
                self.current_controller.deactivate()
            self._set_control_checkbox(False)
        self._apply_main_ui_state()
        return True

    def _toggle_connection(self):
        """切换连接状态"""
        if self._fish_connection_state == "disconnected":
            self._connect_to_fish()
        elif self._fish_connection_state == "connected":
            self._disconnect_from_fish()
    
    def _connect_to_fish(self):
        """连接到机器鱼"""
        if self._fish_connection_state != "disconnected":
            return
        try:
            # 获取用户输入的IP地址和端口
            ip_address = self.ip_input.text().strip()
            if not ip_address:
                QMessageBox.warning(self, "输入错误", "请输入有效的IP地址")
                return
            
            try:
                port = int(self.port_input.text().strip())
            except ValueError:
                QMessageBox.warning(self, "输入错误", "请输入有效的端口号")
                return
            
            self._fish_connection_state = "connecting"
            self._apply_main_ui_state()
            self.status_bar.showMessage("正在连接机器鱼...")

            communication = SocketCommunication(
                ip_address=ip_address, port=port)
            self.communication = communication

            # 设置数据回调，实时更新UI
            communication.set_data_callback(self._on_sensor_data_received)
            communication.set_connection_callback(
                lambda connected, source=communication:
                self._on_connection_changed(source, connected))
            communication.set_state_callback(self._on_board_state)
            # 心跳呼吸灯：心跳线程真实发出一拍 → 信号排队回 UI 线程点亮
            communication.set_heartbeat_callback(
                self.heartbeat_pulse_signal.emit)
            if communication.connect():
                self._finish_fish_connection(ip_address, port)
            else:
                communication.set_connection_callback(None)
                communication.disconnect()
                if self.communication is communication:
                    self.communication = None
                self._fish_connection_state = "disconnected"
                self.connection_status_label.setText("连接失败")
                self.status_bar.showMessage("机器鱼连接失败")
                self._log_message(f"机器鱼连接失败 ({ip_address}:{port})")
                self._apply_main_ui_state()
        except Exception as e:
            self._fish_connection_state = "disconnected"
            self.communication = None
            self._apply_main_ui_state()
            self._log_message(f"连接异常: {e}")
            QMessageBox.critical(self, "连接错误", f"连接失败: {e}")

    def _finish_fish_connection(self, ip_address, port):
        """幂等地完成主连接，再放行从属视频和深度连接。"""
        if self._fish_connection_state == "connected":
            return
        self._fish_connection_state = "connected"
        self.connection_status_label.setText("已连接")
        self.status_bar.showMessage(f"机器鱼连接成功 ({ip_address}:{port})")
        if self.variant == "dual":
            self.video_widget.set_fish_connection_available(True)
            self.video_widget.connect_stream()
            self.depth_panel.set_parent_connection_available(
                True, host=ip_address, auto_connect=True)
        self.data_timer.start(50)
        self.telemetry_timer.start()
        self.connection_start_time = time.time()
        self._apply_main_ui_state()
        self._log_message(f"机器鱼连接成功 (Socket: {ip_address}:{port})")
        self.setFocus()
    
    def _disconnect_from_fish(self):
        """断开机器鱼连接"""
        if self._fish_connection_state not in ("connecting", "connected"):
            return
        try:
            was_armed = self._control_armed
            self._set_control_armed(False, send_stop=True)
            if not was_armed:
                # 即使当前未启用控制，主动断链前仍发送一次安全停止帧。
                self._send_stop_command()
            self._fish_connection_state = "disconnecting"
            self._apply_main_ui_state()
            # 停止数据定时器
            self.data_timer.stop()
            self.telemetry_timer.stop()
            self.telemetry_label.setText("控制板: --")
            
            # 双尾鱼：同步断开视频流与深度面板
            if self.variant == "dual":
                self.video_widget.set_fish_connection_available(False)
                self.depth_panel.set_parent_connection_available(False)

            communication = self.communication
            if communication:
                communication.disconnect()
            if self.communication is communication:
                self.communication = None
            self._fish_connection_state = "disconnected"
            # 清除连接时间
            self.connection_start_time = None
                
            self.connection_status_label.setText("未连接")
            self.status_bar.showMessage("已断开连接")
            self._apply_main_ui_state()
            self._log_message("已断开机器鱼连接")
            
        except Exception as e:
            self._log_message(f"断开连接异常: {e}")
    
    def _update_connection_time(self):
        """更新连接时间显示"""
        if self.connection_start_time is not None:
            elapsed_time = time.time() - self.connection_start_time
            hours = int(elapsed_time // 3600)
            minutes = int((elapsed_time % 3600) // 60)
            seconds = int(elapsed_time % 60)
            
            if hours > 0:
                time_str = f"已连接: {hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                time_str = f"已连接: {minutes:02d}:{seconds:02d}"
            
            self.connection_time_label.setText(time_str)
            self.connection_time_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.connection_time_label.setText("未连接")
            self.connection_time_label.setStyleSheet("color: gray; font-weight: bold;")
    
    def _update_data(self):
        """更新数据"""
        if self.communication and self.communication.connected:
            try:
                fish_state = self.communication.get_fish_state()
                if fish_state:
                    # 双目鱼：深度五路按零点补出标定后值（零点来自深度面板的
                    # depth_zero.json，未标定时零点为 0，标定后曲线=fused）
                    if fish_state.depth and fish_state.depth.get("fused") is not None:
                        zero = self.depth_panel.zero_offset \
                            if hasattr(self, "depth_panel") else 0.0
                        fish_state.depth["calibrated"] = \
                            fish_state.depth["fused"] - zero
                        depth_controller = self.controllers.get("depth")
                        if depth_controller is not None:
                            depth_controller.update_depth(
                                fish_state.depth["calibrated"],
                                fish_state.timestamp)
                    self.visualization_widget.update_data(fish_state)
                    # 分传感器 CSV（IMU/深度）：记录进行中时随帧追加
                    self.data_recording_widget.add_sensor_points(fish_state)
                    
                    # 添加到数据记录器（如果有控制命令的话，使用最后的控制命令）
                    last_command = getattr(self, '_last_control_command', None)
                    self.data_recording_widget.add_data_point(fish_state, last_command)
                    
            except Exception as e:
                # 降低错误日志频率避免刷屏
                import time
                import traceback
                if not hasattr(self, '_last_error_time') or time.time() - self._last_error_time > 5:
                    self._last_error_time = time.time()
                    self._log_message(f"数据更新异常: {e}")
                    traceback.print_exc()
    
    def _on_sensor_data_received(self, fish_state: FishState):
        """传感器数据接收回调（由Socket线程调用）"""
        # 注意：此方法在工作线程中调用，直接更新会有线程安全问题
        # 数据通过get_fish_state()获取，定时器_update_data会读取并更新UI
        pass

    def _on_board_state(self, state: dict):
        """控制板状态回推（由Socket线程调用，仅存数据不改UI）"""
        self._last_telemetry = state.get("telemetry")

    def _refresh_telemetry_label(self):
        """刷新底栏控制板遥测显示（1Hz，GUI 线程内执行）。"""
        t = self._last_telemetry
        if not t:
            self.telemetry_label.setText("控制板: --")
            return
        cpu, temp = t.get("cpu_percent"), t.get("soc_temp_c")
        used, total = t.get("mem_used_mb"), t.get("mem_total_mb")
        freq = t.get("cpu_freq_mhz")
        cpu_txt = f"{cpu:.0f}%" if cpu is not None else "--"
        temp_txt = f"{temp:.1f}°C" if temp is not None else "--"
        mem_txt = f"{used}/{total}MB" if used is not None and total else "--"
        freq_txt = f"{freq}MHz" if freq else "--"
        self.telemetry_label.setText(
            f"控制板  CPU {cpu_txt} | {temp_txt} | 内存 {mem_txt} | 大核 {freq_txt}")
    
    def _on_connection_changed(self, source, connected: bool):
        """连接状态变化回调（在socket工作线程中调用）"""
        # 只发射信号，不直接操作UI
        self.connection_changed_signal.emit(source, connected)
    
    @pyqtSlot(object, bool)
    def _handle_connection_changed(self, source, connected: bool):
        """处理连接状态变化（在主线程中执行）"""
        try:
            if source is not self.communication:
                return
            self.heartbeat_light.set_connected(connected)  # 呼吸灯随连接状态亮/灰
            if connected:
                self._finish_fish_connection(source.fish_ip, source.port)
            else:
                # 连接断开，重置UI状态
                self.communication = None
                self._set_control_armed(False, send_stop=False)
                self._fish_connection_state = "disconnected"
                self.data_timer.stop()
                self.telemetry_timer.stop()
                self.connection_start_time = None
                if self.variant == "dual":
                    self.video_widget.set_fish_connection_available(False)
                    self.depth_panel.set_parent_connection_available(False)
                self.connection_status_label.setText("连接断开")
                self.status_bar.showMessage("连接已断开")
                self._apply_main_ui_state()
                self._log_message("机器鱼连接已断开")
        except Exception as e:
            print(f"处理连接状态变化异常: {e}")
    
    def _send_stop_command(self):
        """发送停止命令，确保机器鱼停止运动"""
        if self.communication and self.communication.connected:
            stop_offset = 0.0
            if isinstance(self.current_controller, KeyboardController):
                stop_offset = self.current_controller.get_base_bias()
            stop_cmd = ControlCommand()
            stop_cmd.tail_frequency = 0.0
            stop_cmd.tail_amplitude = 0.0
            stop_cmd.tail_offset = stop_offset
            stop_cmd.pec_angle = 1500
            stop_cmd.timestamp = time.time()
            self.communication.send_control_command(stop_cmd)
            self._log_message("已发送停止命令")

    def _on_enable_control_toggled(self, checked: bool):
        """启用控制开关切换"""
        if not self._set_control_armed(checked, send_stop=True):
            return
        if self._control_armed:
            self._log_message(
                f"控制已启用，{self._current_controller_name}控制器生效")
            self.status_bar.showMessage("控制已启用")
        else:
            self._log_message("控制已禁用")
            self.status_bar.showMessage("控制已禁用")

    def _on_control_command(self, command: ControlCommand):
        """处理控制命令"""
        # 安全开关：未勾选"启用控制"时不发送任何控制命令
        if not self._control_armed:
            return
        if (self._fish_connection_state == "connected" and
                self.communication and self.communication.connected):
            try:
                # 添加胸鳍角度到命令
                if hasattr(self.current_controller, '_pec_angle'):
                    command.pec_angle = self.current_controller._pec_angle
                else:
                    command.pec_angle = 1500  # 默认值
                
                success = self.communication.send_control_command(command)
                if success:
                    # 记录最后的控制命令，用于数据记录
                    self._last_control_command = command
                else:
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
    
    def _on_export_graphics_requested(self):
        """处理图形导出请求"""
        try:
            self.data_recording_widget.export_graphics(self.visualization_widget)
            self._log_message("图形导出完成")
        except Exception as e:
            self._log_message(f"图形导出失败: {e}")
            QMessageBox.critical(self, "导出错误", f"图形导出失败: {e}")
    
    def _save_video_snapshot(self):
        """保存视频快照"""
        try:
            widget = self.video_widget if self.variant == "dual" \
                else self._active_legacy_video_widget()
            filename = widget.save_snapshot() \
                if hasattr(widget, "save_snapshot") else None
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
    
    def _normalize_key(self, event) -> str:
        """按键事件转控制键名
        方向键保留大小写: 小写w/a/d=慢速, 大写W/A/D(Shift或大写锁)=快速;
        其余键统一转大写; 无文本键(Space/方向键)用键值映射
        """
        raw = event.text()
        if not raw:
            key_map = {
                Qt.Key_Space: "Space",
                Qt.Key_Up: "Up",
                Qt.Key_Down: "Down",
                Qt.Key_Left: "Left",
                Qt.Key_Right: "Right"
            }
            return key_map.get(event.key(), "")
        upper = raw.upper()
        if upper in ("W", "A", "D"):
            return raw if raw.islower() else upper
        return upper

    def keyPressEvent(self, event):
        """键盘按下事件"""
        if (self._control_armed and
                isinstance(self.current_controller, KeyboardController)):
            key_text = self._normalize_key(event)

            if key_text:
                # 更新控制器
                self.current_controller.handle_key_press(key_text)
                # 更新按键状态显示(状态面板统一用大写键名)
                self.keyboard_status_widget.update_key_state(key_text.upper(), True)
                # 处理特殊功能键
                self.keyboard_status_widget.handle_special_keys(key_text.upper(), True)

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """键盘释放事件"""
        if (self._control_armed and
                isinstance(self.current_controller, KeyboardController)):
            key_text = self._normalize_key(event)

            if key_text:
                # 更新控制器
                self.current_controller.handle_key_release(key_text)
                # 更新按键状态显示
                self.keyboard_status_widget.update_key_state(key_text.upper(), False)

        super().keyReleaseEvent(event)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self._save_splitter_sizes()
        self._set_control_armed(False, send_stop=True)
        # 停用控制器
        if self.current_controller and self.current_controller.active:
            self.current_controller.deactivate()

        # 停止图像增强页的 Mock 与后台增强线程
        if hasattr(self, 'enhancement_widget'):
            self.enhancement_widget.shutdown()

        # 断开连接
        if self._fish_connection_state in ("connecting", "connected"):
            self._disconnect_from_fish()
        
        # VideoMonitorWidget没有_stop_camera方法，不需要调用
            
        event.accept()
