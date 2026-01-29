#!/bin/bash
# 机器鱼端单独启动摄像头视频流服务
# 使用orangepi用户运行，避免root用户cv2依赖问题

cd ~/catkin_ws/src/fish_control/scripts
python3 camera_stream_server.py
