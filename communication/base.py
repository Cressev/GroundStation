#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼通信接口基类
Fish Robot Communication Interface Base Class
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
import time

@dataclass
class FishState:
    """机器鱼状态数据结构"""
    position: Dict[str, float]  # x, y, z
    orientation: Dict[str, float]  # roll, pitch, yaw
    timestamp: float
    
    def __init__(self):
        self.position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.orientation = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        # 双目鱼深度数据（gs_bridge depth JSON）：
        # raw_1/filtered_1/raw_2/filtered_2/fused/calibrated，空 dict = 无数据
        self.depth = {}
        self.timestamp = time.time()

@dataclass
class ControlCommand:
    """控制命令数据结构"""
    tail_frequency: float  # 摆尾频率 (Hz)
    tail_amplitude: float  # 摆尾幅度 (rad)
    tail_offset: float     # 摆尾偏移角 (rad)
    timestamp: float
    
    def __init__(self, freq=1.0, amp=0.5, offset=0.0):
        self.tail_frequency = freq
        self.tail_amplitude = amp
        self.tail_offset = offset
        self.timestamp = time.time()

class FishCommunicationInterface(ABC):
    """机器鱼通信接口抽象基类"""
    
    def __init__(self):
        self._connected = False
        self._last_state = FishState()
        
    @property
    def connected(self) -> bool:
        """连接状态"""
        return self._connected
        
    @abstractmethod
    def connect(self) -> bool:
        """连接到机器鱼"""
        pass
        
    @abstractmethod
    def disconnect(self) -> bool:
        """断开连接"""
        pass
        
    @abstractmethod
    def send_control_command(self, command: ControlCommand) -> bool:
        """发送控制命令"""
        pass
        
    @abstractmethod
    def get_fish_state(self) -> Optional[FishState]:
        """获取机器鱼状态"""
        pass
        
    @abstractmethod
    def is_alive(self) -> bool:
        """检查连接是否存活"""
        pass
