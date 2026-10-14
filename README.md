# 机器鱼地面站 GroundStation（PyQt5）

双版本机器鱼地面站：启动时选择鱼体版本，按版本加载对应的视频、通信与控制页面。

- **双尾双目鱼（dual，当前主攻）**：机载 pico RK3588S（ROS2 Humble）。视频/测距连
  pico 的 `pico_stereo depth_node` TCP 服务（9998，协议见下），控制命令发 pico 的
  `gs_bridge` TCP 服务（9999），gs_bridge 翻译成 `/fish/control/actuator_command`
  交给串口桥发 STM32。当前地面站固定使用**纯显示模式**，测距入口保留但禁用，不会发送
  `RANGE_ON`。纯显示时机器鱼端使用 UVC 原生 `1280×720` 单目档位，只采集、编码和发送
  一路摄像头；双目测距代码保留，今后需要时仍可切回标定尺寸。
- **单尾单目鱼（single，旧平台）**：机载 orangepi（ROS1）。视频连
  `camera_stream_server`（9998，机上录制），控制连 `socket_server`（9999，
  发布 /servo_info_*）。原功能不变。

## 快速启动

```bash
conda activate fish_ui_gpu
python main.py          # 先弹出版本选择对话框，选择后进入主窗口
```

`fish_ui_gpu` 是启用 UIEC²-Net、U-shape Transformer 和 Ucolor 的推荐环境；`qt5` 环境仍可
运行传统增强和其余地面站功能，但无法运行三个 CUDA 模型。

服务端启动方式见 `catkin_ws_in_fish/部署说明.md`（单尾鱼）与
`pico_stereo/USAGE.md` + `gs_bridge`（双尾鱼，由代理部署在 pico 上）。

## 文件清单（逐文件）

| 文件 | 说明 |
|---|---|
| `main.py` | 入口：高 DPI 设置 → 版本选择对话框 → 按变体构造 MainWindow |
| `config.py` | 全局配置：单尾鱼 IP/端口、`DUAL_FISH_CONFIG`（pico IP + 9999/9998 端口）、控制限幅（胸鳍 PWM 500–2500 μs）、键位映射、键盘默认参数 `KEYBOARD_CONTROL_DEFAULTS`（含相位差 1.57）、深度闭环安全默认参数 `DEPTH_CONTROL_DEFAULTS`、UI/视频/记录参数；`STEREO_RANGING_UI_ENABLED=False` 保证当前版本只显示、不启动测距，`STEREO_PREVIEW_LAYOUT="raw_single"` 标记原生单目流 |
| `ui/fish_variant_dialog.py` | **新增** 启动版本选择对话框（dual/single 卡片式选择） |
| `ui/connection_store.py` | **新增** 连接档案持久化（本地 connections.json 记录 备注+IP+端口，双尾鱼页面下拉直选） |
| `ui/heartbeat_light.py` | **新增** 心跳呼吸灯（状态栏左下角）：脉冲只由真实心跳发送事件驱动——通信层每成功发出一拍 ping 经 Qt 信号点亮、两拍间自然衰减，停发即沉暗，不做装饰性空闪；悬停显示累计拍数与最后时刻；断链转灰 |
| `ui/main_window.py` | 主窗口：按 `variant` 加载“单目视频”、图像增强页与深度页；主连接采用 `disconnected/connecting/connected/disconnecting` 状态机，视频和深度连接严格受主连接门闩控制；右侧栏只保留深度与按键状态，不再挂载旧数据记录页；控制总开关打开后锁定控制方式下拉框及菜单，断链先撤销发送权并安全停机；左/右侧栏首次默认 360/280 px，用户拖动宽度按鱼体版本保存并在下次启动恢复 |
| `ui/stereo_camera_widget.py` | 双尾鱼纯显示组件：`StereoVideoClient`（TCP 9998）+ `StereoFishCameraWidget`；接收 `1280×720` 原生单目 JPEG，在电脑端顺时针转正并做 Gamma 2.0 提亮；兼容旧 `raw_sbs` 双目流但只显示第一目；区分“线程启动”“TCP 已连接”“相机已确认开启”，按钮只由集中状态机刷新，快速重复点击和迟到回执不会反转状态；相机开关等待板端确认，含 GET_STATE、本地 MP4 和快照；测距按钮固定禁用，不发送 `RANGE_ON` |
| `ui/depth_panel.py` | 双尾鱼深度面板：`DepthTcpClient`（TCP 9999，接收 gs_bridge 深度推送）、实时深度、10 秒零点标定、CSV 记录；连接严格依赖主连接，区分连接中/已连接/断开中/错误，快速断开可取消未完成连接；主链断开时自动结束记录并保存到 `records/`。深度单位为 cm，数据源 IP 跟随本次主连接 |
| `ui/image_enhancement_widget.py` | 双尾鱼图像增强对比页：原图/增强图左右等宽显示，复用同一路 9998 单目视频帧且默认对整帧增强；一级选择传统方法/神经网络/不处理，传统方法下含综合增强、CLAHE、Gamma、白平衡；支持本地 Mock 视频、实时 FPS/延迟/丢帧统计、单画面放大、截图、左右对比 MP4 录像和参数导出 |
| `enhancers/__init__.py` | 神经网络增强器工厂：按选项延迟导入对应适配器，避免启动界面时立即占用 GPU |
| `enhancers/base.py` | 神经网络统一接口，以及单目/双目拆分、等比例补边和原尺寸恢复工具 |
| `enhancers/model_paths.py` | UIEC²-Net、U-shape 外部源码/权重和 Ucolor 本地 ONNX 路径检查；支持 `GROUNDSTATION_BASELINE_ROOT` 覆盖默认 baseline 目录 |
| `enhancers/uiec2_enhancer.py` | UIEC²-Net PyTorch/CUDA 适配器，320×240/目，左右目合为一个 batch 推理 |
| `enhancers/ushape_enhancer.py` | U-shape Transformer PyTorch/CUDA 适配器，256×256/目，双目共享输出归一化范围 |
| `enhancers/ucolor_enhancer.py` | Ucolor ONNX Runtime/CUDA 适配器，包含 GDCP 透射率图预处理和 TensorFlow 转换模型推理 |
| `ref/convert_ucolor_to_onnx.py` | 在旧 TensorFlow 环境中把 Ucolor 检查点转换成外部张量 ONNX zip，并替换 ONNX 不支持的 RGB→HSV 算子 |
| `models/README.md` | 大模型本地路径、SHA256、Ucolor 转换/解压步骤和数值对齐结果；实际权重由 `.gitignore` 排除 |
| `ui/fish_camera_widget.py` | 单尾鱼机载相机组件（TCP 9998 客户端 + 机上录制控制），仅 single 变体使用 |
| `ui/video_display.py` | 笔记本外接 USB 相机监控（VideoDisplayWidget + VideoMonitorWidget 容器），仅 single 变体使用 |
| `ui/visualization.py` | pyqtgraph 数据可视化（XY 轨迹/深度/姿态/实时朝向）；全局时间序列保留从最近一次“清除曲线”以来的完整数据，滑动窗口只筛选显示范围；两张时序图 X 轴同步，用户缩放/拖动后“保存数据”仅导出当前可见范围的深度各通道与 Roll/Pitch/Yaw，文件对话框可选 CSV 或 XLSX；“保存图像”将当前画布导出为 PNG；清除、重置、保存按钮在同一操作行 |
| `ui/keyboard_status.py` | 键盘按键状态面板与特殊功能键处理 |
| `ui/data_recording.py` | 历史持续记录控制面板源码，为保留旧功能未删除；当前主界面不再挂载，实际导出由时间序列页的按钮完成 |
| `controllers/base.py` | KeyboardController 等控制器：把键盘事件合成为 ControlCommand（频率/幅值/偏置/**相位差**/胸鳍脉宽）；参数栏含相位差旋钮（默认 1.57 rad，±6.282），并可直接输入 500–2500 μs 胸鳍脉宽后点击“设定”发送；输入期间不会被 100 ms 控制定时器回写，Q/E 增量调节继续保留 |
| `controllers/depth.py` | 双尾鱼地面站深度闭环：使用标定后 `fused` 深度运行 PID，PID 接管胸鳍但保留 W/A/D/S 尾鳍键盘控制；含独立启停、参数解锁、允许正负值的 Kp/Ki/Kd、正向目标深度、积分限幅、中位/最小/最大脉宽、数据超时和输出方向调节；只有总控制已启用时 PID 开关才可操作，切走控制器或断链会关闭 PID 并回中 |
| `communication/base.py` | 通信抽象基类（FishState/ControlCommand/FishCommunicationInterface） |
| `communication/socket_client.py` | 双尾/单尾 TCP 控制客户端（9999，JSON 行协议）：state 回推走状态回调（遥测 + IMU 欧拉角并入 FishState.orientation 实时驱动姿态图），depth 推送装入 FishState.depth 供时间序列图，兼容旧版单尾鱼组合格式 |
| `communication/ssh_ros.py` | SSH 执行 ROS 命令的辅助（旧链路备用） |
| `data/recorder.py` | 历史持续传感器/控制数据记录器（CSV + metadata），当前主界面不调用 |
| `utils/graphics_exporter.py` | 历史全图导出器，当前时间序列 PNG 导出改由 `ui/visualization.py` 实现 |
| `catkin_ws_in_fish/` | 单尾鱼（orangepi ROS1）机载脚本母本：`camera_stream_server.py`（9998 视频流+机上录制）、`socket_server.py`（9999 控制+传感器推送）、launch 与部署说明 |
| `tests/test_ui_state_machine.py` | 主连接、控制锁定、视频确认状态、失败重试、侧栏默认值与持久化的离线回归测试 |
| `tests/test_visualization_time_modes.py` | 全局历史不受滑动窗口截断、时间模式幂等、双图时间轴同步、可见范围筛选及 CSV/XLSX 文件输出的离线回归测试 |
| `tests/test_depth_controller.py` | PID 数学、参数锁、中位与限幅、方向切换、键盘并行控制和断流回中测试 |
| `docs/2026-10-13-ui-state-machine-design.md` | 本次 UI 状态机的状态、门闩、幂等规则和验证边界 |
| `docs/README.md` | docs 文档目录逐文件索引 |
| `Change_log.md` / `TODO.md` | 变更记录与待办 |
| `fps_compare/`、`records/`、`temp_scripts/`、`image.png` | 历史测试素材与一次性脚本（非运行依赖） |

## UI 状态机与安全交互

双尾鱼页面采用严格依赖关系：`主控制连接 → 视频/深度服务连接 → 摄像头确认开启 → 录制`。
下一级只能在上一级真实就绪后操作；主连接断开会自动撤销控制、锁定视频和深度页，并停止相关
记录。TCP 工作线程的 `running` 只表示线程生命周期，不再冒充“已经连接”。连接中再次点击断开
会设置取消标记；旧线程没有退出前不会启动第二次连接。

控制方式只有在总控制关闭时才能切换。总控制打开后，下拉框和控制菜单同时锁定；无论通过菜单
还是下拉框选择，界面与实际控制器都保持一致。重复连接、断开、启用、停用或选择同一控制器均
保持幂等。详细状态表见 `docs/2026-10-13-ui-state-machine-design.md`。

## 深度闭环控制

深度闭环只在启动时选择“双尾双目鱼”后出现，不会启动双目测距。反馈量来自控制连接
`9999` 已有的 WF5803 融合深度，并使用深度页面同一个零点：
`控制深度 = fused - zero_offset`，单位始终为 cm。**水面为 0，水下为正数，越深数值越大**；
例如目标深度 20 cm 应填写 `20 cm`。

操作顺序：

1. 先连接机器鱼，确认“深度”页面持续显示有效数值；需要相对水面控制时先完成零点标定。
2. 控制方式选择“深度控制”。W/A/D/S、Shift+W/A/D 仍控制尾鳍推进和转向。
3. 勾选“解锁参数调节”，填写目标深度、Kp/Ki/Kd、中位脉宽、最小/最大脉宽等，点击“应用并保存参数”。参数文件只保存在本机，不上传 Git。
4. 取消“解锁参数调节”可防止误触；再勾选总安全开关“启用控制”。
5. 最后勾选“启用深度 PID”。PID 开启期间胸鳍由闭环独占，Q/E 不生效；关闭 PID 后胸鳍回中，Q/E 恢复手动控制。

首次下水默认按“目标更深时减小脉宽”输出，目标 15 cm，Kp=20，Ki=Kd=0，中位 1500 μs，
输出限制 1300–1700 μs。若鱼体响应方向相反，先关闭 PID，再解锁参数，把“输出方向”改为
“目标更深时增大脉宽”。Kp/Ki/Kd 均允许输入负值；通常建议增益保持正值，只用“输出方向”
选择执行器极性，避免“负增益 + 反向输出”发生两次反转。深度数据超过 0.5 秒未更新时，控制器清空 PID 状态并把胸鳍回到中位；
地面站总安全开关关闭或通信断开时，原有停止链仍具有最高优先级。
旧版 `negative_down_v1` 或未记录坐标约定的 `depth_pid_params.json` 会在加载时安全迁移：保留 PID 增益与脉宽范围，但将目标恢复为 15 cm、输出方向恢复为“目标更深时减小脉宽”，防止旧的反向参数被继续使用。

## 双尾鱼 TCP 协议（pico 侧由 pico_stereo + gs_bridge 实现）

视频/测距（9998，depth_node）：

```
服务端->地面站: [4字节大端长度][1字节类型][数据]
  0xFF = JPEG：当前纯显示为 1280x720 原生单目帧；保留的测距模式为 1280x960 处理画布
  0xFE = UTF-8 JSON（{"type":"measurement","layout":"raw_single",...,"fps":..}
                     / {"type":"measurement","D":..,"Z":..,"X":..,"Y":..,"disp":..,"valid":..,"fps":..}
                     / {"type":"point_set","u":..,"v":..} / {"type":"pong"} / {"type":"error"}）
地面站->服务端: 文本行
  SET_POINT u v   点击测距（u,v 为左校正图像素坐标）
  RANGE_ON / RANGE_OFF   启动/停止板上测距程序（纯视频回传 <-> 测距模式）
  CAM_ON / CAM_OFF 开关板上摄像头（一键启动默认不开相机，板上回 {"type":"camera"} 确认）
  GET_STATE       查询板上真实状态（回 {"type":"node_state",...}，UI 连接时自动调用）
  PING            探活
```

**当前回传内容**（测距关闭时）：两路相机画面上下排布（各 640x480，canvas 640x960，
约 15~20 FPS，gamma 提亮），测点/视差/距离读数在点击"启动测距"后加入画布。

**保存视频**：视频页"保存视频"按钮开始录制（随视频流实时写帧），停止后弹出
文件对话框选择保存位置与文件名（**仅支持 mp4**，mp4v 编码；取消则存到
records/ 下按时间戳命名）。板上相机曝光/增益需在 v4l2-ctl 预设好
（depth_node 已自动设置，室内默认 exposure_absolute=1300 + gain=120）。

## 图像增强对比页

双尾鱼模式下中央区域新增第三个标签页 `图像增强对比`。页面把同一视频帧的原图和增强图
左右等宽排列，不提供可拖动分隔线；窗口尺寸变化时两侧自动同步调整。增强处理在独立线程
中进行，队列只保留最新帧；
处理速度低于采集速度时主动丢弃旧帧，优先保证实时预览延迟不会持续累积。

- 实时模式：复用 `StereoVideoClient.frame_received`，不会向 pico 再建立第二条 9998 连接。
- Mock 模式：页面内点击“加载 Mock 视频”，选择本地 mp4/avi/mov/mkv 并循环播放。
- 布局约束：左右视频窗固定等宽，使用自定义绘制画布而不是 `QLabel.setPixmap()`；画布只在
  布局已经分配的矩形内等比例绘图，视频原始分辨率不会参与页面尺寸计算。较长的状态文字
  和 Mock 文件名不会参与页面最小宽度计算，鼠标悬停可查看完整内容。
- 增强方法：传统图像增强、UIEC²-Net、U-shape Transformer、Ucolor、
  LightUcolorRetinex 或不处理。前三个开源网络已经接入并可选择；LightUcolorRetinex 在最终
  结构和权重确定前保持禁用。
- 传统模式：水下综合增强、CLAHE 局部对比度、Gamma 明暗校正和灰度世界白平衡。
  水下综合增强按“灰度世界→CLAHE→Gamma→饱和度→对比度”的固定顺序处理；单项模式
  只启用自身真正使用的高级参数。
- 参数：增强强度是所有已实现方法外层的原图混合比例；Gamma、对比度、饱和度和
  CLAHE 只属于传统方法。浑浊水体、清水、偏蓝绿色、低照度均明确标为“示例预设”，
  仅在水下综合增强中显示，尚未使用课题组真实水下数据完成标定。
- 处理区域：实时单目流默认处理整张画面；“仅旧双目画布上半部”只用于兼容历史 1280×960 素材。
- 输出：单画面放大/截图、左右对比截图、左右对比 MP4 录像、增强参数 JSON，以及
  输入/输出 FPS、处理耗时、丢弃旧帧数等实时指标。

“开始保存对比视频”会先要求选择 `.mp4` 路径；录像内容为严格同一时刻的原图在左、增强图
在右，并带 `ORIGINAL` / `ENHANCED` 标记。再次点击“停止并保存视频”后，后台线程会写完
录像队列并关闭文件，然后显示实际帧数、视频时长和录像队列丢帧数。编码使用 `mp4v`，
录像声明帧率取当前增强输出帧率且最高 25 FPS，避免增强处理略慢于输入时造成明显快放。

调试时也可以在启动前用环境变量指定 Mock 视频；程序会自动切到增强对比页：

```powershell
$env:GROUNDSTATION_MOCK_VIDEO = 'D:\桌面\1632b6b4313f804820195bfe22956b48.mp4'
python main.py
Remove-Item Env:GROUNDSTATION_MOCK_VIDEO
```

启动后选择“双尾双目鱼”。Mock 播放期间暂不显示 Pico 实时帧，点击“停止 Mock”后自动恢复
使用现有 Pico 单目视频流。`仅旧双目画布上半部（兼容）`用于 1280×960 历史测距画布，只增强上半部
左右校正图，保留下半部视差伪彩与测距叠加的原始含义。

### 三个开源网络的本机部署

默认从 `C:\Users\yiiixw\Documents\ChatGPT\图像增强\baseline` 读取 UIEC²-Net 与
U-shape 源码/权重；目录改变时，在启动前设置：

```powershell
$env:GROUNDSTATION_BASELINE_ROOT = '你的\baseline\绝对路径'
```

当前 `fish_ui_gpu` 由原 `pytorch` 环境克隆，保留 PyTorch 2.7.1+cu128，再安装 PyQt5、
pyqtgraph 与 ONNX Runtime。重建环境时使用下列顺序；ONNX Runtime GPU 构建与 CUDA 12.4
依赖必须同时固定，NumPy 固定 1.26.4 以兼容现有 SciPy：

```powershell
conda create -n fish_ui_gpu --clone pytorch
conda run -n fish_ui_gpu python -m pip install PyQt5==5.15.10 pyqtgraph==0.13.7
conda install -n fish_ui_gpu --override-channels -c defaults `
  'onnxruntime=1.22.2=py310h5bbf1a5_0_cuda' 'cuda-cupti=12.4.127' 'numpy=1.26.4' -y
conda install -n fish_ui_gpu -c conda-forge nomkl 'libblas=*=*openblas' -y
conda list -n fish_ui_gpu llvm-openmp   # 若能列出该包，再执行下一行
conda remove -n fish_ui_gpu llvm-openmp -y
```

最后两步用于避免 ONNX Runtime 的 `libomp.dll` 与 PyTorch 的 `libiomp5md.dll` 同进程冲突。
代码还会在 Ucolor 会话创建前预载 PyTorch CUDA/cuDNN，确保先选 Ucolor、后切换 PyTorch
模型也不会被 Conda CUDA DLL 遮蔽。不要用 `KMP_DUPLICATE_LIB_OK=TRUE` 绕过冲突。

本机 RTX 5060 Laptop GPU、Mock 视频实测如下；这是吞吐参考，不是固定承诺：

| 方法 | 内部输入 | 实测 |
|---|---|---|
| UIEC²-Net | 320×240/目，双目 batch | Mock 约 30 FPS，单次约 23 ms |
| U-shape Transformer | 256×256/目，双目 batch | Mock 约 20.8 FPS，单次约 51 ms |
| Ucolor | 256×256/目，固定 batch=1 | 单目约 305–310 ms（约 3.2 FPS）；双目约 558 ms（约 1.8 FPS） |

Ucolor 首次选择需约 35 秒完成 600 MB 权重加载和 cuDNN 预热，期间状态栏显示“正在加载”；
加载完成前界面保持响应。增强线程永远只保留最新帧，慢模型不会把旧帧排成长队。

控制（9999，gs_bridge）：

```
地面站->板上: {"type":"control","tail_frequency":Hz,"tail_amplitude":rad,
              "tail_offset":rad,"pec_angle":us}   （JSON 行）
板上->地面站: {"type":"state","ack_count":N,"last_command":{...},
              "telemetry":{"cpu_percent":..,"soc_temp_c":..,"mem_used_mb":..,
              "mem_total_mb":..,"cpu_freq_mhz":..},
              "imu":{"roll":rad,"pitch":rad,"yaw":rad}}（2Hz 回推，遥测供底栏、
              IMU 供姿态图/时间序列；四元数由 gs_bridge 转欧拉角）
              {"type":"depth","raw_1":..,"filtered_1":..,"fused":..}（10Hz，订阅
              /fish/sensors/depth 转发，供深度面板显示/记录）
```

gs_bridge 将 control 翻译为 `fish_interfaces/ActuatorCommand` 发布到
`/fish/control/actuator_command`（限幅见 gs_bridge/gs_bridge_node.py 的 CONTROL_LIMITS）。

## 双尾鱼板上服务启动（pico，root，ros2 launch 方式）

```bash
/root/catkin_ws/src/pico_stereo/scripts/start_dual_fish.sh
```

一键脚本 = 加载 ROS2 环境 + `ros2 launch`。launch 文件:
`pico_stereo/launch/depth.launch.py`（双目测深）、`gs_bridge/launch/gs_bridge.launch.py`
（控制桥）、`pico_stereo/launch/dual_fish_bringup.launch.py`（一键总成，绝对路径引用，
**从源码目录直跑**，不依赖 colcon install 产物）。Ctrl+C 停止全部节点。

注意：源文件 `depth_node.py`/`stereo_lib.py` 已加 `chattr +i` 不可变锁（修改前先
`chattr -i`）。板上另有并行 agent/用户共用节点，其测试前清场（pkill 等）
会停掉服务，重新运行上面的启动脚本即可。

