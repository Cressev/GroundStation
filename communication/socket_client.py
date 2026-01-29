#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地面站Socket客户端通信模块
Ground Station Socket Client Communication Module

创建时间: 2026-01-28
说明: 通过TCP Socket连接机器鱼，接收实时传感器数据，发送控制命令。
      支持20-50Hz的数据刷新率。
"""

import socket
import json
import threading
import time
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.base import FishCommunicationInterface, FishState, ControlCommand
from config import FISH_IP


# Socket通信配置
SOCKET_PORT = 9999
SOCKET_TIMEOUT = 5.0
RECONNECT_INTERVAL = 3.0


class SocketCommunication(FishCommunicationInterface):
    """基于Socket的通信实现，用于实时数据传输"""
    
    def __init__(self, ip_address: str = None, port: int = None):
        super().__init__()
        self.fish_ip = ip_address if ip_address else FISH_IP
        self.port = port if port else SOCKET_PORT
        
        self.socket = None
        self._receive_thread = None
        self._stop_event = threading.Event()
        
        # 数据回调
        self._data_callback: Optional[Callable[[FishState], None]] = None
        self._connection_callback: Optional[Callable[[bool], None]] = None
        
        # 接收缓冲区
        self._recv_buffer = ""
        
    def connect(self) -> bool:
        """连接到机器鱼Socket服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(SOCKET_TIMEOUT)
            self.socket.connect((self.fish_ip, self.port))
            
            self._connected = True
            self._stop_event.clear()
            
            # 启动接收线程
            self._receive_thread = threading.Thread(target=self._receive_loop)
            self._receive_thread.daemon = True
            self._receive_thread.start()
            
            print(f"Socket连接成功: {self.fish_ip}:{self.port}")
            
            if self._connection_callback:
                self._connection_callback(True)
            
            return True
            
        except Exception as e:
            print(f"Socket连接失败: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """断开连接"""
        try:
            self._stop_event.set()
            self._connected = False
            
            if self._receive_thread and self._receive_thread.is_alive():
                self._receive_thread.join(timeout=2.0)
            
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            
            print("Socket连接已断开")
            
            if self._connection_callback:
                self._connection_callback(False)
            
            return True
            
        except Exception as e:
            print(f"断开连接异常: {e}")
            return False
    
    def send_control_command(self, command: ControlCommand) -> bool:
        """发送控制命令"""
        if not self._connected or not self.socket:
            return False
        
        try:
            cmd_data = {
                'type': 'control',
                'tail_frequency': command.tail_frequency,
                'tail_amplitude': command.tail_amplitude,
                'tail_offset': command.tail_offset,
                'pec_angle': getattr(command, 'pec_angle', 1500),
                'timestamp': command.timestamp
            }
            
            json_data = json.dumps(cmd_data) + '\n'
            self.socket.sendall(json_data.encode('utf-8'))
            return True
            
        except Exception as e:
            print(f"发送控制命令失败: {e}")
            return False
    
    def get_fish_state(self) -> Optional[FishState]:
        """获取最新的机器鱼状态"""
        return self._last_state
    
    def is_alive(self) -> bool:
        """检查连接是否存活"""
        return self._connected and self.socket is not None
    
    def set_data_callback(self, callback: Callable[[FishState], None]):
        """设置数据回调函数，当收到新数据时调用"""
        self._data_callback = callback
    
    def set_connection_callback(self, callback: Callable[[bool], None]):
        """设置连接状态回调函数"""
        self._connection_callback = callback
    
    def _receive_loop(self):
        """接收数据循环"""
        while not self._stop_event.is_set() and self._connected:
            try:
                # 接收数据
                data = self.socket.recv(4096)
                if not data:
                    # 连接断开
                    print("服务器连接断开")
                    self._connected = False
                    if self._connection_callback:
                        self._connection_callback(False)
                    break
                
                # 解码并添加到缓冲区
                self._recv_buffer += data.decode('utf-8')
                
                # 解析完整的JSON消息（以换行符分隔）
                while '\n' in self._recv_buffer:
                    line, self._recv_buffer = self._recv_buffer.split('\n', 1)
                    if line.strip():
                        self._parse_sensor_data(line.strip())
                
            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    print(f"接收数据异常: {e}")
                    self._connected = False
                    if self._connection_callback:
                        self._connection_callback(False)
                break
    
    def _parse_sensor_data(self, json_str: str):
        """解析传感器数据"""
        try:
            data = json.loads(json_str)
            
            state = FishState()
            
            # 解析IMU数据 -> orientation
            imu = data.get('imu', {})
            state.orientation = {
                'roll': imu.get('roll', 0.0),
                'pitch': imu.get('pitch', 0.0),
                'yaw': imu.get('yaw', 0.0)
            }
            
            # 解析UWB数据 -> position
            uwb = data.get('uwb', {})
            state.position = {
                'x': uwb.get('x', 0.0),
                'y': uwb.get('y', 0.0),
                'z': uwb.get('z', 0.0)
            }
            
            # 解析深度数据 -> 更新position的z值（如果深度数据更准确）
            depth = data.get('depth', {})
            depth_fusion = depth.get('fusion', 0.0)
            if abs(depth_fusion) > 0.001:  # 如果有深度数据，使用深度数据
                state.position['z'] = -depth_fusion  # 深度为负值
            
            state.timestamp = data.get('timestamp', time.time())
            
            # 更新状态
            self._last_state = state
            
            # 触发回调
            if self._data_callback:
                self._data_callback(state)
                
        except json.JSONDecodeError as e:
            print(f"JSON解析失败: {e}")
        except Exception as e:
            print(f"数据解析异常: {e}")


# 为了兼容性，保留原有的SSHROSCommunication类名作为别名
# 但推荐使用SocketCommunication
