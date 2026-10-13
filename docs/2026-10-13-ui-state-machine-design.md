# 地面站 UI 状态机设计（2026-10-13）

## 目标

解决主连接、视频服务、摄像头、深度流和控制器分别修改控件状态造成的竞态。每组控件只由一个
集中刷新函数决定，网络线程只报告事实，不直接猜测最终状态。

## 依赖关系

```text
主控制连接 connected
├─ 视频服务 connected
│  └─ 摄像头 confirmed on
│     ├─ 本地录制
│     └─ 板上录制
├─ 深度数据流 connected
└─ 总控制 armed
   └─ 当前控制器 active
      └─ 深度 PID 可启用（仅深度控制器）
```

当前版本的双目测距入口由 `STEREO_RANGING_UI_ENABLED=False` 固定关闭。程序保留协议代码，
但正常 UI 路径不会发送 `RANGE_ON`。

## 状态与规则

| 对象 | 状态 | 核心规则 |
|---|---|---|
| 主连接 | disconnected / connecting / connected / disconnecting | 连接中禁用地址和档案编辑；只有 connected 放行从属连接和总控制 |
| 视频服务 | locked / disconnected / connecting / connected / disconnecting / error | 主连接未就绪时为 locked；线程运行与 TCP 成功分开记录；失败后允许重试 |
| 摄像头 | unavailable / querying / off / turning_on / on / turning_off | 开关命令后等待板端回执或首帧，不做乐观反转；等待期间按钮禁用 |
| 深度流 | locked / disconnected / connecting / connected / disconnecting / error | 主连接断开即收拢；连接中快速断开设置取消标记 |
| 总控制 | disarmed / armed | 只有主连接 connected 才能 armed；armed 时禁止切换控制器 |

所有重复操作都先检查当前状态。相同目标状态不重复启动线程、不重复激活控制器，也不重复发送
普通控制命令。主动断开主连接前始终尽力发送一次安全停止帧。

## 时间序列

全局模式的数据源是从最近一次“清除曲线”起累积的完整列表。滑动窗口只在绘图时按用户填写的
秒数取时间范围，绝不改变底层历史。因此从滑动窗口切回全局时会恢复全部曲线，而不是只剩最后
约 10 秒。

## 布局持久化

主分割器首次使用 360/760/280 的左、中、右宽度。关闭窗口时通过 `QSettings` 按 dual/single
分别保存实际宽度；下次启动恢复，并对过小屏幕进行最小宽度约束。

## 验证边界

离线测试覆盖控制器锁定、重复操作、断链收拢、视频失败重试、相机确认状态、全局/滑动曲线和
侧栏持久化。本次没有连接 pico、没有启动摄像头服务，也没有启动双目测距；硬件上的实际按钮
时序仍需用户下次正常使用时观察。
