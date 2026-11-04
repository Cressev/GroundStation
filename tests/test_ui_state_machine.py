#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主连接、控制器、双目视频和侧栏的离线状态机测试。"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

from ui.image_enhancement_widget import EnhancementWorker
from ui.main_window import MainWindow
from ui.stereo_camera_widget import (StereoFishCameraWidget, StereoVideoClient,
                                     prepare_stereo_display_frame)
from controllers.xbox import XboxInputState


_APP = None


class FakeCommunication:
    """记录停止/控制命令的无网络通信替身。"""

    def __init__(self):
        """初始化为已连接状态。"""
        self.connected = True
        self.commands = []
        self.depth_requests = []

    def send_depth_control(self, request):
        """Record settings/intent only, without simulating local PID computation."""
        self.depth_requests.append(request)
        return True

    def send_control_command(self, command):
        """记录命令并报告发送成功。"""
        self.commands.append(command)
        return True

    def disconnect(self):
        """幂等地切换为断开状态。"""
        self.connected = False
        return True


def ensure_app():
    """创建并持有唯一 QApplication。"""
    global _APP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _APP = app
    return app


def make_connected_window():
    """创建不触发真实网络的已连接双尾鱼主窗口。"""
    ensure_app()
    window = MainWindow("dual")
    communication = FakeCommunication()
    window.communication = communication
    window._fish_connection_state = "connected"
    window._apply_main_ui_state()
    return window, communication


def test_control_arm_locks_controller_and_repeated_transitions_are_idempotent():
    """启用控制后锁定控制器，重复启停不得产生额外迁移。"""
    window, communication = make_connected_window()
    assert not window.current_controller.active
    assert window.controller_combo.isEnabled()

    window.enable_control_checkbox.setChecked(True)
    assert window._control_armed
    assert window.current_controller.active
    assert not window.controller_combo.isEnabled()
    command_count = len(communication.commands)

    assert window._set_control_armed(True)
    assert len(communication.commands) == command_count
    assert not window._request_controller("xbox")
    assert window._current_controller_name == "keyboard"

    window.enable_control_checkbox.setChecked(False)
    assert not window._control_armed
    assert not window.current_controller.active
    assert window.controller_combo.isEnabled()
    assert len(communication.commands) == command_count + 1
    window._fish_connection_state = "disconnected"
    window.communication = None
    window.close()


def test_controller_selection_stays_synchronized_and_depth_pid_is_independent():
    """Heading selection and depth startup are independent and have separate UI locks."""
    window, _ = make_connected_window()
    assert window._request_controller("xbox")
    assert window._request_controller("xbox")
    assert window._current_controller_name == "xbox"
    assert window.controller_combo.currentData() == "xbox"
    assert window.controller_actions["xbox"].isChecked()
    depth = window.controllers["depth"]
    depth.get_control_widget()
    assert depth._pid_enable_checkbox.isHidden()
    window.depth_enable_checkbox.setChecked(True)
    assert depth._pid_enabled and depth.active
    assert not window._control_armed
    assert window.controller_combo.isEnabled()
    assert not window.depth_controller_combo.isEnabled()
    window.depth_enable_checkbox.setChecked(False)
    assert not depth._pid_enabled
    window._fish_connection_state = "disconnected"
    window.communication = None
    window.close()


def test_xbox_mode_is_integrated_and_unconnected_gamepad_cannot_arm_control():
    """Xbox 必须同时出现在菜单/下拉框中，且无手柄时不能误进入已启用状态。"""
    window, communication = make_connected_window()
    assert window.controller_combo.findData("xbox") >= 0
    assert "xbox" in window.controller_actions
    assert "xbox" in window.controllers
    assert window._request_controller("xbox")
    assert window._current_controller_name == "xbox"
    assert window.controller_actions["xbox"].isChecked()

    xbox = window.controllers["xbox"]
    xbox._poll_timer.stop()
    xbox._backend = Mock(available=True)
    xbox._backend.poll.return_value = XboxInputState()
    panel = xbox.get_control_widget()
    assert panel is not None
    assert "normal_frequency" in xbox._parameter_inputs
    assert "pec_fast_rate" in xbox._parameter_inputs

    assert not window._set_control_armed(True)
    assert not window._control_armed
    assert not window.enable_control_checkbox.isChecked()
    assert window.controller_combo.isEnabled()
    assert communication.commands == []

    window._fish_connection_state = "disconnected"
    window.communication = None
    window.close()


def test_disconnect_disarms_control_and_locks_child_connections():
    """主连接断开必须原子地撤销控制并锁定视频/深度子连接。"""
    window, communication = make_connected_window()
    window.video_widget.set_fish_connection_available(True)
    window.depth_panel.set_parent_connection_available(True)
    window.enable_control_checkbox.setChecked(True)

    window._disconnect_from_fish()
    assert window._fish_connection_state == "disconnected"
    assert not window._control_armed
    assert not window.enable_control_checkbox.isChecked()
    assert not window.enable_control_checkbox.isEnabled()
    assert window.video_widget._stream_state == "locked"
    assert window.depth_panel._connection_state == "locked"
    assert not communication.connected
    window.close()


def test_stereo_camera_waits_for_confirmed_state_and_recovers_after_failure():
    """相机开关等待板端确认，连接失败后可重试。"""
    ensure_app()
    widget = StereoFishCameraWidget()
    assert not widget.connect_btn.isEnabled()
    widget.set_fish_connection_available(True)
    assert widget.connect_btn.isEnabled()

    widget._stream_state = "connecting"
    widget._on_connection_status(False, "连接失败: test")
    assert widget._stream_state == "error"
    assert widget.connect_btn.isEnabled()

    commands = []
    widget.stream_client.send_command = lambda command: commands.append(command) or True
    widget._on_connection_status(True, "connected")
    assert widget._camera_state == "querying"
    assert not widget.cam_btn.isEnabled()
    widget._on_message(
        '{"type":"node_state","camera_enabled":false,"ranging":false,'
        '"preview_layout":"raw_single"}')
    assert widget._camera_state == "off"
    assert widget.stream_client.preview_layout == "raw_single"
    assert widget.cam_btn.isEnabled()

    widget._toggle_camera()
    widget._toggle_camera()
    assert widget._camera_state == "turning_on"
    assert commands.count("CAM_ON") == 1
    assert not widget.cam_btn.isEnabled()
    widget._on_message('{"type":"camera","enabled":true}')
    assert widget._camera_state == "on"
    assert widget.cam_btn.text() == "关闭摄像头"
    assert widget.camera_state_label.text() == "摄像头: 已开启"

    widget.current_frame = np.zeros((8, 16, 3), dtype=np.uint8)
    widget._apply_ui_state()
    assert widget.record_btn.isEnabled()
    widget.set_fish_connection_available(False)
    assert widget._stream_state == "locked"
    assert not widget.connect_btn.isEnabled()
    assert not widget.cam_btn.isEnabled()
    widget.close()


def test_single_camera_preview_rotates_one_eye_and_enhances_full_frame():
    """原生单目和旧双目兼容流都只输出一目，实时增强处理整张单目帧。"""
    single = np.zeros((4, 6, 3), dtype=np.uint8)
    single[:, :, 1] = 64
    prepared_single = prepare_stereo_display_frame(single, "raw_single")
    assert prepared_single.shape == (6, 4, 3)

    legacy_dual = np.zeros((4, 12, 3), dtype=np.uint8)
    legacy_dual[:, :6, 1] = 64
    legacy_dual[:, 6:, 2] = 255
    prepared_legacy = prepare_stereo_display_frame(legacy_dual, "raw_sbs")
    assert prepared_legacy.shape == (6, 4, 3)
    assert np.array_equal(prepared_single, prepared_legacy)

    processed = np.zeros((960, 1280, 3), dtype=np.uint8)
    assert prepare_stereo_display_frame(processed, "processed") is processed
    assert EnhancementWorker._region_height(
        prepared_single, {"region": "auto", "source_mode": "live"}) == 6
    assert EnhancementWorker._region_height(
        processed, {"region": "auto", "source_mode": "mock"}) == 480


def test_video_client_failure_resets_running_flag_once():
    """视频 TCP 连接失败必须复位 running，且只发一次断开状态。"""
    ensure_app()
    client = StereoVideoClient()
    client.set_connection("127.0.0.1", 9998)
    statuses = []
    client.connection_status.connect(
        lambda connected, message: statuses.append((connected, message)))
    fake_socket = Mock()
    fake_socket.connect.side_effect = OSError("offline")
    with patch("ui.stereo_camera_widget.socket.socket", return_value=fake_socket):
        client.run()
    assert not client.running
    assert not client.connected
    assert client.socket is None
    assert len(statuses) == 1
    assert statuses[0][0] is False


def test_splitter_uses_wide_defaults_and_persists_per_variant():
    """首次启动使用宽侧栏，之后恢复用户上次拖动的宽度。"""
    app = ensure_app()
    with tempfile.TemporaryDirectory() as directory:
        settings_path = Path(directory) / "layout.ini"
        window = MainWindow("dual")
        window._settings = QSettings(str(settings_path), QSettings.IniFormat)
        window.resize(1400, 900)
        window.show()
        app.processEvents()
        window._restore_splitter_sizes()
        app.processEvents()
        first_sizes = window.main_splitter.sizes()
        # offscreen 平台会把 1400 px 窗口压缩到虚拟屏宽度，
        # 因此验证明显宽于旧默认 220/200，不要求物理像素完全相等。
        assert first_sizes[0] >= 300
        assert first_sizes[2] >= 210

        window.main_splitter.setSizes([400, 600, 300])
        app.processEvents()
        saved_sizes = window.main_splitter.sizes()
        window._save_splitter_sizes()
        window.main_splitter.setSizes([320, 760, 220])
        window._restore_splitter_sizes()
        app.processEvents()
        restored_sizes = window.main_splitter.sizes()
        assert abs(restored_sizes[0] - saved_sizes[0]) <= 2
        assert abs(restored_sizes[2] - saved_sizes[2]) <= 2
        window.close()


def test_recording_panel_is_replaced_by_time_series_export_buttons():
    """右侧不再显示数据记录页，导出功能位于时间序列页。"""
    ensure_app()
    window = MainWindow(variant="dual")
    tab_names = [window.right_tabs.tabText(index)
                 for index in range(window.right_tabs.count())]
    assert "数据记录" not in tab_names
    assert not hasattr(window, "data_recording_widget")
    assert window.visualization_widget.save_time_data_btn.text() == "保存数据"
    assert window.visualization_widget.save_time_image_btn.text() == "保存图像"
    window.close()
