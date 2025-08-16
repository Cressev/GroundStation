#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据记录管理器
Data Recording Manager
"""

import os
import csv
import json
import time
import threading
import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import pandas as pd

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from communication.base import FishState, ControlCommand
from config import RECORD_CONFIG

@dataclass
class RecordEntry:
    """记录数据条目"""
    timestamp: float
    position_x: float
    position_y: float
    position_z: float
    orientation_roll: float
    orientation_pitch: float
    orientation_yaw: float
    control_frequency: float
    control_amplitude: float
    control_offset: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_fish_state_and_command(cls, fish_state: FishState, control_command: ControlCommand):
        """从鱼状态和控制命令创建记录条目"""
        return cls(
            timestamp=fish_state.timestamp,
            position_x=fish_state.position['x'],
            position_y=fish_state.position['y'],
            position_z=fish_state.position['z'],
            orientation_roll=fish_state.orientation['roll'],
            orientation_pitch=fish_state.orientation['pitch'],
            orientation_yaw=fish_state.orientation['yaw'],
            control_frequency=control_command.tail_frequency,
            control_amplitude=control_command.tail_amplitude,
            control_offset=control_command.tail_offset
        )

class DataRecorder(QObject):
    """数据记录器"""
    
    # 信号定义
    recording_started = pyqtSignal()
    recording_paused = pyqtSignal()
    recording_resumed = pyqtSignal()
    recording_stopped = pyqtSignal()
    data_saved = pyqtSignal(str)  # 保存的文件路径
    recording_status_changed = pyqtSignal(str)  # 状态消息
    
    def __init__(self):
        super().__init__()
        self.is_recording = False
        self.is_paused = False
        self.recorded_data: List[RecordEntry] = []
        self.current_session_start = None
        self.total_recording_time = 0.0
        
        # 确保保存目录存在
        self.save_directory = RECORD_CONFIG["save_directory"]
        if not os.path.exists(self.save_directory):
            os.makedirs(self.save_directory)
        
        # 自动保存定时器
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self._auto_save)
        
    def start_recording(self):
        """开始记录"""
        if not self.is_recording:
            self.is_recording = True
            self.is_paused = False
            self.current_session_start = time.time()
            
            # 启动自动保存
            self.auto_save_timer.start(RECORD_CONFIG["auto_save_interval"] * 1000)
            
            self.recording_started.emit()
            self.recording_status_changed.emit("数据记录已开始")
            print("数据记录已开始")
    
    def pause_recording(self):
        """暂停记录"""
        if self.is_recording and not self.is_paused:
            self.is_paused = True
            
            # 累计记录时间
            if self.current_session_start:
                self.total_recording_time += time.time() - self.current_session_start
            
            self.recording_paused.emit()
            self.recording_status_changed.emit("数据记录已暂停")
            print("数据记录已暂停")
    
    def resume_recording(self):
        """恢复记录"""
        if self.is_recording and self.is_paused:
            self.is_paused = False
            self.current_session_start = time.time()
            
            self.recording_resumed.emit()
            self.recording_status_changed.emit("数据记录已恢复")
            print("数据记录已恢复")
    
    def stop_recording(self):
        """停止记录"""
        if self.is_recording:
            self.is_recording = False
            self.is_paused = False
            
            # 累计总记录时间
            if self.current_session_start:
                self.total_recording_time += time.time() - self.current_session_start
                self.current_session_start = None
            
            # 停止自动保存
            self.auto_save_timer.stop()
            
            self.recording_stopped.emit()
            self.recording_status_changed.emit("数据记录已停止")
            print(f"数据记录已停止，总时长: {self.total_recording_time:.1f}秒，记录点数: {len(self.recorded_data)}")
    
    def add_data_point(self, fish_state: FishState, control_command: ControlCommand):
        """添加数据点"""
        if self.is_recording and not self.is_paused:
            entry = RecordEntry.from_fish_state_and_command(fish_state, control_command)
            self.recorded_data.append(entry)
            
            # 检查是否超过最大记录点数
            if len(self.recorded_data) > RECORD_CONFIG["max_record_points"]:
                self.recorded_data.pop(0)  # 移除最老的数据点
    
    def save_data(self, filename: Optional[str] = None) -> str:
        """保存数据到文件"""
        if not self.recorded_data:
            raise ValueError("没有可保存的数据")
        
        if filename is None:
            timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
            filename = f"fish_data_{timestamp}.csv"
        
        filepath = os.path.join(self.save_directory, filename)
        
        try:
            # 保存为CSV格式
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                if self.recorded_data:
                    fieldnames = list(self.recorded_data[0].to_dict().keys())
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for entry in self.recorded_data:
                        writer.writerow(entry.to_dict())
            
            # 同时保存元数据
            metadata = {
                "recording_start": self.recorded_data[0].timestamp if self.recorded_data else 0,
                "recording_end": self.recorded_data[-1].timestamp if self.recorded_data else 0,
                "total_points": len(self.recorded_data),
                "total_duration": self.total_recording_time,
                "config": RECORD_CONFIG
            }
            
            metadata_file = filepath.replace('.csv', '_metadata.json')
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            self.data_saved.emit(filepath)
            self.recording_status_changed.emit(f"数据已保存到: {filename}")
            print(f"数据已保存到: {filepath}")
            return filepath
            
        except Exception as e:
            error_msg = f"保存数据失败: {str(e)}"
            self.recording_status_changed.emit(error_msg)
            raise Exception(error_msg)
    
    def _auto_save(self):
        """自动保存"""
        if self.recorded_data:
            try:
                timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
                filename = f"fish_data_auto_{timestamp}.csv"
                self.save_data(filename)
                print("自动保存完成")
            except Exception as e:
                print(f"自动保存失败: {e}")
    
    def clear_data(self):
        """清空记录数据"""
        self.recorded_data.clear()
        self.total_recording_time = 0.0
        self.recording_status_changed.emit("记录数据已清空")
        print("记录数据已清空")
    
    def get_recording_status(self) -> Dict[str, Any]:
        """获取记录状态"""
        current_duration = 0.0
        if self.is_recording and not self.is_paused and self.current_session_start:
            current_duration = time.time() - self.current_session_start
        
        return {
            "is_recording": self.is_recording,
            "is_paused": self.is_paused,
            "total_points": len(self.recorded_data),
            "total_duration": self.total_recording_time + current_duration,
            "current_session_duration": current_duration
        }
    
    def export_to_excel(self, filename: Optional[str] = None) -> str:
        """导出为Excel格式"""
        if not self.recorded_data:
            raise ValueError("没有可导出的数据")
        
        if filename is None:
            timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
            filename = f"fish_data_{timestamp}.xlsx"
        
        filepath = os.path.join(self.save_directory, filename)
        
        try:
            # 转换为DataFrame
            data_dicts = [entry.to_dict() for entry in self.recorded_data]
            df = pd.DataFrame(data_dicts)
            
            # 保存为Excel
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Fish_Data', index=False)
                
                # 添加统计信息sheet
                stats_data = {
                    '统计项': ['总记录点数', '记录时长(秒)', '平均频率', '平均幅度', 
                              'X位置范围', 'Y位置范围', 'Z位置范围'],
                    '数值': [
                        len(self.recorded_data),
                        self.total_recording_time,
                        df['control_frequency'].mean() if len(df) > 0 else 0,
                        df['control_amplitude'].mean() if len(df) > 0 else 0,
                        f"{df['position_x'].min():.3f} ~ {df['position_x'].max():.3f}" if len(df) > 0 else "N/A",
                        f"{df['position_y'].min():.3f} ~ {df['position_y'].max():.3f}" if len(df) > 0 else "N/A",
                        f"{df['position_z'].min():.3f} ~ {df['position_z'].max():.3f}" if len(df) > 0 else "N/A"
                    ]
                }
                stats_df = pd.DataFrame(stats_data)
                stats_df.to_excel(writer, sheet_name='Statistics', index=False)
            
            self.recording_status_changed.emit(f"数据已导出到Excel: {filename}")
            return filepath
            
        except Exception as e:
            error_msg = f"导出Excel失败: {str(e)}"
            self.recording_status_changed.emit(error_msg)
            raise Exception(error_msg)
