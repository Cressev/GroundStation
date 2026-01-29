#!/bin/bash
# 机器鱼控制系统一键启动脚本
# 自动启动所有必需的ROS节点

echo "========================================="
echo "  机器鱼控制系统启动"
echo "========================================="
echo ""

# 检查ROS环境
if [ -z "$ROS_DISTRO" ]; then
    echo "错误: 未检测到ROS环境"
    echo "请先执行: source /opt/ros/noetic/setup.bash"
    exit 1
fi

# 启动所有节点
echo "1. 启动舵机控制节点..."
roslaunch fish_control keyboard.launch &
SERVO_PID=$!
sleep 3

echo ""
echo "2. 启动Socket通信服务器..."
rosrun fish_control socket_server.py &
SOCKET_PID=$!
sleep 2

echo ""  
echo "3. 启动摄像头流服务器..."
roslaunch fish_control camera_stream.launch &
CAMERA_PID=$!
sleep 2

echo ""
echo "========================================="
echo "  所有节点已启动！"
echo "========================================="
echo "进程ID："
echo "  - 舵机控制: $SERVO_PID"
echo "  - Socket通信: $SOCKET_PID"
echo "  - 摄像头流: $CAMERA_PID"
echo ""
echo "按 Ctrl+C 停止所有节点"
echo ""

# 等待中断信号
trap "echo ''; echo '正在关闭所有节点...'; kill $SERVO_PID $SOCKET_PID $CAMERA_PID 2>/dev/null; exit" INT TERM

# 保持脚本运行
wait
