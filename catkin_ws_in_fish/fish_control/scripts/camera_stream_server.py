#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼鱼眼摄像头视频流服务器
Camera Stream Server for Fish Robot

架构:
  - 摄像头始终以高分辨率高帧率采集 (MJPG, 默认1280x960@30)
  - 实时流: 缩小到低分辨率低帧率 (默认640x480@20) 经TCP发给地面站, 省Wi-Fi带宽
  - 录制: 地面站发送 REC_START/REC_STOP 命令, 高分辨率高帧率视频直接保存在机上
    (record_dir), 录制数据不经过Wi-Fi, 不占用带宽

TCP协议 (客户端 -> 服务器):
    REC_START\\n  开始机上录制
    REC_STOP\\n   停止机上录制

TCP协议 (服务器 -> 客户端), 每条消息: [4字节长度][1字节类型][数据]
    类型0xFF: JPEG视频帧
    类型0xFE: UTF-8 JSON消息 (录制开始/保存完成通知)

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
import os
import json
import select
from datetime import datetime

# 尝试导入rospy（ROS环境）
try:
    import rospy
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    print("警告: rospy未找到，使用默认参数")

# 消息类型标识（长度字段之后的第一个字节）
MSG_JPEG = 0xFF   # JPEG视频帧
MSG_TEXT = 0xFE   # UTF-8 JSON消息


class CameraStreamServer:
    """机器鱼鱼眼摄像头视频流服务器"""

    def __init__(self, port=9998, camera_index=0,
                 width=1280, height=960, fps=30,              # 采集(高分辨率高帧率)
                 stream_width=640, stream_height=480,         # 实时流缩放目标
                 stream_fps=15, quality=80,                   # 实时流帧率与JPEG质量
                 record_dir="/home/orangepi/catkin_ws/src/fish_control/data/video/"):
        """
        初始化视频流服务器

        Args:
            port: 服务器监听端口
            camera_index: 摄像头设备索引
            width/height/fps: 摄像头采集参数(高分辨率高帧率, 机上录制用)
            stream_width/stream_height/stream_fps: 实时流缩放分辨率与帧率(低清省带宽)
            quality: 实时流JPEG质量 (1-100)
            record_dir: 机上录制视频保存目录
        """
        self.port = port
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.stream_width = stream_width
        self.stream_height = stream_height
        self.stream_fps = stream_fps
        self.quality = quality
        self.record_dir = record_dir
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
        # MJPG压缩格式：默认YUYV未压缩格式在高分辨率下帧率极低(1080p仅5fps)
        self.camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.camera.set(cv2.CAP_PROP_FPS, self.fps)

        # 读取实际参数
        actual_width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = int(self.camera.get(cv2.CAP_PROP_FPS))
        actual_fourcc = int(self.camera.get(cv2.CAP_PROP_FOURCC))
        fourcc_str = "".join(chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4))

        print(f"✓ 摄像头初始化成功")
        print(f"  采集分辨率: {actual_width}x{actual_height}")
        print(f"  采集帧率: {actual_fps} FPS")
        print(f"  像素格式: {fourcc_str}")
        print(f"  实时流: {self.stream_width}x{self.stream_height}@{self.stream_fps}fps 质量{self.quality}")
        print(f"  机上录制: {self.fps}FPS -> {self.record_dir}")

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

    def _send_text(self, conn, obj):
        """发送JSON文本消息给客户端"""
        try:
            data = json.dumps(obj).encode('utf-8')
            conn.sendall(struct.pack("!IB", len(data) + 1, MSG_TEXT) + data)
        except OSError:
            pass

    def _stream_video(self, conn):
        """向客户端发送视频流, 同时处理机上录制命令"""
        frame_interval = 1.0 / self.fps
        stream_interval = 1.0 / self.stream_fps
        last_stream_time = 0.0
        recv_buf = b''
        writer = None           # 机上录制VideoWriter (None=未在录制)
        rec_info = None         # 机上录制信息

        # 设置TCP_NODELAY减少延迟
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        try:
            while self.running:
                frame_start = time.time()

                # 非阻塞轮询地面站命令 (REC_START/REC_STOP)
                readable, _, _ = select.select([conn], [], [], 0)
                if readable:
                    try:
                        recv_buf += conn.recv(4096)
                    except (ConnectionResetError, OSError):
                        break
                    while b'\n' in recv_buf:
                        line, recv_buf = recv_buf.split(b'\n', 1)
                        cmd = line.decode('utf-8', 'ignore').strip().upper()
                        if cmd:
                            # 简化: 命令处理需要conn发回执, 内联处理
                            if cmd == "REC_START" and writer is None:
                                os.makedirs(self.record_dir, exist_ok=True)
                                path = os.path.join(
                                    self.record_dir,
                                    f"fish_camera_{datetime.now().strftime('%Y%m%d_%H%M%S')}.avi")
                                writer = cv2.VideoWriter(
                                    path, cv2.VideoWriter_fourcc(*'XVID'),
                                    self.fps, (self.width, self.height))
                                if not writer.isOpened():
                                    # XVID不可用时退回MJPG容器
                                    writer = cv2.VideoWriter(
                                        path, cv2.VideoWriter_fourcc(*'MJPG'),
                                        self.fps, (self.width, self.height))
                                if writer.isOpened():
                                    rec_info = {"path": path, "frames": 0,
                                                "start": time.time()}
                                    print(f"✓ 开始机上录制: {path}")
                                    self._send_text(conn, {"event": "rec_started",
                                                           "file": path})
                                else:
                                    print("✗ 机上录制启动失败: VideoWriter无法打开")
                                    writer = None
                            elif cmd == "REC_STOP" and writer is not None:
                                writer.release()
                                duration = time.time() - rec_info["start"]
                                print(f"✓ 机上录制完成: {rec_info['path']} "
                                      f"({rec_info['frames']}帧, {duration:.1f}秒)")
                                self._send_text(conn, {
                                    "event": "rec_saved",
                                    "file": rec_info["path"],
                                    "frames": rec_info["frames"],
                                    "duration": round(duration, 1)})
                                writer = None
                                rec_info = None

                # 读取帧
                ret, frame = self.camera.read()
                if not ret:
                    print("✗ 读取摄像头失败")
                    break

                # 机上录制: 写入全分辨率帧 (鱼眼倒装, 旋转180°与地面站看到的一致)
                if writer is not None:
                    writer.write(cv2.rotate(frame, cv2.ROTATE_180))
                    rec_info["frames"] += 1

                # 实时流: 按stream_fps节流, 缩小后JPEG发送
                now = time.time()
                if now - last_stream_time >= stream_interval:
                    last_stream_time = now
                    small = cv2.resize(frame, (self.stream_width, self.stream_height))
                    ret, img_encoded = cv2.imencode(
                        '.jpg', small, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
                    if ret:
                        data = img_encoded.tobytes()
                        try:
                            conn.sendall(struct.pack("!IB", len(data) + 1, MSG_JPEG) + data)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            print("地面站断开连接")
                            break

                # 控制帧率：只休眠本帧剩余的时间预算，避免叠加额外延迟
                elapsed = time.time() - frame_start
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)

        except Exception as e:
            print(f"流传输错误: {e}")
        finally:
            # 连接断开时如仍在录制, 自动保存
            if writer is not None:
                writer.release()
                duration = time.time() - rec_info["start"]
                print(f"连接断开, 机上录制已自动保存: {rec_info['path']} "
                      f"({rec_info['frames']}帧, {duration:.1f}秒)")
            conn.close()
            print("连接关闭")

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
        width = rospy.get_param('~width', 1280)
        height = rospy.get_param('~height', 960)
        fps = rospy.get_param('~fps', 30)
        stream_width = rospy.get_param('~stream_width', 640)
        stream_height = rospy.get_param('~stream_height', 480)
        stream_fps = rospy.get_param('~stream_fps', 20)
        quality = rospy.get_param('~quality', 80)
        record_dir = rospy.get_param(
            '~record_dir', '/home/orangepi/catkin_ws/src/fish_control/data/video/')
    else:
        # 使用命令行参数（非ROS环境）
        import argparse
        parser = argparse.ArgumentParser(description='机器鱼鱼眼摄像头视频流服务器')
        parser.add_argument('--port', type=int, default=9998, help='服务器端口 (默认: 9998)')
        parser.add_argument('--camera', type=int, default=0, help='摄像头索引 (默认: 0)')
        parser.add_argument('--width', type=int, default=1280, help='采集宽度 (默认: 1280)')
        parser.add_argument('--height', type=int, default=960, help='采集高度 (默认: 960)')
        parser.add_argument('--fps', type=int, default=30, help='采集帧率 (默认: 30)')
        parser.add_argument('--stream-width', type=int, default=640, help='实时流宽度')
        parser.add_argument('--stream-height', type=int, default=480, help='实时流高度')
        parser.add_argument('--stream-fps', type=int, default=15, help='实时流帧率')
        parser.add_argument('--quality', type=int, default=80, help='实时流JPEG质量 1-100')
        parser.add_argument('--record-dir', type=str,
                            default='/home/orangepi/catkin_ws/src/fish_control/data/video/',
                            help='机上录制保存目录')
        args = parser.parse_args()

        port = args.port
        camera_index = args.camera
        width = args.width
        height = args.height
        fps = args.fps
        stream_width = args.stream_width
        stream_height = args.stream_height
        stream_fps = args.stream_fps
        quality = args.quality
        record_dir = args.record_dir

    # 创建并启动服务器
    server = CameraStreamServer(
        port=port,
        camera_index=camera_index,
        width=width,
        height=height,
        fps=fps,
        stream_width=stream_width,
        stream_height=stream_height,
        stream_fps=stream_fps,
        quality=quality,
        record_dir=record_dir
    )

    server.start()
