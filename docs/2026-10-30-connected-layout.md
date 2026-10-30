# 连接后底部显示不全：修复与使用

连接后，右栏的状态文字、深度值和隐藏按键页会增加最小高度。旧布局没有整体滚动，主窗口因此被强制撑大，底部越过屏幕。隐藏的图像增强页也会给中央区域施加最小高度。

现在右栏可独立上下滚动，极窄时横向滚动；连接/标定/记录状态放在按钮下方整行，三个深度值纵排，不挤成竖字。时间序列双图完整保留，可滚动查看下图；保存图像仍保存完整画布，不把工具栏/滚动条截入，保存数据仍按真实时间范围。左侧参数区最小可视高度可缩至120，顶部“全部停止”仍不跟参数一起滚走。增强页也可滚动，不改变视频源或计算逻辑。

## 生效方法

1. 停止航向/深度控制，保存需要的曲线和记录。
2. 关闭并重新打开地面站，选择原鱼体版本，按原IP/端口连接。
3. 窗口较短时，在右栏或时间序列画布区域滚动查看；右栏顶部箭头仍可收起/展开，保留宽度记忆。

只修改电脑UI，不重启Pico/传感器/相机服务，不重置深度零点、PID参数、连接档案或已保存布局。

## 文件与验证

- `ui/main_window.py`：右栏/增强页滚动容器、120高度的参数滚动区及幂等收放。
- `ui/depth_panel.py`：全宽状态文字、纵排数值；没有改单位/零点/记录/通信。
- `ui/visualization.py`：以滚动区承载原time_series_canvas，图高不小于150、整体不小于400。
- `tests/test_connected_layout.py`：7项参数化布局/可达性/收放检查，无真实连接。
- `ref/verify_connected_layout.py`：真实Windows Qt多尺寸截图和几何JSON，假反馈、假手柄、临时QSettings，断言个人JSON未改；--baseline参数可在内存加载备份代码进行对照。
- `docs/plans/2026-10-30-connected-layout.md`：实施与安全边界。

操作目的：只用假反馈验证新布局；预期1280×720/1100×650不被强制撑高，生成PNG/metrics.json；2026-10-30实测通过。

```powershell
cd D:\Documents\Study\codex-fish
conda activate agentscope
python src/GroundStation/ref/verify_connected_layout.py --output tmp/layout_check_new --assert-fit
```

[完整测试报告、对照图及旧测试问题](../../../docs/test-reports/pico/ui_connected_layout_20261030_1708/report.md)。
