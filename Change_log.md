# Change Log

## 2026-01-29 09:10

### 改进: 机载相机UI统一与录制功能
- **修改** `ui/fish_camera_widget.py`
  - UI布局与外部监控保持一致
  - 添加视频录制功能
  - 开始录制/停止录制按钮
  - 录制完成后选择保存目录
  - 显示录制状态和帧数统计

## 2026-01-29 09:00

### 修复: ROS launch参数冲突
- **修改** `catkin_ws_in_fish/camera_stream_server.py`
  - 使用 `rospy.get_param()` 读取ROS参数
  - 兼容ROS launch和直接运行两种方式
  - 修复argparse与ROS参数冲突
- **修改** `catkin_ws_in_fish/部署说明.md`
  - 添加文件格式转换步骤（Windows→Linux）

## 2026-01-29 08:45

### 新功能: 视频监控双摄像头
- **新增** `ui/fish_camera_widget.py` - 机载相机显示组件
  - Socket视频流接收
  - 实时视频显示
  - 连接状态控制
- **修改** `ui/video_display.py` 
  - 添加 `VideoMonitorWidget` 包装类
  - 两个标签页：外部监控/机载相机
- **修改** `ui/main_window.py`
  - 使用 `VideoMonitorWidget` 替代原有单一组件
- **新增** `机器鱼端代码/camera_stream_server.py`
  - 鱼眼摄像头视频流服务器
  - JPEG编码，TCP传输
  - 命令行参数支持
- **新增** `机器鱼端代码/camera_stream.launch` - ROS启动文件
- **新增** `机器鱼端代码/部署说明.md` - 部署指南

**技术细节**:
- 独立Socket连接（端口9998）
- JPEG编码（质量80%）
- 640x480@20FPS
- TCP_NODELAY减少延迟
- 预估延迟150-250ms

## 2026-01-29 00:01

### 修复: 姿态角方向统一
- **修改** `ui/visualization.py` 中的 `_update_attitude_visualization` 函数
  - 反转俯仰角(pitch)和偏航角(yaw)方向
  - 使3D显示与现实姿态一致
  - 横滚角(roll)保持不变

## 2026-01-28 23:58

### 修复: 胸鳍随鱼体旋转
- **修改** `ui/visualization.py`
  - 保存胸鳍对象引用
  - 在姿态更新时同步应用旋转变换

## 2026-01-28 23:57

### 改进: 添加胸鳍
- **修改** `ui/visualization.py`
  - 在鱼身两侧添加胸鳍
  - 三角形展开设计
  - 与身体颜色协调

## 2026-01-28 23:55

### 改进: 添加鱼形轮廓线
- **修改** `ui/visualization.py`
  - 启用边缘绘制（drawEdges=True）
  - 深褐色轮廓线增强立体感

## 2026-01-28 23:50

### 改进: 美化3D鱼形模型（兼容版）
- **修改** `ui/visualization.py`
  - 增加顶点数量使鱼身更流线型
  - 月牙形尾巴设计
  - 橙红色锦鲤配色
  - 不使用shader参数确保兼容性

## 2026-01-28

### 改进: 姿态可视化显示
- **修改** `ui/visualization.py`
  - **使用PyQtGraph OpenGL实现真正的3D姿态可视化**
  - 创建3D鱼形模型，支持roll/pitch/yaw三轴旋转
  - 添加坐标网格和坐标轴参考
  - 支持鼠标拖拽旋转3D视角

### 新增: 双向Socket通信功能
- **新增** `catkin_ws_in_fish/fish_control/scripts/socket_server.py` - 机器鱼端Socket服务器
  - 订阅IMU、UWB、深度传感器话题
  - 通过TCP以20-50Hz推送JSON格式传感器数据
  - 接收并解析地面站控制命令
- **新增** `catkin_ws_in_fish/fish_control/launch/sensor_socket.launch` - 启动文件
- **新增** `communication/socket_client.py` - 地面站Socket客户端
  - 实时接收传感器数据（20-50Hz）
  - 发送控制命令

### 修改: UI界面支持Socket连接
- **修改** `ui/main_window.py`
  - 添加端口输入框
  - 切换到使用SocketCommunication
  - 添加连接状态回调处理
- **修改** `config.py` - 添加 `SOCKET_PORT = 9999` 配置

### 修改: IP地址可编辑功能
- **修改** `ui/main_window.py` - 添加IP地址输入框，用户可修改后点击连接
- **修改** `communication/ssh_ros.py` - 支持动态传入IP地址参数
