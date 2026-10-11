# 机器鱼地面站 GroundStation（PyQt5）

双版本机器鱼地面站：启动时选择鱼体版本，按版本加载对应的视频、通信与控制页面。

- **双尾双目鱼（dual，当前主攻）**：机载 pico RK3588S（ROS2 Humble）。视频/测距连
  pico 的 `pico_stereo depth_node` TCP 服务（9998，协议见下），控制命令发 pico 的
  `gs_bridge` TCP 服务（9999），gs_bridge 翻译成 `/fish/control/actuator_command`
  交给串口桥发 STM32。**点击视频左上（左校正图）区域即可点击测距**。
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
| `config.py` | 全局配置：单尾鱼 IP/端口、`DUAL_FISH_CONFIG`（pico IP + 9999/9998 端口）、控制限幅（胸鳍 PWM 500–2500 μs）、键位映射、键盘默认参数 `KEYBOARD_CONTROL_DEFAULTS`（含相位差 1.57）、UI/视频/记录参数 |
| `ui/fish_variant_dialog.py` | **新增** 启动版本选择对话框（dual/single 卡片式选择） |
| `ui/connection_store.py` | **新增** 连接档案持久化（本地 connections.json 记录 备注+IP+端口，双尾鱼页面下拉直选） |
| `ui/heartbeat_light.py` | **新增** 心跳呼吸灯（状态栏左下角）：脉冲只由真实心跳发送事件驱动——通信层每成功发出一拍 ping 经 Qt 信号点亮、两拍间自然衰减，停发即沉暗，不做装饰性空闪；悬停显示累计拍数与最后时刻；断链转灰 |
| `ui/main_window.py` | 主窗口：按 `variant` 加载视频页（dual=双目测距组件 / single=原视频监控）、图像增强对比页（仅 dual）与深度页（仅 dual）、连接默认值、菜单、键盘事件分发、安全启用开关；主连接成功后自动连视频流并同步深度面板数据源 IP；底栏常驻控制板遥测标签（CPU/温度/内存/频率，1Hz 刷新） |
| `ui/stereo_camera_widget.py` | **新增** 双尾鱼视频+测距组件：`StereoVideoClient`（TCP 9998 客户端，协议兼容老版）+ `StereoFishCameraWidget`；纯显示快通路接收 2560x720 原始双目总图，在电脑端将每目 1280x720 顺时针转正、上下拼接成 720x2560，并做 Gamma 2.0 提亮，减轻 pico 负载；RANGE_ON/OFF 保留完整测距链和点击测点；另含相机开关、GET_STATE 状态同步和本地 MP4 保存 |
| `ui/depth_panel.py` | **新增** 双尾鱼深度面板：`DepthTcpClient`（TCP 9999 客户端，接收 gs_bridge 的 10Hz `{"type":"depth",...}` 推送）、大字号实时深度显示、**深度零点标定**（"标定"按钮采集 10 秒融合值均值设为 0 点，零点持久化 `depth_zero.json`，可"清除标定"；CSV 含标定后深度列）、开始/停止 CSV 记录（停止弹对话框仅存 .csv）。**深度单位为 cm**（板上节点输出即 cm，零点标定与显示同单位，全程无换算）。**数据源 IP 跟随主连接**：主连接成功后自动切到本次输入的 IP 并连上深度流，也可用面板内按钮手动连/断 |
| `ui/image_enhancement_widget.py` | 双尾鱼图像增强对比页：原图/增强图左右等宽显示，复用现有 9998 视频帧；一级选择传统方法/神经网络/不处理，传统方法下含综合增强、CLAHE、Gamma、白平衡；支持本地 Mock 视频、实时 FPS/延迟/丢帧统计、单画面放大、截图、左右对比 MP4 录像和参数导出 |
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
| `ui/visualization.py` | pyqtgraph 数据可视化（XY 轨迹/深度/姿态/实时朝向）；时间序列的深度-时间图含双目鱼五路曲线：原始1/原始2/滤波1/滤波2/标定后；时间轴模式可切全局/滑动窗口，滑动窗口支持用户填写 1–3600 秒；清除曲线与重置画布位于同一控制行，页面文案不再显示括号说明 |
| `ui/keyboard_status.py` | 键盘按键状态面板与特殊功能键处理 |
| `ui/data_recording.py` | 数据记录/CSV/Excel 导出控制面板；传感器数据保存目录组（IMU/深度各自目录，停止记录时按保存时刻在目录内生成 CSV） |
| `controllers/base.py` | KeyboardController 等控制器：把键盘事件合成为 ControlCommand（频率/幅值/偏置/**相位差**/胸鳍脉宽）；参数栏含相位差旋钮（默认 1.57 rad，±6.282），并可直接输入 500–2500 μs 胸鳍脉宽后点击“设定”发送；输入期间不会被 100 ms 控制定时器回写，Q/E 增量调节继续保留 |
| `communication/base.py` | 通信抽象基类（FishState/ControlCommand/FishCommunicationInterface） |
| `communication/socket_client.py` | 双尾/单尾 TCP 控制客户端（9999，JSON 行协议）：state 回推走状态回调（遥测 + IMU 欧拉角并入 FishState.orientation 实时驱动姿态图），depth 推送装入 FishState.depth 供时间序列图，兼容旧版单尾鱼组合格式 |
| `communication/ssh_ros.py` | SSH 执行 ROS 命令的辅助（旧链路备用） |
| `data/recorder.py` | 传感器/控制数据记录器（CSV + metadata） |
| `utils/graphics_exporter.py` | 可视化图形导出 |
| `catkin_ws_in_fish/` | 单尾鱼（orangepi ROS1）机载脚本母本：`camera_stream_server.py`（9998 视频流+机上录制）、`socket_server.py`（9999 控制+传感器推送）、launch 与部署说明 |
| `tests/` | 组件/键盘/视频等单元测试（pytest） |
| `docs/` | 功能说明文档（键盘、视频、舵机、传感器） |
| `Change_log.md` / `TODO.md` | 变更记录与待办 |
| `fps_compare/`、`records/`、`temp_scripts/`、`image.png` | 历史测试素材与一次性脚本（非运行依赖） |

## 双尾鱼 TCP 协议（pico 侧由 pico_stereo + gs_bridge 实现）

视频/测距（9998，depth_node）：

```
服务端->地面站: [4字节大端长度][1字节类型][数据]
  0xFF = JPEG 画布（1280x960：上行左|右校正图，下行视差伪彩，左图叠加测点与 D 读数）
  0xFE = UTF-8 JSON（{"type":"measurement","D":..,"Z":..,"X":..,"Y":..,"disp":..,"valid":..,"fps":..}
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
- 处理区域：整张画面，或仅处理双目测距画布上半部。
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
使用现有 Pico 视频流。`仅双目图区域（上半部）`用于 1280×960 双目测距画布，只增强上半部
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

