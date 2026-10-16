# Change Log

## 2026-10-17

### Xbox 扳机全量程修复与紧停震动反馈

- 时间：2026-10-17 00:23。
- 修复 XInput 扳机字段误用有符号 `BYTE` 的问题：旧逻辑在原始值超过 127 后把 128～255 解释成负数，表现为 0→50% 后突变到 -50%→0；现改用 `ctypes.c_ubyte`，LT/RT 全行程连续映射 0～100%。
- 增加 `XInputSetState` 双电机震动输出；按 X 或 B 紧急停尾时，当前手柄以 75%/100% 强度短震 250 ms，由独立单次定时器自动停止，不阻塞 50 Hz 控制循环。
- 手柄断连仍立即停尾，但因设备已经离线不尝试震动；震动失败也不会阻塞或削弱紧停命令。
- 新增扳机 `0/127/128/255` 边界和 X/B 震动启停回归测试；本机 `xinput1_4.dll` 对 1 号手柄的震动启动与停止调用均返回成功。

### Xbox 后半圆保持与跨侧偏置平滑

- 时间：2026-10-17 00:03。
- 将左摇杆中心死区和后半圆拆成独立状态：只有进入中心死区才触发平滑停止；进入后半圆后保持越过边界前一刻的尾鳍频率、摆幅、偏置、LT 包络和启停进度。
- 在后半圆内仍允许 Y/A/RT 独立调节胸鳍，不让尾鳍保持逻辑阻塞胸鳍操作。
- 尾鳍偏置增加变化率限制；从前半圆最左侧沿后半圆转到最右侧并重新进入前半圆时，完整左右跨度在两个当前尾摆周期内连续完成，不发生偏置突变。
- 新增后半圆保持和跨侧过渡回归测试，Xbox 控制模型共 9 项测试通过；真实手柄、网络和鱼体执行器闭环仍待现场验证。

## 2026-10-16

### Xbox 连续控制与双周期平滑安全停机

- 时间：2026-10-16 17:59。
- 双尾鱼控制方式新增“Xbox 控制”，Windows 端直接使用 XInput，不增加 pygame 等运行依赖。
- 左摇杆只接受前半圆并连续控制方向，后半圆不倒退；LT 在普通与加速频率/摆幅端点间连续插值。
- 尾鳍启动、LT 加速和松杆停止都按两个摆动周期平滑变化；X/B 与手柄断开绕过平滑，先发送零摆幅帧再撤销总控制。
- Y/A 以 `μs/s` 匀速调节胸鳍，RT 连续提高调节速度；页面显示 PWM 与 0–180°指令估算角。
- UI 可配置普通/加速频率和摆幅、最大转向量、基础偏置、相位差、死区、胸鳍范围与两档调节速度，参数保存到 `xbox_params.json`。
- 修正通用控制启用流程：控制器激活失败时不再误把总控制显示为已启用。
- 新增 8 项 Xbox 模型/紧停/断连测试和 UI 接入测试；当前 XInput DLL 加载成功，但测试时手柄未处于可检测状态，真实手柄与鱼体闭环仍待现场验证。

## 2026-10-14

### 时间序列页按当前可见范围导出数据与 PNG

- 移除右侧“数据记录”标签页及主菜单中的旧持续记录入口；历史源码保留，
  没有删除。
- 时间序列页新增“保存数据”和“保存图像”；清除曲线、重置画布和两个保存按钮
  位于同一操作行，时间模式与窗口大小单独一行，窄画布下不会挤压。
- 深度图和姿态角图 X 轴双向同步。用户手动缩放/拖动后，导出仅包含当前
  可见时间区间的深度各通道与 Roll/Pitch/Yaw，不会把画布外历史一起保存。
- 文件对话框可直接选择 CSV 或 Excel (`.xlsx`) 并指定文件路径；PNG 导出只截取
  当前两张时序画布，不包含上方操作按钮。

### 纯显示改为机器鱼端原生单目采集

- pico 纯显示从 `2560×720` 双目横拼改为 UVC 原生 `1280×720` 单目档位，
  另一路画面不再进入采集、JPEG 编码和网络传输链路。
- “单目视频”页只显示这一路图像，电脑端顺时针转正后用 Gamma 2.0 提亮；
  协议仍兼容旧 `raw_sbs` 流，但只取第一目。
- 图像增强对比页复用同一单目帧，“自动”区域改为增强整帧；旧双目
  `1280×960` 画布的上半部处理只作为显式兼容选项保留。
- 测距代码和 `RANGE_ON` 切回 `1280×480` 标定尺寸的路径未删除；当前 UI 仍禁用
  测距入口，本次测试也不启动测距。
- 整链路实测收到 40 帧 `1280×720` 单目图，约 30.07 FPS、平均 195858 B/帧；
  Gamma 2.0 后平均亮度由 101.28 提到 155.03。测试结束已关相机，状态为 `ranging=false`。

## 2026-10-13

### 修正：深度坐标为向下正值并允许负 PID 增益

- 更正深度坐标：水面为 0，水下为正数且越深越大；默认目标由 -15 cm 改为 15 cm。
- 误差仍为“目标深度 - 当前深度”。由于胸鳍脉宽减小会促使下潜，默认使用正 PID 增益和
  `direction=-1`，即“目标更深时减小脉宽”。
- Kp/Ki/Kd 输入和参数加载范围由 0–1000 改为 -1000–1000，用户可以直接输入负增益；
  界面提示通常优先用输出方向选择极性，避免两次反转。
- 参数坐标标记升级为 `positive_down_v2`；旧参数加载时保留增益、中位和限幅，安全重置目标与方向。

## 2026-10-11

### 迁移：图像增强对比功能并入 dual-fish-stereo 最新基线

- 从 `wxy-image_enhence` 分支把图像增强对比功能整体移植到拉取的最新
  `feature/dual-fish-stereo` 基线上；基线侧的遥测、深度(cm)、滚动区、1:1 渲染、
  GET_STATE 等改动全部保留，无覆盖。
- `ui/main_window.py` 按新基线手工重新接线（导入、dual 分支挂载第三个标签页、
  `frame_received`/`connection_status` 信号连接、closeEvent 停止增强线程），写法与
  wxy 分支一致；新版 `StereoVideoClient` 信号签名未变，1280×960 画布协议未变，
  增强页"仅双目图区域（上半部）"选项继续有效。
- README/Change_log/`.gitignore`（权重与本地备份排除）同步合并。

## 2026-10-10

### 调整：图像增强改为左右对比布局

- 图像增强页由上下排列改为左侧原始画面、右侧增强画面，更适配竖向真实视频。
- 根据实测取消视频窗之间的可拖动分隔器，改为普通等宽水平布局，避免拖动时反复缩放视频造成明显卡顿。
- 视频显示由 `QLabel.setPixmap()` 改为自定义 `VideoCanvas.paintEvent()`；视频帧只在布局分配的画布矩形内等比例绘制，不再有 Pixmap 反向改变画布尺寸的路径。
- Mock 源状态中的长文件名不再参与控制网格的最小宽度计算，避免加载视频时扩宽增强页并带动画布和主窗口一起变大。
- 对比截图和 MP4 对比录像同步改为左原图、右增强图，界面与导出结果保持一致。

## 2026-10-07

### 接入：UIEC²-Net、U-shape Transformer 与 Ucolor

- 新增 `enhancers/` 统一适配层，三个模型都在增强线程中延迟加载，不阻塞 PyQt 主线程。
- UIEC²-Net 使用 320×240/目 PyTorch CUDA 推理；U-shape 使用 256×256/目，并让左右目
  共享输出归一化范围，避免双目亮度独立漂移。
- Ucolor 原 TensorFlow 2.4 CPU 模型转换为外部张量 ONNX，新增 GDCP 预处理与
  ONNX Runtime CUDA 推理；固定图像与原框架最大像素差 1、平均差 0.020。
- 模型失败时保留原图并在状态栏显示真实错误，后台线程继续运行；模型切换时释放旧模型。
- 修复 PyTorch 与 ONNX Runtime 同进程的 OpenMP、CUDA/cuDNN DLL 加载顺序冲突，验证
  Ucolor→UIEC²-Net、Ucolor→U-shape 切换均成功。
- 新增 `models/README.md` 和 `ref/convert_ucolor_to_onnx.py`，记录模型位置、校验值、转换、
  解压及 `fish_ui_gpu` 环境复现步骤；大权重和转换产物不提交 Git。
- RTX 5060 Laptop GPU 实测：UIEC²-Net Mock 约 30 FPS，U-shape 约 20.8 FPS；Ucolor
  单目约 3.2 FPS、双目约 1.8 FPS，首次加载约 35 秒。

## 2026-10-06

### 新增：双尾鱼图像增强上下对比页

- 新增 `ui/image_enhancement_widget.py`：原始画面和增强画面上下排列，使用可拖动分隔线。
- 复用双目测距页现有 9998 视频连接，不重复拉取网络视频流。
- 支持本地视频循环 Mock，便于不连接机器鱼时设计和验证 UI。
- 增强在线程中执行并只保留最新帧，显示输入/输出 FPS、单帧耗时和丢弃旧帧数。
- 内置水下综合增强、CLAHE、Gamma 和灰度世界白平衡，以及场景预设和高级参数。
- 支持单画面最大化、单帧截图、上下对比图保存和参数 JSON 导出。
- 新增上下对比 MP4 录像：原图/增强图严格同帧，独立编码线程写盘，停止后报告帧数、
  时长和录像队列丢帧，不阻塞 PyQt 主线程。
- `GROUNDSTATION_MOCK_VIDEO` 环境变量可在启动时自动播放指定视频并切到增强页。
- 重构算法选择层级：一级为传统图像增强、四个神经网络和不处理，传统方法下再选择
  综合增强、CLAHE、Gamma 或灰度世界白平衡；未接入的网络明确禁用并标记“待接入”。
- 传统高级参数按模式动态启用，示例预设只在水下综合增强中显示，避免无效参数造成误解。

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
