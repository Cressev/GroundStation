#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼鱼眼摄像头视频流服务器
Camera Stream Server for Fish Robot

运行方式:
    roslaunch fish_control camera_stream.launch
    或
    python3 camera_stream_server.py
"""

import cv2
import socket
import struct
import time
import signal
import sys

# 尝试导入rospy（ROS环境）
try:
    import rospy
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    print("警告: rospy未找到，使用默认参数")


class CameraStreamServer:
    """机器鱼鱼眼摄像头视频流服务器"""
    
    def __init__(self, port=9998, camera_index=0, width=640, height=480, fps=30, quality=80):
        """
        初始化视频流服务器
        
        Args:
            port: 服务器监听端口
            camera_index: 摄像头设备索引
            width: 视频宽度
            height: 视频高度
            fps: 目标帧率
            quality: JPEG质量 (1-100)
        """
        self.port = port
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.running = False
        
        # 初始化摄像头
        self.camera = None
        self.server_socket = None
        
    def init_camera(self):
        """初始化摄像头"""
        print(f"正在打开摄像头 {self.camera_index}...")
        self.camera = cv2.VideoCapture(self.camera_index)
        
        if not self.camera.isOpened():
            print(f"✗ 无法打开摄像头 {self.camera_index}")
            return False
        
        # 设置摄像头参数
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.camera.set(cv2.CAP_PROP_FPS, self.fps)
        
        # 读取实际参数
        actual_width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = int(self.camera.get(cv2.CAP_PROP_FPS))
        
        print(f"✓ 摄像头初始化成功")
        print(f"  分辨率: {actual_width}x{actual_height}")
        print(f"  帧率: {actual_fps} FPS")
        print(f"  JPEG质量: {self.quality}%")
        
        return True
        
    def start(self):
        """启动视频流服务"""
        if not self.init_camera():
            return
        
        # 创建Socket服务器
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(1)
            print(f"✓ 视频流服务器启动在端口 {self.port}")
            print("等待地面站连接...")
            
            self.running = True
            
            while self.running:
                try:
                    # 等待连接
                    conn, addr = self.server_socket.accept()
                    print(f"✓ 地面站已连接: {addr}")
                    
                    # 发送视频流
                    self._stream_video(conn)
                    
                except KeyboardInterrupt:
                    print("\n收到中断信号，正在关闭...")
                    break
                except Exception as e:
                    print(f"连接异常: {e}")
                    
        except Exception as e:
            print(f"✗ 服务器启动失败: {e}")
        finally:
            self.stop()
            
    def _stream_video(self, conn):
        """向客户端发送视频流"""
        frame_count = 0
        start_time = time.time()
        
        # 设置TCP_NODELAY减少延迟
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        try:
            while self.running:
                # 读取帧
                ret, frame = self.camera.read()
                if not ret:
                    print("✗ 读取摄像头失败")
                    break
                
                # JPEG压缩
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
                ret, img_encoded = cv2.imencode('.jpg', frame, encode_param)
                
                if not ret:
                    print("✗ JPEG编码失败")
                    continue
                
                # 转换为字节
                data = img_encoded.tobytes()
                size = len(data)
                
                try:
                    # 发送帧大小 (4字节，网络字节序)
                    conn.sendall(struct.pack("!I", size))
                    # 发送帧数据
                    conn.sendall(data)
                    
                    frame_count += 1
                    
                    # 每100帧打印一次统计
                    if frame_count % 100 == 0:
                        elapsed = time.time() - start_time
                        actual_fps = frame_count / elapsed
                        avg_size = size / 1024  # KB
                        print(f"已发送 {frame_count} 帧, 实际帧率: {actual_fps:.1f} FPS, 平均大小: {avg_size:.1f} KB")
                        
                except (BrokenPipeError, ConnectionResetError):
                    print("地面站断开连接")
                    break
                    
                # 控制帧率
                time.sleep(1.0 / self.fps)
                
        except Exception as e:
            print(f"流传输错误: {e}")
        finally:
            conn.close()
            print(f"连接关闭，共发送 {frame_count} 帧")
            
    def stop(self):
        """停止服务"""
        self.running = False
        
        if self.camera:
            self.camera.release()
            print("摄像头已释放")
            
        if self.server_socket:
            self.server_socket.close()
            print("服务器已关闭")


def signal_handler(sig, frame):
    """处理Ctrl+C信号"""
    print('\n收到中断信号，正在退出...')
    sys.exit(0)


if __name__ == "__main__":
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    
    print("=" * 50)
    print("机器鱼鱼眼摄像头视频流服务器")
    print("=" * 50)
    
    # 读取参数
    if ROS_AVAILABLE:
        # 从ROS参数服务器读取
        rospy.init_node('camera_stream_server', anonymous=False)
        
        port = rospy.get_param('~port', 9998)
        camera_index = rospy.get_param('~camera', 0)
        width = rospy.get_param('~width', 640)
        height = rospy.get_param('~height', 480)
        fps = rospy.get_param('~fps', 20)
        quality = rospy.get_param('~quality', 80)
        
        print(f"使用ROS参数:")
        print(f"  port={port}, camera={camera_index}")
        print(f"  resolution={width}x{height}, fps={fps}, quality={quality}")
    else:
        # 使用命令行参数（非ROS环境）
        import argparse
        parser = argparse.ArgumentParser(description='机器鱼鱼眼摄像头视频流服务器')
        parser.add_argument('--port', type=int, default=9998, help='服务器端口 (默认: 9998)')
        parser.add_argument('--camera', type=int, default=0, help='摄像头索引 (默认: 0)')
        parser.add_argument('--width', type=int, default=640, help='视频宽度 (默认: 640)')
        parser.add_argument('--height', type=int, default=480, help='视频高度 (默认: 480)')
        parser.add_argument('--fps', type=int, default=20, help='目标帧率 (默认: 20)')
        parser.add_argument('--quality', type=int, default=80, help='JPEG质量 1-100 (默认: 80)')
        
        args = parser.parse_args()
        
        port = args.port
        camera_index = args.camera
        width = args.width
        height = args.height
        fps = args.fps
        quality = args.quality
    
    # 创建并启动服务器
    server = CameraStreamServer(
        port=port,
        camera_index=camera_index,
        width=width,
        height=height,
        fps=fps,
        quality=quality
    )
    
    server.start()
