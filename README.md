# 机器鱼控制系统 Fish Robot Control System

## 项目简介

这是一个基于PyQt5的机器鱼地面站控制系统，用于通过SSH连接控制和监控运行ROS1的机器鱼。

## 系统架构

```
GroundStation/
├── main.py                 # 主程序入口
├── config.py              # 系统配置文件
├── communication/         # 通信模块
│   ├── __init__.py
│   ├── base.py           # 通信接口基类
│   └── ssh_ros.py        # SSH/ROS通信实现
├── controllers/          # 控制器模块
│   ├── __init__.py
│   └── base.py          # 控制器基类和键盘控制器
├── ui/                  # 用户界面模块
│   ├── __init__.py
│   ├── main_window.py   # 主窗口
│   └── visualization.py # 数据可视化组件
└── README.md           # 说明文档
```

## 功能特性

### 1. 通信功能
- 基于SSH的ROS1通信
- 实时状态数据获取
- 控制命令发送
- 连接状态监控

### 2. 控制功能
- 键盘控制（已实现）
- 扩展接口支持Xbox手柄、自主控制等
- 实时控制参数调节

### 3. 数据可视化
- XY轨迹图：显示机器鱼在水平面的运动轨迹
- 深度-时间图：显示机器鱼的深度变化
- 姿态-时间图：显示Roll、Pitch、Yaw角度变化
- 实时姿态可视化：俯视图显示机器鱼当前朝向

### 4. 系统特性
- 模块化设计，易于扩展
- 良好的错误处理和日志记录
- 直观的用户界面

## 控制参数

### 机器鱼控制量
- **摆尾频率 (tail_frequency)**: 0.0-10.0 Hz，控制摆尾速度
- **摆尾幅度 (tail_amplitude)**: 0.0-1.57 rad，控制摆尾幅度
- **摆尾偏移角 (tail_offset)**: -1.57-1.57 rad，控制游泳方向

### 传感器反馈
- **位置坐标**: x, y, z (米)
- **姿态角**: roll, pitch, yaw (弧度)

## 键盘控制说明

| 按键 | 功能 | 说明 |
|------|------|------|
| W | 前进 | 偏移角度设为0 |
| S | 后退 | 偏移角度设为180° |
| A | 左转 | 偏移角度设为-90° |
| D | 右转 | 偏移角度设为90° |
| Q | 上浮 | 减小频率，增大幅度 |
| E | 下潜 | 增大频率，减小幅度 |
| Space | 停止 | 频率和幅度都设为0 |
| ↑ | 增加频率 | 步长0.1 Hz |
| ↓ | 减少频率 | 步长0.1 Hz |
| → | 增加幅度 | 步长0.05 rad |
| ← | 减少幅度 | 步长0.05 rad |

## 安装和运行

### 环境要求
- Python 3.7+
- PyQt5
- pyqtgraph
- matplotlib
- numpy
- paramiko

使用环境：
conda activate qt5 
### 安装依赖
```bash
# 激活conda环境
conda activate qt5

# 安装依赖包
pip install PyQt5 pyqtgraph matplotlib numpy paramiko
```

### 配置连接
在 `config.py` 中修改机器鱼的连接参数：
```python
FISH_IP = "192.168.1.100"  # 机器鱼IP地址
SSH_USERNAME = "orangepi"   # SSH用户名
SSH_PASSWORD = "orangepi"   # SSH密码
```

### 运行程序
```bash
cd GroundStation
python main.py
```

## 扩展指南

### 添加新的控制器
1. 在 `controllers/` 目录下创建新的控制器文件
2. 继承 `ControllerBase` 类
3. 实现必要的抽象方法
4. 在主窗口中注册新控制器

### 添加新的通信方式
1. 在 `communication/` 目录下创建新的通信实现
2. 继承 `FishCommunicationInterface` 类
3. 实现所有抽象方法

### 自定义可视化
1. 修改 `ui/visualization.py` 中的图表配置
2. 添加新的可视化组件
3. 在 `config.py` 中调整显示参数

## 注意事项

1. **网络连接**: 确保电脑和机器鱼在同一局域网中
2. **SSH权限**: 确保SSH用户有足够权限执行ROS命令
3. **ROS环境**: 机器鱼上的ROS环境需要正确配置
4. **防火墙**: 检查防火墙设置，确保SSH端口可访问

## 故障排除

### 连接问题
- 检查IP地址和网络连通性
- 验证SSH用户名和密码
- 确认机器鱼上的ROS master正在运行

### 控制问题
- 检查ROS topic是否存在
- 验证控制命令格式是否正确
- 确认机器鱼控制程序是否运行

### 显示问题
- 检查PyQt5和pyqtgraph安装是否正确
- 确认图表数据是否正常更新

## 开发计划

- [ ] Xbox手柄控制器
- [ ] 自主控制算法接口
- [ ] 数据记录和回放功能
- [ ] 多机器鱼支持
- [ ] 3D可视化
- [ ] 远程视频流显示
