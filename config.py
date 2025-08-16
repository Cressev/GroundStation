# 机器鱼控制系统配置文件

# 网络配置
FISH_IP = "192.168.137.241"  # 机器鱼IP地址
SSH_PORT = 22
SSH_USERNAME = "orangepi"
SSH_PASSWORD = "orangepi"

# ROS配置
ROS_MASTER_URI = f"http://{FISH_IP}:11311"

# 控制参数范围
CONTROL_LIMITS = {
    "tail_frequency": {"min": 0.0, "max": 10.0, "default": 1.0, "unit": "Hz"},
    "tail_amplitude": {"min": 0.0, "max": 1.57, "default": 0.5, "unit": "rad"},
    "tail_offset": {"min": -1.57, "max": 1.57, "default": 0.0, "unit": "rad"}
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
    "up": "Q",
    "down": "E",
    "stop": "Space",
    "increase_freq": "Up",
    "decrease_freq": "Down",
    "increase_amp": "Right",
    "decrease_amp": "Left",
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
    "video_format": "RGB888"
}
