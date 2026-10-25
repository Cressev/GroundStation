# 双目采集分辨率选择实施计划

**目标：** 双目测距页可选择真实双目采集档位；保持本地测距和单目保存，禁止把单目档位误当双目。

**架构：** Pico通过GET_STATE公布UVC MJPG枚举与已知双目布局档位的交集；摄像头关闭时通过SET_RESOLUTION修改下次采集尺寸，UI以带请求ID的回执为准。NPZ仍原样校验，不缩放Q/map；不匹配时仅显示原始第一目，禁用距离。

**技术：** PyQt5、OpenCV、现有TCP stereo-relay-v1扩展（保持向后兼容）。

## 方案取舍

只缩放UI不能改变真实分辨率；硬编码所有UVC档位会混入原生单目，均不采用。采用板端能力查询，并只放行已知横拼档位640×240/1280×480/1600×600/2560×720/3200×1200。相机忙、录像中、等待确认时禁止修改，避免自动重启及混合尺寸录像。

## 实施顺序

1. 备份ui/stereo_camera_widget.py、stereo/calculation.py、Pico stereo_stream.py及文档到根tmp/stereo_resolution_20261026_0111/backup；板端原文件读取后与本地MD5比较，已一致。
2. 新建tests/test_stereo_resolution.py及docs/local-stereo/ref/test_resolution.py：能力过滤、真实尺寸、开相机拒绝、失败/超时/重连、标定不匹配及单目预览。先运行确认缺失功能失败。
3. 修改Pico stereo_stream.py：只读v4l2枚举，增加关机态SET_RESOLUTION和明确回执，打开后读回实际尺寸。保持曝光/增益/发送上限/不测距不变。
4. 修改stereo/calculation.py增加无标定单目预览；修改UI增加紧凑下拉和应用按钮、当前采集/每目尺寸、状态守卫。切换成功清除旧帧/点/距离，禁用不匹配NPZ测距。
5. 新建ref/verify_stereo_resolution.py，以合成同步双目和临时QSettings做真实Windows窗口及截图验收；运行全部非交互tests和板端协议单测，AST/docstring/UTF8检查。
6. 板端已有活跃视频/控制连接：不重启当前服务或抢相机。只在文件未变化时备份并部署本轮relay源码（不热加载），新进程隔离端口验证不打开相机；实际换档须用户保存数据后重启视频服务再验收，不能宣称已实机采集成功。
7. 同步GroundStation README/docs索引、Pico README/launch说明、根docs/local-stereo、正式报告/两级索引、finding和长期记忆。只提交本任务文件，不提交个人JSON/stereo_param，不自动push。

## 验收命令

在src/GroundStation，agentscope环境执行：

```powershell
python -X utf8 -c "import stereo_runtime; import pytest; raise SystemExit(pytest.main(['-q','tests/test_stereo_resolution.py']))"
python -X utf8 ref/verify_stereo_resolution.py --output ../../tmp/stereo_resolution_20261026_0111/windows
python -X utf8 -c "import stereo_runtime; import pytest; raise SystemExit(pytest.main(['-q','tests','--ignore=tests/test_opengl.py','--ignore=tests/test_fish_model.py']))"
```

预期：新测试与回归全通过；窗口有可用档位/每目尺寸和关闭后应用提示，无横向溢出；无标定仅单目预览、截图仍一目。真实相机占用时不运行采集测试。
