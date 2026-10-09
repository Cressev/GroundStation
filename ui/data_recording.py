#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据记录控制界面
Data Recording Control Widget
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QLabel, QPushButton, QProgressBar, QFrame, QFileDialog,
                             QLineEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette

import sys
import os
import time
import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.recorder import DataRecorder
from utils.graphics_exporter import GraphicsExporter

class DataRecordingWidget(QWidget):
    """数据记录控制组件"""
    
    # 信号定义
    export_graphics_requested = pyqtSignal()  # 请求导出图形
    
    def __init__(self):
        super().__init__()
        self.data_recorder = DataRecorder()
        self.graphics_exporter = GraphicsExporter()

        # 分传感器数据缓存（IMU/深度）：记录中累积，停止时按保存时刻落盘 CSV
        self._imu_rows = []
        self._depth_rows = []

        self._init_ui()
        self._init_connections()
        
        # 状态更新定时器
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(1000)  # 每秒更新
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("数据记录控制")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # 记录控制组
        record_group = QGroupBox("记录控制")
        record_layout = QVBoxLayout(record_group)
        
        # 控制按钮行
        button_layout = QHBoxLayout()
        
        self.start_record_btn = QPushButton("开始记录")
        self.start_record_btn.clicked.connect(self._start_recording)
        self.start_record_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        
        self.pause_record_btn = QPushButton("暂停记录")
        self.pause_record_btn.clicked.connect(self._pause_recording)
        self.pause_record_btn.setEnabled(False)
        self.pause_record_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; font-weight: bold; }")
        
        self.stop_record_btn = QPushButton("停止记录")
        self.stop_record_btn.clicked.connect(self._stop_recording)
        self.stop_record_btn.setEnabled(False)
        self.stop_record_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; font-weight: bold; }")
        
        button_layout.addWidget(self.start_record_btn)
        button_layout.addWidget(self.pause_record_btn)
        button_layout.addWidget(self.stop_record_btn)
        
        record_layout.addLayout(button_layout)
        
        # 记录状态显示
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("记录状态: 未开始")
        self.status_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.status_label.setStyleSheet("color: #666;")
        
        self.points_label = QLabel("记录点数: 0")
        self.points_label.setFont(QFont("Arial", 10))
        
        self.duration_label = QLabel("记录时长: 0.0 秒")
        self.duration_label.setFont(QFont("Arial", 10))
        
        # 进度条（显示相对于最大记录点数的进度）
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(10000)  # 与配置中的max_record_points对应
        self.progress_bar.setValue(0)
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.points_label)
        status_layout.addWidget(self.duration_label)
        status_layout.addWidget(QLabel("记录进度:"))
        status_layout.addWidget(self.progress_bar)
        
        record_layout.addLayout(status_layout)
        layout.addWidget(record_group)
        
        # 数据保存组
        save_group = QGroupBox("数据保存")
        save_layout = QVBoxLayout(save_group)

        save_button_layout = QHBoxLayout()

        self.save_csv_btn = QPushButton("保存CSV")
        self.save_csv_btn.clicked.connect(self._save_csv)
        self.save_csv_btn.setEnabled(False)
        
        self.save_excel_btn = QPushButton("保存Excel")
        self.save_excel_btn.clicked.connect(self._save_excel)
        self.save_excel_btn.setEnabled(False)
        
        self.clear_data_btn = QPushButton("清空数据")
        self.clear_data_btn.clicked.connect(self._clear_data)
        
        save_button_layout.addWidget(self.save_csv_btn)
        save_button_layout.addWidget(self.save_excel_btn)
        save_button_layout.addWidget(self.clear_data_btn)
        
        save_layout.addLayout(save_button_layout)
        layout.addWidget(save_group)
        
        # 图形导出组
        export_group = QGroupBox("图形导出")
        export_layout = QVBoxLayout(export_group)
        
        export_button_layout = QHBoxLayout()
        
        self.export_current_btn = QPushButton("导出当前图形")
        self.export_current_btn.clicked.connect(self._export_current_graphics)
        
        self.export_all_btn = QPushButton("导出所有图形")
        self.export_all_btn.clicked.connect(self._export_all_graphics)
        
        export_button_layout.addWidget(self.export_current_btn)
        export_button_layout.addWidget(self.export_all_btn)

        export_layout.addLayout(export_button_layout)
        layout.addWidget(export_group)

        # 分传感器数据保存目录组（IMU/深度；文件按保存时间自动命名）
        path_group = QGroupBox("传感器数据保存目录")
        path_layout = QVBoxLayout(path_group)

        imu_row = QHBoxLayout()
        imu_row.addWidget(QLabel("IMU 目录:"))
        self.imu_path_input = QLineEdit("records/imu")
        imu_row.addWidget(self.imu_path_input, 1)
        self.imu_path_btn = QPushButton("浏览…")
        self.imu_path_btn.clicked.connect(
            lambda: self._browse_sensor_dir(self.imu_path_input, "IMU 数据"))
        imu_row.addWidget(self.imu_path_btn)
        path_layout.addLayout(imu_row)

        depth_row = QHBoxLayout()
        depth_row.addWidget(QLabel("深度目录:"))
        self.depth_path_input = QLineEdit("records/depth")
        depth_row.addWidget(self.depth_path_input, 1)
        self.depth_path_btn = QPushButton("浏览…")
        self.depth_path_btn.clicked.connect(
            lambda: self._browse_sensor_dir(self.depth_path_input, "深度数据"))
        depth_row.addWidget(self.depth_path_btn)
        path_layout.addLayout(depth_row)

        self.sensor_path_hint = QLabel(
            "停止记录时在上述目录生成 CSV，文件名=保存时刻")
        self.sensor_path_hint.setStyleSheet("color: #666; font-size: 10pt;")
        path_layout.addWidget(self.sensor_path_hint)
        layout.addWidget(path_group)

        layout.addStretch()

    def _browse_sensor_dir(self, line_edit, title):
        """浏览选择某个传感器数据的保存目录。"""
        path = QFileDialog.getExistingDirectory(
            self, f"选择{title}保存目录", line_edit.text() or "records")
        if path:
            line_edit.setText(path)

    def add_sensor_points(self, fish_state):
        """记录进行中时，把 IMU/深度数据缓存进各自序列（主定时器调用）。

        停止记录时统一按\"保存目录/保存时刻.csv\"落盘。
        """
        if not self.data_recorder.is_recording:
            return
        now = time.time()
        o = fish_state.orientation
        self._imu_rows.append(
            [f"{now:.3f}", o.get("roll", 0.0), o.get("pitch", 0.0),
             o.get("yaw", 0.0)])
        d = getattr(fish_state, "depth", None) or {}
        self._depth_rows.append(
            [f"{now:.3f}", d.get("raw_1"), d.get("filtered_1"),
             d.get("raw_2"), d.get("filtered_2"), d.get("fused"),
             d.get("calibrated")])

    def _save_sensor_csvs(self):
        """停止记录：把缓存序列写入 <目录>/<保存时刻>.csv（每传感器一个文件）。"""
        import csv as _csv
        import os as _os
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        jobs = (
            ("IMU", self.imu_path_input, self._imu_rows,
             ["时间戳", "roll(rad)", "pitch(rad)", "yaw(rad)"]),
            ("深度", self.depth_path_input, self._depth_rows,
             ["时间戳", "原始1", "滤波1", "原始2", "滤波2", "融合", "标定后"]),
        )
        saved = []
        for kind, line_edit, rows, header in jobs:
            if not rows:
                continue
            dir_path = line_edit.text().strip() or f"records/{kind}"
            try:
                _os.makedirs(dir_path, exist_ok=True)
                file_path = _os.path.join(dir_path, f"{stamp}.csv")
                with open(file_path, "w", newline="", encoding="utf-8") as f:
                    writer = _csv.writer(f)
                    writer.writerow(header)
                    writer.writerows(rows)
                saved.append(f"{kind} {len(rows)}点 -> {file_path}")
            except OSError as exc:
                saved.append(f"{kind} 保存失败: {exc}")
        if saved:
            self.sensor_path_hint.setText("；".join(saved))

    def _reset_sensor_rows(self):
        """开始记录：清空两路缓存序列，从零累积。"""
        self._imu_rows = []
        self._depth_rows = []
    
    def _init_connections(self):
        """初始化信号连接"""
        # 数据记录器信号
        self.data_recorder.recording_started.connect(self._on_recording_started)
        self.data_recorder.recording_paused.connect(self._on_recording_paused)
        self.data_recorder.recording_resumed.connect(self._on_recording_resumed)
        self.data_recorder.recording_stopped.connect(self._on_recording_stopped)
        self.data_recorder.data_saved.connect(self._on_data_saved)
        self.data_recorder.recording_status_changed.connect(self._on_status_changed)
        
        # 图形导出器信号
        self.graphics_exporter.export_completed.connect(self._on_export_completed)
        self.graphics_exporter.export_failed.connect(self._on_export_failed)
    
    def _start_recording(self):
        """开始记录（清空传感器缓存，从零累积）"""
        self.data_recorder.start_recording()
        self._reset_sensor_rows()
        self.sensor_path_hint.setText("记录中… 停止时按保存时刻落盘 CSV")

    def _pause_recording(self):
        """暂停/恢复记录"""
        if self.data_recorder.is_paused:
            self.data_recorder.resume_recording()
        else:
            self.data_recorder.pause_recording()

    def _stop_recording(self):
        """停止记录（IMU/深度缓存按保存时刻落盘为 CSV）"""
        self.data_recorder.stop_recording()
        self._save_sensor_csvs()
    
    def _save_csv(self):
        """保存CSV文件"""
        save_dir = self._get_save_directory("选择CSV保存目录")
        if save_dir:
            try:
                # 临时设置保存目录
                original_dir = self.data_recorder.save_directory
                self.data_recorder.save_directory = save_dir
                
                filepath = self.data_recorder.save_data()
                print(f"CSV文件已保存: {filepath}")
                
                # 恢复原目录
                self.data_recorder.save_directory = original_dir
            except Exception as e:
                print(f"保存CSV失败: {e}")
    
    def _save_excel(self):
        """保存Excel文件"""
        save_dir = self._get_save_directory("选择Excel保存目录")
        if save_dir:
            try:
                # 临时设置保存目录
                original_dir = self.data_recorder.save_directory
                self.data_recorder.save_directory = save_dir
                
                filepath = self.data_recorder.export_to_excel()
                print(f"Excel文件已保存: {filepath}")
                
                # 恢复原目录
                self.data_recorder.save_directory = original_dir
            except Exception as e:
                print(f"保存Excel失败: {e}")
    
    def _get_save_directory(self, title: str) -> str:
        """获取保存目录"""
        import datetime
        
        # 创建默认目录路径，并确保父目录存在
        default_dir = f"records/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 确保默认目录的父目录存在
        parent_dir = os.path.dirname(default_dir)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                print(f"创建父目录失败: {e}")
                default_dir = "."  # 使用当前目录作为备用
        
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            title, 
            default_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if selected_dir:
            # 确保目录存在
            try:
                os.makedirs(selected_dir, exist_ok=True)
                print(f"选择的保存目录: {selected_dir}")
                return selected_dir
            except Exception as e:
                print(f"创建选择的目录失败: {e}")
                return None
        return None
    
    def _clear_data(self):
        """清空数据"""
        self.data_recorder.clear_data()
        self._update_status_display()
    
    def _export_current_graphics(self):
        """导出当前图形"""
        save_dir = self._get_save_directory("选择图形保存目录")
        if save_dir:
            # 临时设置图形导出器的保存目录
            original_dir = self.graphics_exporter.save_directory
            self.graphics_exporter.save_directory = save_dir
            
            self.export_graphics_requested.emit()
            
            # 恢复原目录
            self.graphics_exporter.save_directory = original_dir
    
    def _export_all_graphics(self):
        """导出所有图形"""
        save_dir = self._get_save_directory("选择图形保存目录")
        if save_dir:
            # 临时设置图形导出器的保存目录
            original_dir = self.graphics_exporter.save_directory
            self.graphics_exporter.save_directory = save_dir
            
            self.export_graphics_requested.emit()
            
            # 恢复原目录
            self.graphics_exporter.save_directory = original_dir
    
    def _update_status_display(self):
        """更新状态显示"""
        status = self.data_recorder.get_recording_status()
        
        # 更新标签
        self.points_label.setText(f"记录点数: {status['total_points']}")
        self.duration_label.setText(f"记录时长: {status['total_duration']:.1f} 秒")
        
        # 更新进度条
        self.progress_bar.setValue(status['total_points'])
        
        # 更新保存按钮状态
        has_data = status['total_points'] > 0
        self.save_csv_btn.setEnabled(has_data)
        self.save_excel_btn.setEnabled(has_data)
    
    def _on_recording_started(self):
        """记录开始事件"""
        self.status_label.setText("记录状态: 记录中")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        
        self.start_record_btn.setEnabled(False)
        self.pause_record_btn.setEnabled(True)
        self.stop_record_btn.setEnabled(True)
        self.pause_record_btn.setText("暂停记录")
    
    def _on_recording_paused(self):
        """记录暂停事件"""
        self.status_label.setText("记录状态: 已暂停")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.pause_record_btn.setText("恢复记录")
    
    def _on_recording_resumed(self):
        """记录恢复事件"""
        self.status_label.setText("记录状态: 记录中")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        self.pause_record_btn.setText("暂停记录")
    
    def _on_recording_stopped(self):
        """记录停止事件"""
        self.status_label.setText("记录状态: 已停止")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        
        self.start_record_btn.setEnabled(True)
        self.pause_record_btn.setEnabled(False)
        self.stop_record_btn.setEnabled(False)
        self.pause_record_btn.setText("暂停记录")
    
    def _on_data_saved(self, filepath: str):
        """数据保存完成事件"""
        print(f"数据已保存: {filepath}")
    
    def _on_status_changed(self, message: str):
        """状态变化事件"""
        print(f"记录状态: {message}")
    
    def _on_export_completed(self, filepath: str):
        """导出完成事件"""
        print(f"图形已导出: {filepath}")
    
    def _on_export_failed(self, error_message: str):
        """导出失败事件"""
        print(f"图形导出失败: {error_message}")
    
    def add_data_point(self, fish_state, control_command):
        """添加数据点（外部调用）"""
        self.data_recorder.add_data_point(fish_state, control_command)
    
    def export_graphics(self, visualization_widget):
        """导出图形（外部调用）"""
        try:
            exported_files = self.graphics_exporter.export_all_plots(visualization_widget)
            for filepath in exported_files:
                print(f"图形已导出: {filepath}")
        except Exception as e:
            print(f"导出图形失败: {e}")
    
    def get_data_recorder(self):
        """获取数据记录器"""
        return self.data_recorder
    
    def get_graphics_exporter(self):
        """获取图形导出器"""
        return self.graphics_exporter
