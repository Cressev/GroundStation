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
import math
from copy import deepcopy
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
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        
        # 数据回调
        self._data_callback: Optional[Callable[[FishState], None]] = None
        self._connection_callback: Optional[Callable[[bool], None]] = None
        # 板端状态回推回调（state JSON 原始 dict，含控制板遥测）
        self._state_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        # 心跳回调（每真实发出一拍心跳调用一次，供 UI 呼吸灯等）
        self._heartbeat_callback: Optional[Callable[[int], None]] = None
        self._hb_seq = 0
        self._send_lock = threading.Lock()

        # 接收缓冲区
        self._recv_buffer = ""
        
    def connect(self) -> bool:
        """连接到机器鱼Socket服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(SOCKET_TIMEOUT)
            self.socket.connect((self.fish_ip, self.port))
            
            self._connected = True
            self._last_state = FishState()
            self._stop_event.clear()
            
            # 启动接收线程
            self._receive_thread = threading.Thread(target=self._receive_loop)
            self._receive_thread.daemon = True
            self._receive_thread.start()

            # 启动心跳线程：gs_bridge 静默超过 2s 会判为断链并周期发兜底停止帧
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
            self._heartbeat_thread.daemon = True
            self._heartbeat_thread.start()
            
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
                'tail_phase_diff': getattr(command, 'tail_phase_diff', 1.57),
                'pec_angle': getattr(command, 'pec_angle', 1500),
                'timestamp': command.timestamp
            }
            if getattr(command, 'pectoral_owner', None) in ('pico_depth', 'pico_hold'):
                cmd_data.pop('pec_angle')
                cmd_data['pectoral_owner'] = command.pectoral_owner
            
            json_data = json.dumps(cmd_data) + '\n'
            with self._send_lock:
                self.socket.sendall(json_data.encode('utf-8'))
            return True
            
        except Exception as e:
            print(f"发送控制命令失败: {e}")
            return False
    
    def get_fish_state(self) -> Optional[FishState]:
        """获取最新的机器鱼状态"""
        return deepcopy(self._last_state)

    def send_depth_control(self, request):
        """Send a board-local PID request as a single serialized JSON line."""
        if not self._connected or self.socket is None:
            return False
        try:
            payload = (json.dumps(request, allow_nan=False)+'\n').encode('utf-8')
            with self._send_lock:
                self.socket.sendall(payload)
            return True
        except (OSError, ValueError, TypeError):
            return False
    
    def is_alive(self) -> bool:
        """检查连接是否存活"""
        return self._connected and self.socket is not None
    
    def set_data_callback(self, callback: Callable[[FishState], None]):
        """设置数据回调函数，当收到新数据时调用"""
        self._data_callback = callback
    
    def set_connection_callback(self, callback: Callable[[bool], None]):
        """设置连接状态回调函数"""
        self._connection_callback = callback

    def set_state_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """设置板端状态回推回调（state JSON 原始 dict，含遥测字段）"""
        self._state_callback = callback

    def set_heartbeat_callback(self, callback: Callable[[int], None]):
        """设置心跳回调：每真实发出一拍心跳调用一次（参数=累计拍数）。

        注意回调在心跳线程执行，UI 侧请经 Qt 信号转回主线程。
        """
        self._heartbeat_callback = callback
    
    def _heartbeat_loop(self):
        """每 0.5s 发送一行心跳 JSON（gs_bridge 静默 2s 即判为断链并兜底停止）。"""
        payload = (json.dumps({"type": "ping"}) + "\n").encode("utf-8")
        while not self._stop_event.is_set() and self._connected and self.socket:
            try:
                with self._send_lock:
                    self.socket.sendall(payload)
                self._hb_seq += 1
                if self._heartbeat_callback:
                    self._heartbeat_callback(self._hb_seq)  # 真实发出后才触发（UI 呼吸灯）
            except Exception:
                break  # 发送失败=连接已死，交给接收线程走断线回调
            time.sleep(0.5)

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
    
    def _sensor_identity(self, data, previous=None):
        """Keep source sample identity and age independent of packet/display timestamps."""
        identity = data.get('sample_id')
        try:
            age = float(data.get('age_s', float('nan')))
            if identity is None or not math.isfinite(age) or age < 0:
                return None
        except (ValueError, TypeError):
            return None
        if previous is not None and previous['id'] == identity:
            return previous
        return dict(id=identity, age_s=age, received_at=time.monotonic(),
                    source_timestamp=data.get('sample_timestamp'))

    def _merge_imu(self, imu):
        """Copy new IMU state while rejecting malformed radians and never fabricating pitch=0."""
        if not isinstance(imu, dict):
            return
        try:
            angles = {key: float(imu[key]) for key in ('roll', 'pitch', 'yaw')}
            if not all(math.isfinite(value) for value in angles.values()) or abs(angles['pitch']) > math.pi / 2 + .001:
                return
        except (KeyError, ValueError, TypeError):
            return
        state = deepcopy(self._last_state or FishState())
        state.orientation = angles
        state.imu_sample = self._sensor_identity(imu, state.imu_sample)
        state.timestamp = time.time()
        self._last_state = state
        if self._data_callback:
            self._data_callback(state)

    def _parse_sensor_data(self, json_str: str):
        """解析传感器数据"""
        try:
            data = json.loads(json_str)
            if data.get('type') == 'depth_control_state':
                state = deepcopy(self._last_state or FishState())
                state.depth_control = data
                self._last_state = state
                return
            if data.get('type') == 'imu':
                self._merge_imu(data)
                return

            # gs_bridge 状态回推（含控制板遥测/IMU）：遥测走状态回调；
            # IMU 欧拉角合并进持久 FishState 并触发数据回调（图表实时刷新）
            if data.get("type") == "state":
                if data.get('depth_control') is not None:
                    state = deepcopy(self._last_state or FishState())
                    state.depth_control = data['depth_control']
                    self._last_state = state
                if self._state_callback:
                    self._state_callback(data)
                imu = data.get("imu")
                if imu:
                    self._merge_imu(imu)
                return

            state = FishState()
            state.timestamp = data.get("timestamp", time.time())

            if data.get("type") == "depth":
                # 双目鱼深度 JSON（10Hz）：五路数值原样进 state.depth，
                # 标定后深度由主窗口按零点扣减后补进 "calibrated"。
                # 复用持久 state，保留 IMU 分支已合并的姿态
                st = deepcopy(self._last_state or FishState())
                st.depth = {k: data.get(k) for k in
                            ("raw_1", "filtered_1", "raw_2",
                             "filtered_2", "fused")}
                st.timestamp = data.get("timestamp", time.time())
                st.depth_timestamp = st.timestamp
                st.depth_sample = self._sensor_identity(data, st.depth_sample)
                self._last_state = st
                if self._data_callback:
                    self._data_callback(st)
                return

            # 旧版单尾鱼组合格式：IMU/UWB/depth
            
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
            # 降低阈值，因为机器鱼实际深度较浅（0.2-2米）
            if abs(depth_fusion) > 0.0001:  # 原来是0.001，太严格了
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
