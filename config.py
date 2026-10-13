# 机器鱼控制系统配置文件

# 网络配置
FISH_IP = "192.168.137.215"  # 机器鱼IP地址
SOCKET_PORT = 9999  # Socket通信端口
SSH_PORT = 22
SSH_USERNAME = "orangepi"
SSH_PASSWORD = "orangepi"

# ROS配置
ROS_MASTER_URI = f"http://{FISH_IP}:11311"

# 双尾双目鱼（pico RK3588S）配置
DUAL_FISH_CONFIG = {
    "fish_ip": "10.77.77.2",       # pico 有线静态 IP（稳定；WiFi IP 会漂移）
    "socket_port": 9999,           # 控制桥 gs_bridge 端口（JSON 控制命令）
    "video_port": 9998,            # 双目视频/测距服务端口（pico_stereo depth_node）
    "ssh_username": "root",
    "ssh_password": "123456",
}

# 机器鱼版本（启动选择对话框使用）
FISH_VARIANTS = {
    "dual": {"name": "双尾双目鱼 (pico)", "description": "双尾关节 Hopf + 胸鳍 + 双目测距"},
    "single": {"name": "单尾单目鱼 (orangepi)", "description": "单关节尾 + 胸鳍 + 鱼眼相机"},
}

# 控制参数（根据机器鱼舵机安全范围设定）
CONTROL_LIMITS = {
    "tail_frequency": {
        "min": 0.0,
        "max": 4.0,  # Hz
        "default": 0.0  # 静止启动
    },
    "tail_amplitude": {
        "min": 0.0,
        "max": 0.5,  # rad
        "default": 0.0  # 静止启动
    },
    "tail_offset": {
        # ±0.5是以基础偏置为中心的左右转向范围, 不是绝对零位限幅;
        # 合成偏置=基础偏置±转向量, 绝对范围可达±1.0 (Pi端socket_server已同步放宽)
        "min": -0.5,  # rad
        "max": 0.5,   # rad
        "default": 0.0
    },
    "pec_angle": {
        "min": 500,   # μs (PWM脉宽，STM32 胸鳍完整安全范围)
        "max": 2500,  # μs
        "default": 1500
    }
}

# 键盘开环控制默认参数
KEYBOARD_CONTROL_DEFAULTS = {
    "base_bias": 0.0,
    "slow_frequency": 1.5,
    "slow_amplitude": 0.2,
    "slow_turn_bias": 0.3,
    "fast_frequency": 4.0,
    "fast_amplitude": 0.5,
    "fast_turn_bias": 0.5,
    "tail_phase_diff": 1.57,
}

# 地面站深度闭环默认参数。深度单位为 cm，脉宽单位为 μs。
# direction=-1 表示目标更深时减小胸鳍脉宽；首次下水验证前保留窄限幅。
DEPTH_CONTROL_DEFAULTS = {
    "target_depth": 15.0,
    "kp": 20.0,
    "ki": 0.0,
    "kd": 0.0,
    "integral_limit": 1000.0,
    "neutral_pwm": 1500,
    "minimum_pwm": 1300,
    "maximum_pwm": 1700,
    "sensor_timeout": 0.5,
    "direction": -1,
}

# 传感器数据配置
SENSOR_CONFIG = {
    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    "orientation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
}

# 键盘控制映射
KEYBOARD_MAPPING = {
    "forward": "W",
    "backward": "S", 
    "left": "A",
    "right": "D",
    # 胸鳍角度控制
    "increase_pec": "Q",  # 增加胸鳍角度
    "decrease_pec": "E",  # 减少胸鳍角度
    # 频率控制
    "increase_freq": "Up",     # 增加频率
    "decrease_freq": "Down",   # 减少频率
    # 幅度控制
    "increase_amp": "R",    # 增加幅度
    "decrease_amp": "F",    # 减少幅度
    # UI控制
    "toggle_plot": "P",  # 切换绘图开关
    "clear_plot": "C"    # 清空绘图数据
}

# 数据更新频率 (Hz)
DATA_UPDATE_RATE = 50
PLOT_UPDATE_RATE = 10
PLOT_HISTORY_LENGTH = 500

# UI配置
UI_CONFIG = {
    "window_title": "机器鱼控制系统 Fish Robot Control System",
    "window_size": (1400, 900),  # 增加窗口大小以容纳视频
    "plot_colors": {
        "x": "red",
        "y": "green", 
        "z": "blue",
        "roll": "cyan",
        "pitch": "magenta",
        "yaw": "yellow"
    }
}

# 视频配置
VIDEO_CONFIG = {
    "default_resolution": (640, 480),
    "video_update_rate": 30,  # FPS
    "max_cameras": 10,  # 最大检测摄像头数量
    "video_format": "RGB888",
    "record_codec": "XVID",  # 视频编码格式
    "record_fps": 30,  # 录制帧率
    "save_directory": "records"  # 默认视频保存目录
}

# 数据记录配置
RECORD_CONFIG = {
    "data_save_interval": 0.1,  # 数据保存间隔(秒)
    "auto_save_interval": 300,  # 自动保存间隔(秒)
    "max_record_points": 10000,  # 最大记录点数
    "data_format": "csv",  # 数据保存格式
    "timestamp_format": "%Y%m%d_%H%M%S",
    "save_directory": "records"  # 保存目录
}
