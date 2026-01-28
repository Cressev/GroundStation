#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH/ROS通信实现
SSH/ROS Communication Implementation
"""

import paramiko
import json
import time
import threading
from typing import Optional, Dict, Any

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.base import FishCommunicationInterface, FishState, ControlCommand
from config import FISH_IP, SSH_PORT, SSH_USERNAME, SSH_PASSWORD

class SSHROSCommunication(FishCommunicationInterface):
    """基于SSH的ROS通信实现"""
    
    def __init__(self, ip_address: str = None):
        super().__init__()
        # 使用传入的IP地址，如果没有则使用配置文件中的默认值
        self.fish_ip = ip_address if ip_address else FISH_IP
        self.ros_master_uri = f"http://{self.fish_ip}:11311"
        self.ssh_client = None
        self.sftp_client = None
        self._monitoring_thread = None
        self._stop_monitoring = False
        
    def connect(self) -> bool:
        """连接到机器鱼"""
        try:
            # 创建SSH连接
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            self.ssh_client.connect(
                hostname=self.fish_ip,
                port=SSH_PORT,
                username=SSH_USERNAME,
                password=SSH_PASSWORD,
                timeout=10
            )
            
            # 创建SFTP连接
            self.sftp_client = self.ssh_client.open_sftp()
            
            # 测试ROS连接
            if self._test_ros_connection():
                self._connected = True
                self._start_monitoring()
                return True
            else:
                self.disconnect()
                return False
                
        except Exception as e:
            print(f"连接失败: {e}")
            return False
    
    def disconnect(self) -> bool:
        """断开连接"""
        try:
            self._stop_monitoring = True
            if self._monitoring_thread:
                self._monitoring_thread.join(timeout=2.0)
                
            if self.sftp_client:
                self.sftp_client.close()
                self.sftp_client = None
                
            if self.ssh_client:
                self.ssh_client.close()
                self.ssh_client = None
                
            self._connected = False
            return True
            
        except Exception as e:
            print(f"断开连接失败: {e}")
            return False
    
    def _test_ros_connection(self) -> bool:
        """测试ROS连接"""
        try:
            # 检查ROS master是否运行
            stdin, stdout, stderr = self.ssh_client.exec_command(
                f"export ROS_MASTER_URI={self.ros_master_uri} && rostopic list"
            )
            
            result = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            
            if error and "ERROR" in error:
                print(f"ROS连接测试失败: {error}")
                return False
                
            print("ROS连接测试成功")
            return True
            
        except Exception as e:
            print(f"ROS连接测试异常: {e}")
            return False
    
    def send_control_command(self, command: ControlCommand) -> bool:
        """发送控制命令"""
        if not self._connected:
            return False
            
        try:
            # 构造ROS命令
            ros_command = f"""
export ROS_MASTER_URI={self.ros_master_uri} && 
rostopic pub -1 /fish/control_cmd fish_msgs/ControlCommand "{{
    tail_frequency: {command.tail_frequency},
    tail_amplitude: {command.tail_amplitude}, 
    tail_offset: {command.tail_offset},
    timestamp: {command.timestamp}
}}"
"""
            
            # 执行命令
            stdin, stdout, stderr = self.ssh_client.exec_command(ros_command)
            
            error = stderr.read().decode('utf-8')
            if error and "ERROR" in error:
                print(f"发送控制命令失败: {error}")
                return False
                
            return True
            
        except Exception as e:
            print(f"发送控制命令异常: {e}")
            return False
    
    def get_fish_state(self) -> Optional[FishState]:
        """获取机器鱼状态"""
        return self._last_state
    
    def _start_monitoring(self):
        """启动状态监控线程"""
        self._stop_monitoring = False
        self._monitoring_thread = threading.Thread(target=self._monitoring_loop)
        self._monitoring_thread.daemon = True
        self._monitoring_thread.start()
    
    def _monitoring_loop(self):
        """状态监控循环"""
        while not self._stop_monitoring and self._connected:
            try:
                # 获取位置信息
                position_cmd = f"""
export ROS_MASTER_URI={self.ros_master_uri} && 
rostopic echo -n 1 /fish/position
"""
                stdin, stdout, stderr = self.ssh_client.exec_command(position_cmd)
                position_data = stdout.read().decode('utf-8')
                
                # 获取姿态信息
                orientation_cmd = f"""
export ROS_MASTER_URI={self.ros_master_uri} && 
rostopic echo -n 1 /fish/orientation
"""
                stdin, stdout, stderr = self.ssh_client.exec_command(orientation_cmd)
                orientation_data = stdout.read().decode('utf-8')
                
                # 解析数据并更新状态
                self._parse_and_update_state(position_data, orientation_data)
                
                time.sleep(0.1)  # 10Hz更新频率
                
            except Exception as e:
                print(f"状态监控异常: {e}")
                time.sleep(1.0)
    
    def _parse_and_update_state(self, position_data: str, orientation_data: str):
        """解析并更新状态数据"""
        try:
            # 这里简化处理，实际应该解析YAML格式的ROS消息
            # 为演示目的，使用模拟数据
            import random
            
            state = FishState()
            state.position = {
                "x": random.uniform(-1, 1),
                "y": random.uniform(-1, 1), 
                "z": random.uniform(-0.5, 0.5)
            }
            state.orientation = {
                "roll": random.uniform(-0.2, 0.2),
                "pitch": random.uniform(-0.2, 0.2),
                "yaw": random.uniform(-3.14, 3.14)
            }
            state.timestamp = time.time()
            
            self._last_state = state
            
        except Exception as e:
            print(f"状态数据解析失败: {e}")
    
    def is_alive(self) -> bool:
        """检查连接是否存活"""
        if not self._connected or not self.ssh_client:
            return False
            
        try:
            # 发送简单命令测试连接
            stdin, stdout, stderr = self.ssh_client.exec_command("echo 'test'", timeout=5)
            result = stdout.read().decode('utf-8').strip()
            return result == "test"
            
        except Exception:
            return False
