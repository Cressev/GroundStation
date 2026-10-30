# 机器鱼地面站 GroundStation（PyQt5）

## 2026-10-28 快摆慢回 κ

双尾键盘与Xbox新增“去程占比 κ”，默认0.5，范围0.1—0.9，步进0.01，两个尾关节共用；只改κ也会发送，应用后保存。κ=0.5对称，低于0.5去程快、回程慢，高于0.5相反，不需要切模式。键盘实时区显示κ/f及(1−κ)/f秒；原有其他参数与保存文件保留。单尾隐藏κ。重开旧窗口才能加载新代码。

改动文件：config.py定义默认值；communication/base.py定义tail_kappa；communication/socket_client.py发送JSON；controllers/base.py管理键盘输入和保存；controllers/xbox.py管理Xbox；controllers/coordinator.py在独立深度控制时保留κ；ui/main_window.py按鱼型开关输入；data/recorder.py导出control_kappa。新增tests/test_tail_kappa.py覆盖本功能，ref/verify_tail_kappa.py以假通信和假手柄截取真实Windows面板。

Pico与STM32已同步更新，104项相关回归、消息与串口转换、五组真实CCR、驱动断心跳和GUI断线保护通过。机械和水中效果待测。[完整操作与报告](../../docs/test-reports/stm32/kappa_20261028_2043/report.md)。

双版本机器鱼地面站：启动时选择鱼体版本，按版本加载对应的视频、通信与控制页面。

数据可视化页顺序改为“时间序列 → XY轨迹图 → 姿态显示 → 系统状态”，默认进入时间序列。深度和姿态角图例采用8pt、小线段和紧凑间距，锚定各自绘图区左上角；全部名称/颜色及点击图例切换曲线显隐保留，不改数据、时间模式、导出或XY图例。[验证说明](docs/2026-10-26-time-series-legends.md)。

双目页“连接控制”五个常用按钮已收为紧凑单行：连接视频、断开、摄像头开关、开始/停止录制、保存图像，不再等分撑满整栏。录制按钮开始时绿色、录制中红色、不可用时灰色；右侧显示本次实际经过时长及单目写帧数。停止后保留统计，下次开始清零；固定15FPS视频播放时长可能与实际时长不同。按钮栏宽度不足时仅工具栏横向滚动，不挤宽视频页。[录制说明](docs/2026-10-26-recording-status.md)。

双目页单目画布已加大：默认高度720逻辑像素，可在“画布高度”输入320—2400并恢复默认；竖向图按比例放大、居中留黑边，不拉伸不裁剪。高度框滚轮只滚页面，原截图/录像像素尺寸、测距坐标和相机配置不变。不需重启Pico，保存当前数据后重开地面站加载新布局。[画布说明](docs/2026-10-26-stereo-canvas.md)。

双目测距页新增“采集分辨率”下拉和“应用分辨率”：连接新版视频服务后读取真实可用双目档位，关闭摄像头再应用，开启后核对实际尺寸。当前相机枚举的每目档位为320×240、640×480、800×600、1280×720、1600×1200；不混入原生单目模式。NPZ须与每目尺寸匹配，不匹配只预览原始第一目、禁止测距；截图/录像仍只存一目。板端源码已备份更新，但现有运行服务未重启，保存当前数据后重启UI及原一键服务生效。[使用与验证](docs/2026-10-26-stereo-resolution.md)。

右侧栏顶部的向右箭头可收起整栏，将空间留给画布；右边缘向左箭头可展开。保留当前页面、日志和服务连接，记住收起状态及展开宽度，单双尾版本分别保存。[操作与离线验证](docs/2026-10-24-sidebar-collapse.md)。

2026-10-23双尾鱼左侧已改为独立的“航向控制”和“深度控制”：键盘/Xbox可与单闭环深度PID组合，
各自启停、选型和显示参数，系统信息移至右下角。[新版控制栏使用说明](docs/2026-10-23-independent-control-axes.md)。
参数框按各自启动状态开放：未启动置灰，启动成功后可调节；深度参数无需额外解锁。
参数名保持单行，数字框随侧栏宽度伸展；长说明才换行，极窄栏宽使用滚动，不再挤断中文参数名。

最终定深架构：单双环均在Pico本机计算，电脑只调参/启停/显示；双环两列并排，周期可调。
双环参数区采用9pt紧凑字号与较小间距，保持两列、完整参数名和单位；选择双环时按紧凑表单宽度调整侧栏，不沿用旧的过宽布局。
[Pico并联双环使用说明](docs/2026-10-23-pico-parallel-pid.md)。

“数据可视化 → 系统状态”：CPU/温度/内存独立画布、可调高度和滚动。顶部同排全局/滑动/窗口大小及清除/重置/保存数据/保存图像，窄屏自动换行；已删除实验标签和导出范围下拉。保存按最近手动查看/重置画布的真实可见范围（默认CPU）导出CSV/Excel，按钮提示当前参照；完整三图PNG和断线缺口保留，不改板端控制。[页面说明](docs/2026-10-23-system-status.md)。

- **双尾双目鱼（dual，当前主攻）**：Pico新节点`stereo_stream_node`经有线9998传同帧双目
  （默认1280×480横拼，每目640×480，支持在关相机时切换）与原标定。电脑执行SGBM192/WLS/Q，仅显示左校正图，
  点击标点及读当前帧距离；截图/录像只存这一目，不发送RANGE_ON。9999控制桥与舵机逻辑不变。
  旧视频服务只兼容预览。原start_dual_fish.sh已默认新视频，保留日志监控及其他服务。
- **单尾单目鱼（single，旧平台）**：机载 orangepi（ROS1）。视频连
  `camera_stream_server`（9998，机上录制），控制连 `socket_server`（9999，
  发布 /servo_info_*）。原功能不变。

## 快速启动

2026-10-21本地测距的操作与逐文件说明优先见下节；后面的旧板端协议保留作回退说明。

### 本地测距运行库与操作

```powershell
conda activate agentscope
python ref/install_local_stereo_runtime.py
python main.py
```

本机已将固定版本`opencv-contrib-python==4.11.0.86`安装到忽略目录`.runtime/opencv/`，
安装器拒绝覆盖已有目录，不替换全局OpenCV；无需重复安装。入口在首次导入cv2前引导私有库。
agentscope缺Qt时仅在当前进程复用相邻qt5环境已有GUI包；其他电脑需准备PyQt5/pyqtgraph等基础依赖。
缺WLS会明确报错，不静默改变算法。原fish_ui_gpu/qt5启动方式继续保留。

板上只启动新视频节点（确认9998和相机未被旧节点占用，不含运动控制）：

```bash
source /opt/ros/humble/setup.bash
ros2 launch /root/catkin_ws/src/pico_stereo/launch/stereo_stream.launch.py
```

预期`relay_listen`且`depth_compute=false`，相机默认关闭。连接主控、连接视频、开启相机后，
UI首次默认取板端NPZ；“加载本地NPZ”先检查格式、字段和数值，成功后记住文件路径，下次重开自动重新校验加载，
页面独立显示当前文件名、完整路径与生效状态；文件丢失/损坏则明确报错且不静默回退。
无需重新标定或上传到Pico。“使用板端NPZ”显式恢复默认并清除本地路径记忆。详见[NPZ选择说明](docs/2026-10-21-npz-selection.md)。
默认显示640×480左校正图，顺时针转为480×640后Gamma2.0提亮；其他档位按其实际每目尺寸处理。
算法输入不提亮。点击黑边忽略；绿十字/圆圈有效，红色无效并清除旧XYZ。
D为三维距离，Z为光轴深度，单位cm，不是水面深度传感器数据；测点固定像素，不做物体跟踪。
“保存图像”选PNG路径，绿色“开始录制”开始保存单目视频，红色“停止录制”停止后选MP4，只存带标记的这一目，板上录制入口禁用。右侧实时显示录制时长和帧数，停止后保留；尚无新帧就停止不会导出空MP4。
“暂停/恢复本地测距”只控制电脑计算。旧服务不提供同步双目/标定时只能预览。

| 新增/变更源文件 | 具体职责 |
|---|---|
| `tests/test_stereo_recording.py` | 录制绿/红/禁用样式、单调时钟/帧数、冻结/清零/幂等、断线及关闭自动收尾、编码失败/无帧及窄屏7项回归 |
| `ref/verify_stereo_recording.py` | 真Windows合成帧录制，PNG核对红绿颜色，实际MP4解码验证30帧及单目尺寸，宽/窄工具栏截图与个人JSON散列核对；不连接硬件 |
| `tests/test_stereo_resolution.py` | 能力下拉、应用回执/超时/失败/重连、摄像头/录像门闩、标定失配预览及epoch旧帧过滤 |
| `ref/verify_stereo_resolution.py` | 仅合成相机的真实Windows Qt/TCP联调，检查高分辨率NPZ、720/960画布缩放及复位、点击距离、单目PNG及窄屏；不连接真实机器鱼 |
| `main.py`、`stereo_runtime.py` | 主入口先选择私有contrib；缺Qt时复用相邻qt5已装GUI依赖，不改Conda环境文件 |
| `stereo/__init__.py` | 本地双目包入口 |
| `stereo/transport.py` | 与板端逐字节一致的有界封包、原子元数据、半包跨timeout保留 |
| `stereo/calculation.py` | 所选NPZ与采集源SHA独立绑定，本地32MiB/解压32MiB及字段/数值校验；原SGBM192/WLS/Q/9×9中值；失配只预览原始第一目、JPEG尺寸检查、旋转坐标反算 |
| `stereo/worker.py` | 输入和输出各留最新项；关机/断链/换模型丢弃正在计算的旧帧，GUI不运行SGBM |
| `ui/stereo_camera_widget.py` | 能力分辨率选择及关机态带ID应用/超时核对、单目画布720默认/320—2400可调及复位、等比居中/黑边、同帧点击、PNG/MP4；录制红绿按钮/右侧时长帧数/失败收尾；相机/录像门闩、旧epoch过滤，不发RANGE_ON/SET_POINT |
| `ui/main_window.py` | 本地测距与增强单目复用、独立航向/深度控制栏、单出口发送门闩、右栏幂等收放与按鱼体布局记忆、右下系统信息及关闭清理 |
| `tests/test_sidebar_collapse.py` | 双版本收放/中心扩展、幂等不干扰服务、重启宽度和状态、窄栏/缩窗、键盘操作、双环选型与非法偏好回归 |
| `ref/verify_sidebar_collapse.py` | 真Windows离线收放/重启截图及个人配置SHA核验，不连接板子或启动运动 |
| `docs/2026-10-24-sidebar-collapse.md` | 右栏箭头操作、布局保存与独立复现命令 |
| `ui/system_status.py` | 顶部同排/窄屏换行，无实验标签/导出下拉；三图独立跟随/范围/重置/滚动，按最近手动图可见范围导出CSV/XLSX，完整PNG与缺口 |
| `tests/test_system_status.py` | 十一项遥测/历史/导出、断线/连接门闩、独立图、控件移除、顶部同行、宽转窄不撑宽与自动导出参照回归 |
| `ref/verify_system_status.py` | 真Windows1200/640工具栏、独立三图/滚动/CSV/XLSX601行/PNG及640/1000视频居中截图；合成数据，不联网不写个人配置 |
| `docs/plans/2026-10-25-system-status-toolbar.md` | 本次顶部工具栏简化设计/备份/TDD/自适应布局/自动导出参照及离线验收计划，不涉及板端部署 |
| `docs/2026-10-23-system-status.md` | 系统页使用、遥测口径、四组散热实验设计及本轮未实测边界 |
| `docs/plans/2026-10-23-system-status-thermal.md` | 先UI再实验的分步计划、固定负载/起温条件与接线待确认项 |
| `ref/install_local_stereo_runtime.py` | 固定版本私有运行库安装器，已有目录拒绝覆盖 |
| `ref/verify_npz_selection.py` | 不联网的真Qt验证：临时INI隔离真实偏好，三份真实NPZ、历史双目、后台计算、鼠标标点、单目PNG、启动恢复与丢失文件阻断、切回默认，输出摘要和截图 |
| `tests/test_host_stereo.py` | 半包/坏包/标定/失效generation、旋转点击、XYZ清理、可见标记、单目保存；画布默认/放大/复位、比例居中、滚轮/滚动、坐标及保存尺寸不变回归 |
| `tests/conftest.py` | NPZ偏好测试统一使用临时INI，测试不得污染用户注册表中的选择 |
| `ui/numeric_inputs.py` | 禁滚轮整数/浮点框及控制类型下拉框，滚轮转交最近滚动区；保留点击/Tab、键盘、数字按钮和编辑；集成控制区可选动态最小宽度，完整显示数字/单位并适应字体变化 |
| `tests/test_control_no_wheel.py` | 8项Qt事件回归：键盘9项、深度含键盘18项、Xbox13项数字参数禁滚轮，聚焦/未聚焦、文本子控件、触控板、键盘/按钮及父页面滚动 |
| `ref/verify_control_no_wheel.py` | 真Windows窗口离线验证三控制页40项数字参数，逐项检查页面滚动、数值不变、键盘与编辑；不启控制、不连板、不保存参数，输出截图和JSON |
| `controllers/coordinator.py` | 双尾鱼唯一完整指令合成出口：尾鳍取选中航向来源，胸鳍取PID或手动；独立启停、来源门闩、交接、全停及紧停 |
| `controllers/depth_axis.py` | 独立单闭环深度通道；只显示PID参数并输出胸鳍，复用原PID数学/限幅/超时，启动等待新样本，不绑定键盘 |
| `controllers/parallel_depth.py` | 并排双环视图及离线算法母本；正式UI只继承视图，不运行此电脑PID路径 |
| `controllers/remote_depth.py` | 正式单双环Pico配置代理：目标/参数/周期/启停、会话回执、超时撤权、板端实际PWM显示；不在电脑生成PID输出 |
| `tests/test_parallel_depth.py` | 并联算术、并排布局、样本身份、四元数、TCP完整帧及板端胸鳍仲裁 |
| `tests/test_board_depth.py` | Pico引擎、周期/失效/单双环、PC禁止PID计算、手动屏蔽和实际PWM交接 |
| `ref/verify_parallel_depth.py` | 真Windows Qt五场景、左右参数截图与独立模拟Pico回执，不连板、不改个人配置 |
| `docs/2026-10-23-pico-parallel-pid.md` | 最终Pico计算架构、两列参数、周期、单位、安全保护和验证边界 |
| `docs/plans/2026-10-23-parallel-depth-pid.md` | 并联双环计划及用户确认的板端计算架构修订 |
| `tests/test_control_axes.py` | 46项组合/安全/布局回归：键盘与Xbox组合、单路启停、PWM交接、新样本/超时、旧来源、X/B及断链（含仅深度运行）、参数启停锁、不同字体/栏宽下标签单行与输入完整、禁滚轮/幂等 |
| `ref/verify_control_axes.py` | 真Windows主窗口七场景假通信/假手柄验收，输出全窗/控制区截图、数字框几何和合成指令；可用--sidebar-width/--font-size验证不同布局，不联网、不启相机、不保存个人配置 |
| `tests/test_npz_selection.py` | 22项本地NPZ回归：来源绑定、重连、格式校验、安全切换、路径记忆、启动文件重新校验/丢失损坏阻断及独立进程恢复 |

新协议外层仍`[4字节大端长度][1字节类型][数据]`，最多16MiB。0xFD双目、0xFC原NPZ，
两者数据体为`[2字节JSON长度][JSON][二进制]`，JSON最多4096字节。帧绑定frame_id、
camera_epoch、采集单调时钟、尺寸、标定SHA256。0xFE状态，0xFF仅旧预览。
请求为GET_STATE、GET_CALIBRATION、CAM_ON/OFF、PING，新服务拒绝RANGE_ON/板上录制。
可信有线LAN使用，不提供外网认证防护。总入口已切换，详见仓库`docs/local-stereo/README.md`。

### 历史环境与旧节点说明

```bash
conda activate fish_ui_gpu
python main.py          # 先弹出版本选择对话框，选择后进入主窗口
```

当前电脑没有 `fish_ui_gpu` 环境时，可使用已验证的 `qt5` 环境运行传统增强与全部基础功能：

```powershell
conda activate qt5
python main.py
```

2026-10-15 新 Pico 已保存为连接档案“新板 ICS 固定 IP”，地址
`192.168.137.3:9999`。启动时选“双尾双目鱼 (pico)”，进入主窗口后下拉选择该档案并点击
“连接”；视频通道会自动连到 9998，再点击“开启摄像头”。

`fish_ui_gpu` 是启用 UIEC²-Net、U-shape Transformer 和 Ucolor 的推荐环境；`qt5` 环境仍可
运行传统增强和其余地面站功能，但无法运行三个 CUDA 模型。

服务端启动方式见 `catkin_ws_in_fish/部署说明.md`（单尾鱼）与
`pico_stereo/USAGE.md` + `gs_bridge`（双尾鱼，由代理部署在 pico 上）。

## 文件清单（逐文件）

| 文件 | 说明 |
|---|---|
| `main.py` | 入口：高 DPI 设置 → 版本选择对话框 → 按变体构造 MainWindow |
| `config.py` | 单尾/双尾IP端口与控制限幅、键位、键盘/Xbox/PID默认参数及UI记录参数；STEREO_RANGING_UI_ENABLED是旧板端开关，不控制新本地测距；STEREO_PREVIEW_LAYOUT仅作旧流兼容 |
| `connections.json` | 本地连接档案；新板 `192.168.137.3:9999` 已置顶，原板 `.2` 和历史直连地址继续保留 |
| `ui/fish_variant_dialog.py` | **新增** 启动版本选择对话框（dual/single 卡片式选择） |
| `ui/connection_store.py` | **新增** 连接档案持久化（本地 connections.json 记录 备注+IP+端口，双尾鱼页面下拉直选） |
| `ui/heartbeat_light.py` | **新增** 心跳呼吸灯（状态栏左下角）：脉冲只由真实心跳发送事件驱动——通信层每成功发出一拍 ping 经 Qt 信号点亮、两拍间自然衰减，停发即沉暗，不做装饰性空闪；悬停显示累计拍数与最后时刻；断链转灰 |
| `ui/main_window.py` | 主窗口：双尾鱼独立航向(键盘/Xbox)与深度PID、单出口发送与独立类型锁、右下系统信息；主连接四状态/从属服务门闩，紧停/断链撤两路；双尾首次侧栏420/300px、单尾360/280px，保留分版本宽度与地址记忆 |
| `ui/stereo_camera_widget.py` | 双尾鱼本地测距组件：TCP接收同帧双目，后台计算；加载本地最终NPZ或切回板端参数，显示路径/尺寸/生效状态，坏文件保留原参数，录像期间禁止切换；只显示左校正图，转正提亮、点击标点、单目PNG/MP4；状态集中派生，旧服务只预览 |
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
| `ui/visualization.py` | 时间序列优先、XY轨迹/姿态/实时朝向；两张时间图紧凑8pt左上图例及小样例、保留显隐交互；全局保留完整历史，滑动仅筛选显示；双图X轴同步，按可见范围保存深度/姿态CSV或XLSX，保存画布PNG，清除/重置/保存同行 |
| `ui/keyboard_status.py` | 键盘按键状态面板与特殊功能键处理 |
| `ui/data_recording.py` | 历史持续记录控制面板源码，为保留旧功能未删除；当前主界面不再挂载，实际导出由时间序列页的按钮完成 |
| `controllers/base.py` | 键盘尾鳍控制与500–2500μs胸鳍直设/QE；保留输入不被定时器抢写，新增外部胸鳍归属门闩，PID占用时屏蔽QE/直设并同步合成PWM |
| `controllers/depth.py` | 原单闭环PID数学、参数持久化、限幅/超时及公共PID参数页；保留旧键盘组合类作兼容回归，新UI由depth_axis.py独立复用，不再把深度类型当成航向类型 |
| `controllers/xbox.py` | 双尾鱼 Xbox 控制器：直接调用 Windows XInput（不依赖 pygame），50 Hz 轮询；LT/RT 以无符号 8 位值连续映射 0～100%；左摇杆前半圆连续控制方向，进入后半圆保持进入前的尾鳍状态，重新进入前半圆时偏置按两个尾摆周期过渡；LT 连续加速，启停与加速同样按两个周期平滑；Y/A 匀速调胸鳍、RT 提速；Xbox 控制成功启用后长震 600 ms，X/B 紧停短震 250 ms，断连立即停尾但不震动；页面显示输入、尾鳍参数、胸鳍 PWM 与估算角度 |
| `xbox_params.json` | Xbox 控制参数：LT 松开/全按时的频率和摆幅端点、最大转向量、基础偏置、相位差、摇杆/扳机死区、胸鳍范围与普通/RT 调节速度 |
| `communication/base.py` | 通信抽象基类（FishState/ControlCommand/FishCommunicationInterface） |
| `communication/socket_client.py` | 双尾/单尾 TCP 控制客户端（9999，JSON 行协议）：state 回推走状态回调（遥测 + IMU 欧拉角并入 FishState.orientation 实时驱动姿态图），depth 推送装入 FishState.depth 供时间序列图，兼容旧版单尾鱼组合格式 |
| `communication/ssh_ros.py` | SSH 执行 ROS 命令的辅助（旧链路备用） |
| `data/recorder.py` | 历史持续传感器/控制数据记录器（CSV + metadata），当前主界面不调用 |
| `utils/graphics_exporter.py` | 历史全图导出器，当前时间序列 PNG 导出改由 `ui/visualization.py` 实现 |
| `catkin_ws_in_fish/` | 单尾鱼（orangepi ROS1）机载脚本母本：`camera_stream_server.py`（9998 视频流+机上录制）、`socket_server.py`（9999 控制+传感器推送）、launch 与部署说明 |
| `tests/test_ui_state_machine.py` | 主连接、控制锁定、Xbox 模式接入和无手柄拒绝启用、视频确认状态、失败重试、侧栏默认值与持久化的离线回归测试 |
| `tests/test_last_connection.py` | 12项地址记忆隔离测试：重开/跨进程、双鱼体隔离、失败不覆盖、坏记录回退、档案同步，不接真实网络 |
| `tests/test_xbox_controller.py` | Xbox 前半圆转向、后半圆保持及跨侧偏置过渡、两个周期启停、LT/RT 全量程无符号读取、LT 连续加速、Y/A/RT 胸鳍调节、启用成功长震、X/B 紧停短震和无手柄拒绝激活的离线回归测试 |
| `tests/test_visualization_time_modes.py` | 全局/滑动/幂等/双图时间轴/可见范围CSV/XLSX，页签顺序默认值、图例名称/尺寸/紧凑/锚定及点击显隐回归 |
| `ref/verify_time_series_layout.py` | 真Windows合成曲线窗口，1200/760尺寸检查图例锚定、输出PNG/CSV，验证个人JSON散列保持；无网络或硬件 |
| `tests/test_depth_controller.py` | PID 数学、参数锁、中位与限幅、方向切换、键盘并行控制和断流回中测试 |
| `docs/2026-10-13-ui-state-machine-design.md` | 本次 UI 状态机的状态、门闩、幂等规则和验证边界 |
| `docs/2026-10-21-npz-selection-plan.md` | 本地最终NPZ选择、独立来源绑定和事务式切换的实现计划 |
| `docs/2026-10-21-npz-selection.md` | 环境文件选择步骤、必需字段、尺寸限制、重连/重开规则及离线验证摘要 |
| `docs/2026-10-22-control-no-wheel.md` | 左侧数字参数禁滚轮的操作规则、覆盖范围、验证结果和可复现步骤 |
| `docs/2026-10-23-independent-control-axes.md` | 新控制栏布局、控制组合/执行器归属、启停/紧停/断链、验证与复现边界 |
| `docs/plans/2026-10-23-independent-control-axes.md` | 解耦实施计划及单出口架构决策，含故障策略与验收步骤 |
| `docs/XBOX_CONTROL_GUIDE.md` | Xbox 蓝牙连接检查、按键映射、参数含义、安全操作顺序和首次水池联调步骤 |
| `docs/README.md` | docs 文档目录逐文件索引 |
| `Change_log.md` / `TODO.md` | 变更记录与待办 |
| `fps_compare/`、`records/`、`temp_scripts/`、`image.png` | 历史测试素材与一次性脚本（非运行依赖） |

## UI 状态机与安全交互

左侧键盘、深度/PID和Xbox控制页所有数字输入框均禁用滚轮改值，包括获得焦点后也不例外。
鼠标停在参数输入框或数字文本上滚动，仍滚动左侧页面；点击输入框后可用键盘上下箭头、
输入框旁上下按钮或直接输入数字修改。“应用/保存/设定”流程不变；未启动的控制通道参数置灰，启动成功后开放编辑。
详见[数字输入防误滚说明](docs/2026-10-22-control-no-wheel.md)。

启动时按鱼体版本分别恢复最后一次成功连接的IP和端口，不自动连接或启用控制。
连接成功立即保存；失败、只编辑或选档案不覆盖记录。缺失/坏记录回退原档案或默认值，
不改connections.json顺序。旧版没有此记录，更新后先成功连接一次，之后启动即恢复。
详见[地址记忆说明](docs/2026-10-21-last-connection.md)。

双尾鱼页面采用严格依赖关系：`主控制连接 → 视频/深度服务连接 → 摄像头确认开启 → 录制`。
下一级只能在上一级真实就绪后操作；主连接断开会自动撤销控制、锁定视频和深度页，并停止相关
记录。TCP 工作线程的 `running` 只表示线程生命周期，不再冒充“已经连接”。连接中再次点击断开
会设置取消标记；旧线程没有退出前不会启动第二次连接。

双尾鱼航向和深度通道各自运行时锁定自己的类型；停用航向后可更换键盘/Xbox而不关闭PID。
航向只输出尾鳍，深度PID启动后独占胸鳍；单独关闭PID将最后合成的胸鳍指令值交给手动控制，
不会恢复旧手动值。全部停止/断链/关闭撤销两路并停尾回安全1500μs；Xbox X/B或手柄断开同样撤销两路，
但保持当时胸鳍指令。重连默认两路关闭。单尾版本仍为原单一键盘路径。
当前规则见 `docs/2026-10-23-independent-control-axes.md`；10月13日旧互斥模式文档仅保留历史说明。

## Xbox 控制

Xbox 控制只在“双尾双目鱼”页面出现。电脑先通过蓝牙连接并唤醒手柄，再连接机器鱼；在“航向控制”
中选择“Xbox 控制”，确认实时状态显示“手柄：已连接”后才能勾选“启动航向控制”；成功启用后，
手柄双电机长震 600 ms 作为确认，未检测到手柄或启用失败时不震动。左摇杆前半圆的
角度连续决定转向；进入后半圆不会倒退或停机，而是保持越过边界前一刻的尾鳍频率、摆幅和偏置。
若沿后半圆从最左侧转到最右侧，重新进入前半圆时，尾鳍偏置会在两个当前摆动周期内连续过渡，
不会从左极限突变到右极限。只有摇杆进入中心死区才触发平滑停止。LT 从松开到全按在普通档和
加速档参数间连续插值；启动、LT 加速和中心回中停止均使用两个尾摆周期的平滑过程。

深度控制未启动时，Y 增大胸鳍 PWM，A 减小胸鳍 PWM，RT提高调节速度；PID启动后手动胸鳍屏蔽，尾鳍/方向/LT仍有效。LT/RT 的完整
物理行程都线性显示为 0～100%。X 或 B 会绕过平滑过程，立即发送零尾鳍摆幅、保持当时胸鳍指令，
让当前手柄双电机短震 250 ms，并关闭航向和深度两路；手柄断开执行停尾路径但不震动。紧停后
必须确认摇杆回中，并在 UI 中分别重新勾选需要的通道。页面显示的胸鳍角度由 500–2500 μs 线性
换算为 0–180°，是指令估算值，不是位置传感器反馈。完整操作见 `docs/XBOX_CONTROL_GUIDE.md`。

## 深度闭环控制

深度闭环只在启动时选择“双尾双目鱼”后出现，不会启动双目测距。反馈量来自控制连接
`9999` 已有的 WF5803 融合深度，并使用深度页面同一个零点：
`控制深度 = fused - zero_offset`，单位始终为 cm。**水面为 0，水下为正数，越深数值越大**；
例如目标深度 20 cm 应填写 `20 cm`。

操作顺序：

1. 先连接机器鱼，确认“深度”页面持续显示有效数值；需要相对水面控制时先完成零点标定。
2. 左侧下方“深度控制”选择“单闭环PID”；上方“航向控制”独立选择键盘或Xbox，不再强制键盘。
3. 未启动时参数置灰。确认当前保存参数与实验条件安全后，勾选“启动深度控制”，按已保存参数启动；PID不依赖航向是否启动，等待启动后的新深度样本。
4. 启动成功后直接填写目标深度、Kp/Ki/Kd、中位脉宽、最小/最大脉宽等，点击“应用并保存参数”，无需额外解锁。参数文件只保存在本机，不上传 Git。
5. 需要尾鳍运动时独立勾选“启动航向控制”，对应参数才可编辑。PID期间QE/Y/A/RT等手动胸鳍不生效。
   单独停深度控制时从最后合成的PWM交回手动；仅停航向时PID继续。需全部停止请点常驻的“全部停止”。

首次下水默认按“目标更深时减小脉宽”输出，目标 15 cm，Kp=20，Ki=Kd=0，中位 1500 μs，
输出限制 1300–1700 μs。若鱼体响应方向相反，应先停止并确认执行器安全，参数只在对应控制启动时可编辑；
安全条件下修改“输出方向”为“目标更深时增大脉宽”并应用。Kp/Ki/Kd 均允许输入负值；通常建议增益保持正值，只用“输出方向”
选择执行器极性，避免“负增益 + 反向输出”发生两次反转。深度数据超过 0.5 秒未更新时，控制器清空 PID 状态并把胸鳍回到中位；
全部停止、紧停及通信断开具有最高优先级；已新增并联深度/俯仰双环，两种模式均在Pico计算且周期可调。
旧版 `negative_down_v1` 或未记录坐标约定的 `depth_pid_params.json` 会在加载时安全迁移：保留 PID 增益与脉宽范围，但将目标恢复为 15 cm、输出方向恢复为“目标更深时减小脉宽”，防止旧的反向参数被继续使用。

## 双尾鱼 TCP 协议（pico 侧由 pico_stereo + gs_bridge 实现）

历史视频/测距（旧9998，depth_node；以下RANGE_ON不是新界面操作）：

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

**保存视频**：双目页绿色“开始录制”按钮开始录制、红色“停止录制”结束，右侧显示实际时长/写帧数；单尾页原“保存视频”保留。停止后弹出
文件对话框选择保存位置与文件名（**仅支持 mp4**，mp4v 编码；取消则存到
records/ 下按时间戳命名）。板上相机曝光/增益需在 v4l2-ctl 预设好
（depth_node 已自动设置，室内默认 exposure_absolute=1300 + gain=120）。

## 图像增强对比页

双尾鱼模式下中央区域新增第三个标签页 `图像增强对比`。页面把同一视频帧的原图和增强图
左右等宽排列，不提供可拖动分隔线；窗口尺寸变化时两侧自动同步调整。增强处理在独立线程
中进行，队列只保留最新帧；
处理速度低于采集速度时主动丢弃旧帧，优先保证实时预览延迟不会持续累积。

- 实时模式：复用 `StereoFishCameraWidget.single_frame_ready`的电脑端单目帧，不再建立第二条9998连接。
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

原路径现已默认新视频，保留监控、控制桥、深度传感器、串口桥和IMU。建议setsid nohup后台启动，
UI航向和深度两路先全部停止，服务重启后重新连接。重复启动不多开监控。

```bash
/root/catkin_ws/src/pico_stereo/scripts/start_dual_fish.sh
```

一键脚本 = 加载 ROS2 环境 + `ros2 launch`。launch 文件:
`pico_stereo/launch/stereo_stream.launch.py`（双目传输）、`gs_bridge/launch/gs_bridge.launch.py`
（控制桥）、`pico_stereo/launch/dual_fish_bringup.launch.py`（一键总成，绝对路径引用，
**从源码目录直跑**，不依赖 colcon install 产物）。Ctrl+C 停止全部节点。

注意：源文件 `depth_node.py`/`stereo_lib.py` 已加 `chattr +i` 不可变锁（修改前先
`chattr -i`）。板上另有并行 agent/用户共用节点，其测试前清场（pkill 等）
会停掉服务，重新运行上面的启动脚本即可。

