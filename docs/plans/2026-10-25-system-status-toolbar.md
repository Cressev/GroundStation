# 系统状态顶部工具栏简化实施计划

目标：按用户截图删除“实验标签”“数据导出范围”两整行，四个操作按钮并入时间模式所在的顶部一行。

架构：仅改电脑端PyQt5的SystemStatusWidget及对应测试/离线验证。保留独立画布、历史存储和可见范围CSV/Excel导出；无范围下拉后采用最近手动缩放/拖动或重置的画布，初始/全部重置时以CPU图为参照，保存按钮提示明确当前参照。常规宽度单行，窄窗口仅工具栏自动换行，不扩宽整页。

技术栈：PyQt5、pyqtgraph、pytest，指定agentscope解释器，Qt复用现有qt5包路径。用户已明确授权实施，不另开会话/工作树，不操作当前鱼连接。

## 方案选择

- 不采用只隐藏输入框：会留下无效控件和旧依赖，无法彻底清理布局。
- 不固定导出全历史或固定CPU范围：会与用户正在手动查看的独立画布不符。
- 采用删除控件＋自动跟随最近手动查看画布，保存入口不增加新的下拉菜单。CSV/XLSX删除实验标签condition列，其余遥测单位/来源/会话/缺口字段保持。

## 步骤一：备份与失败测试

文件：ui/system_status.py、tests/test_system_status.py、ref/verify_system_status.py、docs/2026-10-23-system-status.md、README.md。

1. 读取当前代码/既有用户dirty状态；代码和文档已备份到仓库外tmp/system_status_toolbar_20261025_2024/backup/，不改Pico。
2. 为无标签/无范围下拉、常规宽度同排、窄屏不越界、自动导出参照和元数据列删除增加回归。
3. 先执行tests/test_system_status.py，预期新断言失败，再实现。

## 步骤二：实现最小改动

1. 删除QLineEdit/NoWheelComboBox及其整行布局、采样condition字段和导出列。
2. 顶部布局由时间模式组＋四按钮组组成；用两列Grid正常同行，必要时同一个工具栏换行；三画布滚动结构不变。
3. 手动画布范围或重置此图更新导出参照和保存按钮tooltip，模式切换/重置全部/清除回CPU默认。只读实际ViewBox范围，不改其他图，也不截断历史。

## 步骤三：验证与文档

1. 相关单元/状态机回归：pytest tests/test_system_status.py及受影响控制/时序/视频/侧栏测试；随后执行适用全套，硬件/OpenGL环境测试如不适用须明确记录。
2. 更新ref/verify_system_status.py，在真实Windows窗口以合成数据验收1100宽同行、640宽换行、滚动与CSV/XLSX/PNG；禁止真实网络/硬件连接，不改个人JSON/注册表。
3. AST/docstring、UTF-8字节及文件差异验收；同步README和页面手册，记录finding/长期记忆。最终只提交任务相关文件，不包含个人JSON、NPZ或原始大日志；不自动push。

执行入口：在本地当前会话按以上顺序推进，不需要用户重复确认已给出的截图规格。
