# 录制按钮与实时统计实施计划

**目标：** 双目页开始录制显示绿色、停止录制显示红色，同排右侧显示本次时长及已写帧数。

**架构：** 复用现有电脑端单目MP4录制，不改Pico、网络、相机或测距。由`_apply_ui_state`派生按钮文字/颜色；独立250ms定时器使用单调时钟刷新实际经过时间，帧数仅在`VideoWriter.write`未抛异常后累加。停止时冻结统计，下次开始清零。编码器失败显示失败并停止计时。OpenCV的write不提供逐帧落盘回执，统计不等于文件最终解码验收。

**技术：** Python、PyQt5、OpenCV、pytest；沿用当前分支，保留用户JSON/NPZ与运行进程，不创建另一套硬件连接。

## 步骤与验收

1. 已读取当前源码并备份到`../../tmp/stereo_recording_20261026_1055/backup/`，SHA256双侧一致。
2. 新建`tests/test_stereo_recording.py`：验证绿/红/禁用灰、计时/计数、停止冻结/重开归零、断线自动收尾、编码器失败；先运行见失败，再实现。
3. 修改`ui/stereo_camera_widget.py`：按钮样式属性、右侧状态标签、单调时钟/计时器、所有录制收尾路径；保持保存对话框与单目尺寸。
4. 新建`ref/verify_stereo_recording.py`：Windows平台使用合成帧写MP4、解码核对帧数和尺寸，保存绿/红/停止截图；不连接机器鱼、不操作现有UI。用用户指定agentscope运行，若编码器不支持必须如实记录，不能把空文件当通过。
5. 目标测试及全量非交互回归：`python -X utf8 -c "import stereo_runtime; import pytest; raise SystemExit(pytest.main(['-q','tests','--ignore=tests/test_opengl.py','--ignore=tests/test_fish_model.py']))"`。预期全部通过；AST核对新增函数docstring，中文UTF-8/BOM核验。
6. 更新本目录索引、项目README，正式报告统一到`../../docs/test-reports/pico/stereo_recording_20261026_1055/report.md`，配图放assets；更新两级报告索引及finding/长期记忆。本地Git仅提交本任务文件，不推送、不重启现有程序。

## 交互约定

- 初始：绿色“开始录制”（不可用时灰色），右侧“未录制 00:00:00 · 0帧”。
- 开始：红色“停止录制”，右侧“录制中 HH:MM:SS · N帧”；等待新帧时计时继续而帧数不变。
- 停止/关闭相机/断线：停止计时并保留本轮统计；重复停止不得再次保存或重置。
- 窄屏：沿用工具栏自己的横向滚动，不增加整页横向溢出；不换成两排。
- 时长是实际录制经过时间，现有MP4仍为固定15FPS，播放时长不一定等于实际时长；本轮不改变编码策略。
