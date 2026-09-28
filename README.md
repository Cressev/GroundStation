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
conda activate qt5
python main.py          # 先弹出版本选择对话框，选择后进入主窗口
```

服务端启动方式见 `catkin_ws_in_fish/部署说明.md`（单尾鱼）与
`pico_stereo/USAGE.md` + `gs_bridge`（双尾鱼，由代理部署在 pico 上）。

## 文件清单（逐文件）

| 文件 | 说明 |
|---|---|
| `main.py` | 入口：高 DPI 设置 → 版本选择对话框 → 按变体构造 MainWindow |
| `config.py` | 全局配置：单尾鱼 IP/端口、`DUAL_FISH_CONFIG`（pico IP + 9999/9998 端口）、控制限幅、键位映射、UI/视频/记录参数 |
| `ui/fish_variant_dialog.py` | **新增** 启动版本选择对话框（dual/single 卡片式选择） |
| `ui/main_window.py` | 主窗口：按 `variant` 加载视频页（dual=双目测距组件 / single=原视频监控）、连接默认值、菜单、键盘事件分发、安全启用开关 |
| `ui/stereo_camera_widget.py` | **新增** 双尾鱼视频+测距组件：`StereoVideoClient`（TCP 9998 客户端，协议兼容老版）+ `StereoFishCameraWidget`（画布显示、鼠标点击→SET_POINT、测量 JSON 刷新 D/Z/X/Y/视差标签） |
| `ui/fish_camera_widget.py` | 单尾鱼机载相机组件（TCP 9998 客户端 + 机上录制控制），仅 single 变体使用 |
| `ui/video_display.py` | 笔记本外接 USB 相机监控（VideoDisplayWidget + VideoMonitorWidget 容器），仅 single 变体使用 |
| `ui/visualization.py` | pyqtgraph 数据可视化（XY 轨迹/深度/姿态/实时朝向） |
| `ui/keyboard_status.py` | 键盘按键状态面板与特殊功能键处理 |
| `ui/data_recording.py` | 数据记录/CSV/Excel 导出控制面板 |
| `controllers/base.py` | KeyboardController 等控制器：把键盘事件合成为 ControlCommand（频率/幅值/偏置/胸鳍角） |
| `communication/base.py` | 通信抽象基类（FishState/ControlCommand/FishCommunicationInterface） |
| `communication/socket_client.py` | 单尾鱼 TCP 控制客户端（9999，JSON 行协议，50Hz 传感器推送接收） |
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
  PING            探活
```

控制（9999，gs_bridge）：

```
地面站->板上: {"type":"control","tail_frequency":Hz,"tail_amplitude":rad,
              "tail_offset":rad,"pec_angle":us}   （JSON 行）
板上->地面站: {"type":"state","ack_count":N,"last_command":{...}}（2Hz 回推）
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

