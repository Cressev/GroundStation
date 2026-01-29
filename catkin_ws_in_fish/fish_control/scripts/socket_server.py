#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼传感器数据Socket服务器
Fish Robot Sensor Data Socket Server

创建时间: 2026-01-28
说明: 此节点订阅机器鱼上的传感器话题(IMU、UWB、深度)，
      通过TCP Socket将数据实时推送给地面站，
      同时接收地面站的控制命令并发布到ROS。
"""

import rospy
import socket
import json
import threading
import time
import struct
from collections import deque

# 传感器消息类型
from TransducerM_pkg.msg import Imu
from nlink_parser.msg import LinktrackNodeframe2
from fish_control.msg import WF5803_MSG

# 控制命令消息类型
from std_msgs.msg import Float32


class FishSocketServer:
    """机器鱼Socket服务器，实现双向通信"""
    
    def __init__(self):
        rospy.init_node('fish_socket_server', anonymous=False)
        
        # 配置参数
        self.server_port = rospy.get_param('~server_port', 9999)
        self.data_rate = rospy.get_param('~data_rate', 50)  # Hz
        
        # 传感器数据缓存
        self.sensor_data = {
            'timestamp': 0.0,
            'imu': {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0},
            'uwb': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'vx': 0.0, 'vy': 0.0, 'vz': 0.0},
            'depth': {'raw_1': 0.0, 'smooth_1': 0.0, 'raw_2': 0.0, 'smooth_2': 0.0, 'fusion': 0.0}
        }
        self.data_lock = threading.Lock()
        
        # 客户端连接
        self.clients = []
        self.clients_lock = threading.Lock()
        
        # 订阅传感器话题
        self._init_subscribers()
        
        # 控制命令发布器 - 发布到舵机控制话题
        self.pub_amplitude = rospy.Publisher('/servo_info_A', Float32, queue_size=10)
        self.pub_frequency = rospy.Publisher('/servo_info_fre', Float32, queue_size=10)
        self.pub_bias = rospy.Publisher('/servo_info_bias', Float32, queue_size=10)
        self.pub_pec_angle = rospy.Publisher('/servo_info_angle', Float32, queue_size=10)  # 胸鳍
        
        # 启动Socket服务器
        self.server_socket = None
        self.running = False
        
        rospy.loginfo(f"FishSocketServer初始化完成，端口: {self.server_port}")
    
    def _init_subscribers(self):
        """初始化传感器订阅"""
        # IMU数据
        rospy.Subscriber('TransducerM', Imu, self._imu_callback, queue_size=1)
        
        # UWB位置数据
        rospy.Subscriber('/nlink_linktrack_nodeframe2', LinktrackNodeframe2, 
                        self._uwb_callback, queue_size=1)
        
        # 深度数据
        rospy.Subscriber('WF5803_topic', WF5803_MSG, self._depth_callback, queue_size=1)
        
        rospy.loginfo("传感器订阅初始化完成")
    
    def _imu_callback(self, msg):
        """IMU数据回调"""
        with self.data_lock:
            # 转换为弧度制
            self.sensor_data['imu'] = {
                'roll': msg.roll * 3.1415926 / 180.0,
                'pitch': msg.pitch * 3.1415926 / 180.0,
                'yaw': msg.yaw * 3.1415926 / 180.0
            }
            self.sensor_data['timestamp'] = time.time()
    
    def _uwb_callback(self, msg):
        """UWB位置数据回调"""
        with self.data_lock:
            self.sensor_data['uwb'] = {
                'x': msg.pos_3d[0],
                'y': msg.pos_3d[1],
                'z': msg.pos_3d[2],
                'vx': msg.vel_3d[0],
                'vy': msg.vel_3d[1],
                'vz': msg.vel_3d[2]
            }
            self.sensor_data['timestamp'] = time.time()
    
    def _depth_callback(self, msg):
        """深度数据回调"""
        with self.data_lock:
            self.sensor_data['depth'] = {
                'raw_1': msg.deep_raw_1,
                'smooth_1': msg.deep_smooth_1,
                'raw_2': msg.deep_raw_2,
                'smooth_2': msg.deep_smooth_2,
                'fusion': msg.deep_fusion
            }
            self.sensor_data['timestamp'] = time.time()
    
    def start(self):
        """启动服务器"""
        self.running = True
        
        # 创建服务器Socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.server_port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)  # 设置超时以便检查running标志
        
        rospy.loginfo(f"Socket服务器启动，监听端口: {self.server_port}")
        
        # 启动客户端接受线程
        accept_thread = threading.Thread(target=self._accept_clients)
        accept_thread.daemon = True
        accept_thread.start()
        
        # 启动数据广播线程
        broadcast_thread = threading.Thread(target=self._broadcast_data)
        broadcast_thread.daemon = True
        broadcast_thread.start()
        
        # 主线程处理ROS
        rospy.spin()
    
    def _accept_clients(self):
        """接受客户端连接"""
        while self.running and not rospy.is_shutdown():
            try:
                client_socket, client_addr = self.server_socket.accept()
                rospy.loginfo(f"客户端连接: {client_addr}")
                
                # 重要：清除客户端socket的超时设置，使其进入阻塞模式
                # 否则会继承ServerSocket的超时设置(1.0s)，导致不发送数据时连接断开
                client_socket.settimeout(None)
                
                with self.clients_lock:
                    self.clients.append(client_socket)
                
                # 启动客户端接收线程
                recv_thread = threading.Thread(target=self._receive_from_client, 
                                              args=(client_socket, client_addr))
                recv_thread.daemon = True
                recv_thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    rospy.logwarn(f"接受客户端异常: {e}")
    
    def _receive_from_client(self, client_socket, client_addr):
        """接收客户端发送的控制命令"""
        buffer = ""
        while self.running and not rospy.is_shutdown():
            try:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                
                # 解析JSON消息（以换行符分隔）
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        self._process_command(line.strip())
                        
            except Exception as e:
                rospy.logwarn(f"接收数据异常 {client_addr}: {e}")
                break
        
        # 清理断开的客户端
        with self.clients_lock:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
        
        try:
            client_socket.close()
        except:
            pass
        
        rospy.loginfo(f"客户端断开: {client_addr}")
    
    def _process_command(self, json_str):
        """处理控制命令"""
        try:
            cmd = json.loads(json_str)
            
            if cmd.get('type') == 'control':
                # 提取控制参数
                tail_frequency = cmd.get('tail_frequency', 0.0)
                tail_amplitude = cmd.get('tail_amplitude', 0.0)
                tail_offset = cmd.get('tail_offset', 0.0)
                pec_angle = cmd.get('pec_angle', 1500)  # 胸鳍角度
                
                # 发布到舵机控制话题
                self.pub_frequency.publish(Float32(tail_frequency))
                self.pub_amplitude.publish(Float32(tail_amplitude))
                self.pub_bias.publish(Float32(tail_offset))
                self.pub_pec_angle.publish(Float32(pec_angle))  # 发布胸鳍角度
                
                rospy.loginfo(f"控制命令: freq={tail_frequency:.2f}Hz, amp={tail_amplitude:.2f}rad, bias={tail_offset:.2f}rad, pec={pec_angle}μs")
                
        except json.JSONDecodeError as e:
            rospy.logwarn(f"JSON解析失败: {e}")
        except Exception as e:
            rospy.logwarn(f"处理命令异常: {e}")
    
    def _broadcast_data(self):
        """广播传感器数据给所有客户端"""
        rate = rospy.Rate(self.data_rate)
        
        while self.running and not rospy.is_shutdown():
            try:
                # 获取当前传感器数据
                with self.data_lock:
                    data = self.sensor_data.copy()
                
                # 构造JSON消息
                json_data = json.dumps(data) + '\n'
                encoded_data = json_data.encode('utf-8')
                
                # 发送给所有客户端
                with self.clients_lock:
                    dead_clients = []
                    for client in self.clients:
                        try:
                            client.sendall(encoded_data)
                        except Exception as e:
                            dead_clients.append(client)
                    
                    # 移除断开的客户端
                    for client in dead_clients:
                        self.clients.remove(client)
                        try:
                            client.close()
                        except:
                            pass
                
                rate.sleep()
                
            except Exception as e:
                rospy.logwarn(f"广播数据异常: {e}")
    
    def stop(self):
        """停止服务器"""
        self.running = False
        
        with self.clients_lock:
            for client in self.clients:
                try:
                    client.close()
                except:
                    pass
            self.clients.clear()
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        rospy.loginfo("Socket服务器已停止")


def main():
    server = FishSocketServer()
    try:
        server.start()
    except rospy.ROSInterruptException:
        pass
    finally:
        server.stop()


if __name__ == '__main__':
    main()
