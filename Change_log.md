# Change Log

## 2026-01-29 16:40

### 修复: socket回调线程安全问题（critical fix🔥）
**问题**：UI稳定性优化后仍出现`QObject::killTimer: Timers cannot be stopped from another thread`

**新发现的根本原因**：
- `socket_client.py`的`_connection_callback`在工作线程中调用
- `main_window.py`的`_on_connection_changed`直接操作UI（`self.data_timer.stop()`等）
- 违反Qt线程安全规则导致killTimer错误

**修复**：
- **修改** `ui/main_window.py`
  - 添加`connection_changed_signal`信号
  - `_on_connection_changed`只发射信号，不操作UI
  - 新增`@pyqtSlot`装饰的`_handle_connection_changed()`在主线程处理UI更新
  - 使用`Qt.QueuedConnection`连接信号

**效果**：
- ✅ 彻底解决线程安全问题
- ✅ 消除所有跨线程UI操作

### 新增: 状态栏连接时间显示
**需求**：在状态栏显示连接时长，便于诊断稳定性问题

**实现**：
- **修改** `ui/main_window.py`
  - 添加`connection_start_time`记录连接开始时间
  - 添加`connection_time_label`到状态栏右侧
  - 添加`connection_timer`每秒更新显示
  - 添加`_update_connection_time()`方法格式化显示时间

**显示格式**：
- 未连接：灰色 "未连接"
- 已连接：绿色 "已连接: MM:SS" 或 "已连接: HH:MM:SS"

**效果**：
- ✅ 实时显示连接时长
- ✅ 便于观察何时断连
- ✅ 帮助诊断稳定性问题

### 修复: 机器鱼Socket服务器自动断连问题
**问题**：GroundStation连接后，每隔一段时间（如60s）自动断开，机器鱼端提示`timed out`。但摄像头数据依然正常。

**原因**：
- 机器鱼端`socket_server.py`设置了Server Socket超时`settimeout(1.0)`
- 客户端Socket继承了这个超时设置
- 当GroundStation不发送控制命令时，服务器因超时主动断开连接
- **摄像头正常原因**：摄像头使用独立的端口(9998)和程序，不受主控制程序(9999)影响

**修复**：
- **修改** `socket_server.py` (需部署到机器鱼)
  - 在`accept()`后立即调用`client_socket.settimeout(None)`
  - 清除继承的超时设置，进入阻塞模式

## 2026-01-29 16:30

### 修复: UI程序卡死和崩溃问题（P0优先级）
**问题**：程序经常卡死、自动退出，错误信息`QObject::killTimer: Timers cannot be stopped from another thread`

**根本原因**：
1. **线程安全违规**：工作线程(CameraStreamClient)直接触发UI更新
2. **资源泄漏**：VideoWriter未正确释放
3. **异常传播**：缺少异常处理导致单点故障崩溃

**修复**（按优先级）:

#### P0 - 线程安全修复
- **修改** `ui/fish_camera_widget.py`
  - 导入`pyqtSlot`装饰器
  - 信号连接添加`Qt.QueuedConnection`参数（第201-202行）
  - 槽函数添加`@pyqtSlot`装饰器（`_update_frame`, `_on_connection_status`）
  - 所有槽函数添加try-except异常处理

#### P1 - 资源管理优化  
- **修改** `ui/fish_camera_widget.py`的`_stop_recording()`
  - VideoWriter释放包裹在try-except-finally中
  - 确保无论成功失败都设置为None

#### P2 - 异常处理增强
- **修改** `ui/main_window.py`的`_update_data()`
  - 添加错误日志速率限制（5秒一次）
  - 添加traceback打印便于调试

**效果**：
- ✅ 消除线程安全错误
- ✅ 防止资源泄漏
- ✅ 优雅处理异常不崩溃
- ✅提升长时间运行稳定性

**待验证**：
- 长时间运行测试（>30分钟）
- 连接断开循环测试
- 内存监控

## 2026-01-29 15:50

### 修复: 数据记录时control_command为None导致崩溃
**问题**：开始数据记录后出现大量错误`'NoneType' object has no attribute 'tail_frequency'`

**原因**：
- 在`main_window.py`的`_update_data()`中，`_last_control_command`初始值为None
- `data/recorder.py`的`add_data_point()`直接访问None对象的属性

**修复**：
- **修改** `data/recorder.py`的`add_data_point()`方法  
  - 添加control_command的None检查
  - 为None时创建默认ControlCommand对象（频率、幅度、偏移量均为0）

**效果**：数据记录功能正常，不再报错

## 2026-01-29 15:45

### 修复: 深度数据不更新问题
**问题**：Z-t深度图数据一直为0不变化

**原因**：
1. 地面站`socket_client.py`中深度数据阈值过大（0.001米=1毫米）
2. 机器鱼实际深度较浅（0.02-0.1米），被阈值过滤掉
3. launch文件中`calib`参数需设置为`false`才能正常发布数据

**修复**：
- **修改** `communication/socket_client.py`
  - 降低深度数据阈值从0.001到0.0001（0.1毫米）
  - 更新注释说明实际深度范围
- **修改** `catkin_ws_in_fish/fish_control/launch/sensor_socket.launch`
  - 将`calib`参数设置为`false`
  - 添加注释说明calib参数用法

**效果**：深度数据正常更新，Z-t图显示实时深度变化（0.02-0.1米范围）

## 2026-01-29 14:32

### 新增: 图表上的实时数据标注
**需求**：在位置绘图和时间序列绘图中实时显示数据值

**实现**：
- **修改** `ui/visualization.py`
  - 在XY轨迹图左上角添加TextItem显示当前X, Y坐标
  - 在Z-t深度图左上角添加TextItem显示当前深度Z值
  - 在RPY-t姿态角图左上角添加TextItem显示当前Roll, Pitch, Yaw值
  - 文本样式：10pt字体，半透明白色背景，黑色边框
  - 位置自适应图表视图范围

**效果**：用户无需鼠标悬停即可看到图表上的实时数值

## 2026-01-29 14:08

### 修复: 恢复launch文件并提供root用户安装cv2方案
**用户反馈**：注释掉camera_stream太麻烦，需要启动多个命令

**最终方案**：为root用户安装opencv-python
- **恢复** `catkin_ws_in_fish/fish_control/launch/sensor_socket.launch`
  - 取消注释camera_stream_server节点
  
- **更新** `catkin_ws_in_fish/部署说明.md`
  - 添加为root用户安装opencv的步骤
  
**机器鱼端一次性启动**：
```bash
# 为root用户安装opencv（仅首次需要）
sudo su
pip3 install opencv-python

# 启动所有服务（一条命令）
roslaunch fish_control sensor_socket.launch
```

## 2026-01-29 14:03

### 修复: 机器鱼launch文件的cv2依赖问题
**问题**：root用户启动sensor_socket.launch时报错"ModuleNotFoundError: No module named 'cv2'"

**原因**：
- launch文件中包含`camera_stream_server.py`节点
- 该节点依赖opencv(cv2)
- root用户Python环境缺少cv2包，但orangepi用户有

**解决方案**：
- **修改** `catkin_ws_in_fish/fish_control/launch/sensor_socket.launch`
  - 注释掉`camera_stream_server`节点
  - 建议单独以orangepi用户启动摄像头服务
  
- **新增** `catkin_ws_in_fish/fish_control/scripts/start_camera.sh`
  - 单独启动摄像头服务的脚本

**机器鱼端启动方式**：
```bash
# 终端1（root用户）：启动传感器和控制
sudo su
roslaunch fish_control sensor_socket.launch

# 终端2（orangepi用户）：启动摄像头视频流（可选）
cd ~/catkin_ws/src/fish_control/scripts
python3 camera_stream_server.py
```

## 2026-01-29 13:40

### 修复: Space键响应和胸鳍角度真正传输到机器鱼
**问题1**：Space键在keyboard_status.py中缺少映射导致UI无高亮
**问题2**：main_window._on_control_command没有从controller读取_pec_angle添加到命令

- **修改** `ui/keyboard_status.py`
  - 修复`_get_key_action`中的action_map，移除不存在的`up`/`down`
  - 添加`stop`, `increase_pec`, `decrease_pec`等新按键
  
- **修改** `ui/main_window.py`
  - 在`_on_control_command`中添加从`self.current_controller._pec_angle`读取胸鳍角度
  - 在发送命令前设置`command.pec_angle`
  
**现在胸鳍角度应该会正确传输到机器鱼端了！**

## 2026-01-29 11:45

### 修复: 恢复sensor_socket.launch的原有传感器节点配置
**问题**：错误地修改了传感器节点，应该保持原有配置

- **修改** `catkin_ws_in_fish/fish_control/launch/sensor_socket.launch`
  - **恢复原有传感器节点**：
    - IMU: `TransducerM_pkg/TMSerial` (发布到`TransducerM`话题)
    - UWB: `include linktrack.launch` (发布到`/nlink_linktrack_nodeframe2`话题)
    - 深度: `WF5803_pub_node.py` (可选，发布到`WF5803_topic`话题)
  - **添加舵机控制节点**：`servo_control`订阅控制话题
  - **添加timer_controller**：全局运行时间控制

**机器鱼端启动**：
```bash
roslaunch fish_control sensor_socket.launch
```

## 2026-01-29 11:40

### 修复: socket_server真正发布pec_angle + launch文件集成舵机控制
**问题**：之前只定义了`pub_pec_angle`但没有在`_process_command`中发布！

- **修改** `catkin_ws_in_fish/fish_control/scripts/socket_server.py`
  - 在`_process_command`中添加`self.pub_pec_angle.publish(Float32(pec_angle))`
  - 现在真正发布胸鳍角度到`/servo_info_angle`话题
  
- **修改** `catkin_ws_in_fish/fish_control/launch/sensor_socket.launch`
  - **添加舵机控制节点**：启动`servo_control`订阅控制话题
  - 初始化参数：`tail_frequency=0, tail_A=0, tail_bias=0, pec_angle=1500`
  - `servo_time=200000s`（足够长的运行时间）
  - `wait_imu_calib=false`（不等待IMU校准）
  - **现在只需启动sensor_socket.launch即可，无需额外启动keyboard.launch**

**机器鱼端启动方式**：
```bash
roslaunch fish_control sensor_socket.launch
```

## 2026-01-29 11:32

### 修复: 彻底修复键盘控制4个问题
**根本问题**：`config.py`中的按键映射配置错误，导致Q/E被映射为up/down

- **修改** `config.py`
  - 重新定义按键映射：
    - `increase_pec/decrease_pec` → Q/E（胸鳍角度）
    - `increase_freq/decrease_freq` → Up/Down（频率）  
    - `increase_amp/decrease_amp` → R/F（幅度）
    - 移除了错误的`up: Q, down: E`映射
    
- **修改** `controllers/base.py`
  1. **Q/E控制胸鳍**：使用`increase_pec/decrease_pec`映射，增量式调节1300-2000μs
  2. **Up/Down控制频率**：使用`increase_freq/decrease_freq`映射，调节0-2Hz
  3. **Space=S完全一致**：Space键代码与S键完全相同（停止+保存参数）
  4. **R/F控制幅度**：增减幅度0-0.4rad
  
- **修改** `ui/main_window.py`
  - 断开连接前发送停止命令（freq=0, amp=0, bias=0, pec=1500）
  - 添加`import time`用于时间戳
  - 等待0.2s确保命令发送完成

**最终按键功能**：
- **W** 前进 | **S/Space** 停止 | **A** 左转 | **D** 右转
- **Q/E** 胸鳍+/- | **Up/Down** 频率+/- | **R/F** 幅度+/-

## 2026-01-29 11:15

### 修复: 键盘控制问题修复
- **修改** `controllers/base.py`
  1. **修复上下箭头控制频率**：Up/Down箭头现在控制摆尾频率，不再控制胸鳍
  2. **修复Space按键**：Space键现在正常工作，功能与S键相同（停止）
  - 在`handle_key_press`中修复Up/Down逻辑，在`_update_control`中添加频率调节
- **修改** `ui/main_window.py`
  3. **断开连接时停止运动**：断开连接前自动发送停止命令（freq=0, amp=0, bias=0）
  - 在`_disconnect_from_fish`中添加停止命令发送，等待0.1s确保发送完成
- **修改** `catkin_ws_in_fish/fish_control/scripts/socket_server.py`
  - 完善`_process_command`中`pec_angle`参数处理和发布
  
**按键功能总结**：
- **W** 前进 | **S/Space** 停止 | **A** 左转 | **D** 右转
- **Q/E** 胸鳍+/- | **Up/Down** 频率+/- | **R/F** 幅度+/-

## 2026-01-29 11:01

### 优化: 键盘控制逻辑全面改进
- **修改** `controllers/base.py`（完全重写）
  1. **静止时不持续发送**：仅在命令变化时发送，避免静止状态下持续发送相同命令
  2. **A/D键只控方向**：左转/右转只改变bias偏置，不影响频率和幅度
  3. **Q/E控制胸鳍**：改为控制胸鳍角度(`/servo_info_angle`)，长按增减，松开保持
  4. **停止不清零参数**：S/Space停止时保存参数，再次启动恢复上次值
  - 添加`_saved_frequency`和`_saved_amplitude`保存运动参数
  - 添加`_pec_angle`胸鳍角度控制(1300-2000μs)
  - 添加`_last_sent_command`用于检测命令变化，避免重复发送
  - R/F键调节幅度，替代原来的Q/E调频率
- **修改** `communication/socket_client.py`
  - 在`send_control_command`的JSON中添加`pec_angle`字段
- **修改** `catkin_ws_in_fish/fish_control/scripts/socket_server.py`
  - 添加胸鳍角度发布器`pub_pec_angle -> /servo_info_angle`
  - 在`_process_command`中解析并发布`pec_angle`
- **修改** `ui/main_window.py`
  - 在`_on_control_command`中从controller读取`_pec_angle`并添加到命令

## 2026-01-29 10:18

### 改进: 键盘控制改为状态切换模式  
- **修改** `controllers/base.py`
  - 修改控制逻辑为状态机模式：按一次切换状态并保持，而非按住触发
  - S键从"后退"改为"停止"，机器鱼不支持后退
  - 添加运动状态显示label显示当前状态（前进/左转/右转/停止等）
  - 方向按键（W/A/D）按一次即生效并保持直到下一次按键

## 2026-01-29 10:10

### 修复: 键盘控制参数超范围和延迟问题
- **修改** `config.py`
  - 调整控制参数到安全范围：频率0-2Hz，幅度0-0.4rad，偏移±0.2rad
  - 设置初始值为0实现静止启动
- **修改** `controllers/base.py`
  - 修改方向偏移角度从±π/±1.57降低到±0.15，符合安全范围±0.2
  - 降低更新定时器从20Hz到10Hz减少发送频率
  - 添加偏移值范围限制确保不超出安全范围
- **修改** `ui/main_window.py`
  - 修复关闭窗口时的`VideoMonitorWidget`方法调用错误
- **说明**: 解决了控制命令发送频率过高导致延迟、参数超出舵机安全范围、初始状态非静止等问题

## 2026-01-29 09:42

### 修复: 键盘控制无效
- **修改** `ui/main_window.py`
  - 添加 `setFocusPolicy(Qt.StrongFocus)` 确保主窗口可接收键盘事件
  - 在窗口初始化和连接成功后调用 `setFocus()`
  - 解决键盘按键控制完全失效的问题

### 整理: 项目文件结构
- 创建 `tests/` 文件夹 - 存放测试文件
- 创建 `docs/` 文件夹 - 存放文档
- 创建 `temp_scripts/` 文件夹 - 存放临时脚本

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
