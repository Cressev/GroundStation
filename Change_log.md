# Change Log

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
