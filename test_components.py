#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组件测试脚本
Component Test Script
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试所有组件的导入"""
    print("测试组件导入...")
    
    try:
        # 测试基础配置
        from config import UI_CONFIG, KEYBOARD_MAPPING, RECORD_CONFIG, VIDEO_CONFIG
        print("✓ 配置模块导入成功")
    except Exception as e:
        print(f"✗ 配置模块导入失败: {e}")
        return False
    
    try:
        # 测试通信模块
        from communication.base import FishState, ControlCommand
        from communication.ssh_ros import SSHROSCommunication
        print("✓ 通信模块导入成功")
    except Exception as e:
        print(f"✗ 通信模块导入失败: {e}")
        return False
    
    try:
        # 测试控制器模块
        from controllers.base import KeyboardController
        print("✓ 控制器模块导入成功")
    except Exception as e:
        print(f"✗ 控制器模块导入失败: {e}")
        return False
    
    try:
        # 测试数据记录模块
        from data.recorder import DataRecorder
        print("✓ 数据记录模块导入成功")
    except Exception as e:
        print(f"✗ 数据记录模块导入失败: {e}")
        return False
    
    try:
        # 测试图形导出模块
        from utils.graphics_exporter import GraphicsExporter
        print("✓ 图形导出模块导入成功")
    except Exception as e:
        print(f"✗ 图形导出模块导入失败: {e}")
        return False
    
    try:
        # 测试UI模块
        from ui.main_window import MainWindow
        from ui.visualization import DataVisualizationWidget
        from ui.keyboard_status import KeyboardStatusWidget
        from ui.video_display import VideoDisplayWidget
        from ui.data_recording import DataRecordingWidget
        print("✓ UI模块导入成功")
    except Exception as e:
        print(f"✗ UI模块导入失败: {e}")
        return False
    
    print("所有组件导入测试通过！")
    return True

def test_data_recorder():
    """测试数据记录器"""
    print("\n测试数据记录器...")
    
    try:
        from data.recorder import DataRecorder
        from communication.base import FishState, ControlCommand
        
        recorder = DataRecorder()
        
        # 创建测试数据
        fish_state = FishState(x=1.0, y=2.0, z=3.0, roll=0.1, pitch=0.2, yaw=0.3)
        control_command = ControlCommand(thrust=0.5, yaw_rate=0.1, pitch_rate=0.0, roll_rate=0.0)
        
        # 测试记录
        recorder.start_recording()
        recorder.add_data_point(fish_state, control_command)
        recorder.stop_recording()
        
        status = recorder.get_recording_status()
        print(f"✓ 数据记录器测试成功，记录了 {status['total_points']} 个数据点")
        return True
        
    except Exception as e:
        print(f"✗ 数据记录器测试失败: {e}")
        return False

def test_graphics_exporter():
    """测试图形导出器"""
    print("\n测试图形导出器...")
    
    try:
        from utils.graphics_exporter import GraphicsExporter
        import matplotlib.pyplot as plt
        
        exporter = GraphicsExporter()
        
        # 创建简单的测试数据
        data_history = {
            'time': [0, 1, 2, 3, 4],
            'x': [0, 1, 2, 3, 4],
            'y': [0, 2, 4, 6, 8],
            'z': [0, -1, -2, -3, -4],
            'roll': [0, 0.1, 0.2, 0.3, 0.4],
            'pitch': [0, 0.05, 0.1, 0.15, 0.2],
            'yaw': [0, 0.15, 0.3, 0.45, 0.6]
        }
        
        # 测试matplotlib导出
        filepath = exporter.export_data_as_matplotlib(data_history, filename="test_plot.png")
        print(f"✓ 图形导出器测试成功，文件保存至: {filepath}")
        return True
        
    except Exception as e:
        print(f"✗ 图形导出器测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 50)
    print("机器鱼控制系统组件测试")
    print("=" * 50)
    
    success_count = 0
    total_tests = 3
    
    # 导入测试
    if test_imports():
        success_count += 1
    
    # 数据记录器测试
    if test_data_recorder():
        success_count += 1
    
    # 图形导出器测试
    if test_graphics_exporter():
        success_count += 1
    
    print("\n" + "=" * 50)
    print(f"测试完成: {success_count}/{total_tests} 通过")
    
    if success_count == total_tests:
        print("✓ 所有测试通过！系统组件运行正常。")
        return True
    else:
        print("✗ 有测试失败，请检查错误信息。")
        return False

if __name__ == "__main__":
    main()
