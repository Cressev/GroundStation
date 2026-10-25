# 双目视频画布加大实施计划

**目标：** 放大竖向单目画面的默认显示，保留比例、完整画面和黑边；不修改采集、测距或当前连接。

**架构：** 原画布最低320逻辑像素导致纵向图被高度约束。默认改为720，新增320—2400的画布高度输入和恢复默认按钮，复用NoWheelSpinBox。现有整页滚动、SingleViewLabel等比例缩放和点击反算保留。

**技术：** PyQt5，仅电脑UI。

## 方案取舍

不采用拉伸铺满或裁剪；只增宽无法放大竖向图。选择提高高度并允许手动调节，不增加缩放拖动状态、不改变PNG或视频像素尺寸。

## 执行与验收

1. 备份ui/stereo_camera_widget.py、tests/test_host_stereo.py、ref/verify_stereo_resolution.py和README到根tmp/stereo_canvas_20261026_0213/backup。
2. 在test_host_stereo.py先写默认高度、调整/恢复、不发命令/不改变帧、滚轮不改值、滚动/居中/比例和点击映射回归；先跑确认失败。
3. 在ui/stereo_camera_widget.py添加高度控件和本地高度槽，不动视频协议、NPZ、worker、采集和保存代码。
4. 扩展ref/verify_stereo_resolution.py，在原合成TCP联调中检查720→960→720的显示和测点、单目保存尺寸不变，截取画布区域，检查640窄屏无横向溢出。
5. agentscope执行目标测试、完整非交互tests及真实Windows合成验证。只连127.0.0.1假相机，不接Pico，不中断用户窗口。
6. 更新README/docs索引、正式图文报告与总/板型索引、finding和记忆；本地提交本任务文件，不提交个人JSON/stereo_param，不push。

命令（src/GroundStation，agentscope）：

```powershell
python -X utf8 -c "import stereo_runtime; import pytest; raise SystemExit(pytest.main(['-q','tests/test_host_stereo.py']))"
python -X utf8 ref/verify_stereo_resolution.py --output ../../tmp/stereo_canvas_20261026_0213/windows
```

预期：测试全通过，默认画布720逻辑像素，竖向图比例正确且显著增大，高度可调/复位，点击映射与保存分辨率不变；不宣称相机实物测试。
