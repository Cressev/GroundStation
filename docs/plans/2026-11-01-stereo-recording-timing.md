# Stereo recording timing Implementation Plan

**Goal:** 使双目页 MP4 的播放时长与录制的真实经过时间一致，不影响相机及机器鱼控制。

**Architecture:** 维持现有左右目布局和 mp4v 编码；按单调时钟将实际输入帧重采样到 15 FPS 输出时间轴，间隔内保持上一帧，结束时补足到停止时刻。记录分别统计输入帧与编码帧；记录帧不等于网络接收帧。保留编码错误、无帧退出和断线自动收尾。

**Tech Stack:** Python、PyQt5、OpenCV、pytest、ffprobe。

### Task 1: 备份与基线

- 备份当前有未提交修改的 `ui/stereo_camera_widget.py`、`tests/test_stereo_recording.py` 和相关文档，不覆盖用户现有修改。
- 检查录像的写入路径、停止和失败处理，复核默认环境与编码器。

### Task 2: 测试和实现真实时间轴

- 扩展 `tests/test_stereo_recording.py`：固定输入 8 FPS、抖动/输入高于 15 FPS、停帧、停止和错误处理；验证视频编码帧数约等于经过秒数乘 15，并检查时间推进时的上一帧保持。
- 在 `ui/stereo_camera_widget.py` 中实现单调时钟驱动的时间轴重采样；编码写入隔离于 UI 线程、数据结构有界，避免无限积压；保留布局锁定与失败提示。
- 使用合成帧与真正的 mp4v 编码，ffprobe/解码检查帧数、播放时长和帧布局；不得连接机器鱼或发送舵机指令。

### Task 3: 文档和回归

- 更新 `README.md`、`Change_log.md` 和录制说明，讲清输入帧、重复输出帧、数据缺失与 LAN 实测边界。
- 执行相关录像、状态机与分辨率测试；保留现有未提交修改，不擅自提交或推送。
