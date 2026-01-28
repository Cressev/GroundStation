# Change Log

## 2026-01-28

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
