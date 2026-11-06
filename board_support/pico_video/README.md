# Pico 双目视频服务源码镜像

- `stereo_stream.py`：同步双目 JPEG 视频服务，支持按连接临时调整发送帧率；断开时恢复原设置。
- `native_mjpeg.py`：可控 V4L2 子进程采集原生 MJPEG，启动失败则由视频服务回退原 OpenCV 路径。

这两份文件与机器鱼项目 `pico_stereo/pico_stereo/` 同名源码同步，部署到 Pico 的 `/root/catkin_ws/src/pico_stereo/pico_stereo/`。部署前须确认板端当前代码、保留旧文件备份并检查相机和用户现有连接，不得覆盖未知改动；服务需按原有 `ros2 launch` 方式在适当时机重启才加载新代码。不得借此启动舵机或修改控制桥。原生录像是左右目未经校正的画面，需 PyAV；无法获得独立曝光时间戳或保证不同环境下恒定 30 FPS。
