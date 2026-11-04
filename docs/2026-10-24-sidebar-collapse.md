# 右侧栏收起与展开

右侧运行状态栏占用画布空间时，点击栏左上角的向右箭头；整栏向右收起，只留下28逻辑像素的窄条。点击最右侧的向左箭头恢复。按钮也支持Tab聚焦后按空格。

收起只隐藏页面，不断开深度反馈、控制、视频或其他服务。当前标签页及日志保留；反复点击不会创建重复服务。展开优先恢复收起前宽度，窗口很窄时按剩余空间约束。左右分隔条仍可在展开时拖动。

收起状态和展开宽度按dual/single分别保存在原QSettings（FishRobot/GroundStation）中：`layout/right_sidebar_collapsed/<variant>`与`layout/main_splitter/<variant>`。每次收放和退出保存，下次打开恢复；不会自动连接机器鱼。切换并联双闭环时仍保持右栏收起。

## 离线复现

不需要硬件接线，不启动原有地面站实例的连接或控制。在地面站目录运行，输出目录须不存在：

```powershell
conda activate agentscope
python ref/verify_sidebar_collapse.py --output ../../tmp/sidebar-verify-new
```

预期：自动显示未连接窗口，依次保存`expanded.png`、`collapsed.png`、`reopened.png`及`summary.json`。本次实际分割宽度依次为`[420,600,300]`、`[420,872,28]`、`[420,600,300]`；重启恢复、空格展开和个人配置SHA均通过。窗口自动退出，测试使用临时INI，不修改个人连接/PID/手柄配置。证据见仓库`docs/test-reports/pico/sidebar_collapse_20261024/report.md`。
