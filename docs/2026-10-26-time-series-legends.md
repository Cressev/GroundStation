# 时间序列优先与紧凑左上图例

数据可视化页依次为时间序列、XY轨迹图、姿态显示、系统状态，默认进入时间序列。系统状态仍第4页，全部页面保留。

用户截图中的“图标”指曲线图例。本轮只改深度-时间、姿态角-时间两图：8pt文字、16×14逻辑像素样例、3像素样例文字间距、去文字文档内边距，锚定绘图区左上角内缩6逻辑像素。窗口缩放、坐标视域变化不改变锚点；字体/DPI会影响实际物理尺寸。半透明深色底使曲线穿过时仍能辨认名称。

深度6个名称、姿态3个名称和曲线颜色均保留；点击图例线段仍隐藏/显示对应曲线。XY图例、标题、坐标轴、操作按钮、数据采集、全局/滑动模式、CSV/Excel/PNG保存逻辑不变。

保存当前曲线/录像后自行重开地面站生效；不需重启Pico。代理未重启用户窗口，未连接或修改板端。

227项地面站非交互回归通过，新增3项覆盖顺序/图例尺寸锚定/点击显隐；原全局历史、滑动、范围CSV/XLSX保持通过。真实Windows合成数据在1200和760宽时两个图例均位于(6,6)，本机深度约73×132、姿态约63×69逻辑像素；缩放到7.2—12.8秒只导出8—12秒5行。中文完整、PNG可保存，4份个人JSON散列保持。未采集真实传感器或网络。

复现（src/GroundStation，agentscope）：

```powershell
python -X utf8 -c "import stereo_runtime; import pytest; raise SystemExit(pytest.main(['-q','tests/test_visualization_time_modes.py']))"
python -X utf8 ref/verify_time_series_layout.py --output ../../tmp/time_legend_另一新目录
```

预期7项目标通过，输出summary.json、1200/760窗口图、单图截图、画布PNG及5行CSV；sockets_opened=false。已有OpenGL网格法线warning与本任务无关，不作为失败，也不顺带修改。原始证据和备份在根tmp/time_legend_20261026_1011/，正式报告在根docs/test-reports/pico/time_legend_20261026_1011/report.md。
