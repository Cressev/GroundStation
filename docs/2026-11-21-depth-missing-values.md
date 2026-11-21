# 深度单路失效时的显示与容错

第一路WF5803无应答时，Pico将该路NaN转换为JSON null。这不是0cm，也不是健康第二路停止；融合数据仍可能有效。旧面板对None使用`:.1f`格式化，导致每条消息触发TypeError，并中断后续标签/记录更新。

本次修复：

- None、缺字段、坏类型、布尔值、NaN、Infinity和无法转换的大数都显示“无数据”，不补零。
- 双路消息的原始和滤波标签按1路、2路分行，保证窄侧栏读数完整；融合及大字深度仍使用服务端融合值，不偷偷重算或改传感器映射。
- 标定只收有限融合值；CSV保持原列顺序，缺失项为空，健康融合值继续记录。没有改变零点文件、单位、控制器或连接逻辑。
- 旧单路消息保留原有显示。通道恢复时立即显示有效值，不需要重新连接。

修改文件：`ui/depth_panel.py`。新增专项回归`tests/test_depth_missing_values.py`，隔离Windows Qt验证工具`ref/verify_depth_missing_values.py`，计划`docs/plans/2026-11-21-depth-null-values.md`。

## 验证

agentscope/qt5环境14项专项均通过；qt5专项加连接布局、主状态机、侧栏回归42项通过。用真实Windows Qt重放此前从Pico采集的50条单路失效消息，经过QueuedConnection回调，记录50条、Qt槽异常0；个人参数/连接文件SHA前后不变。还检查了双路缺失和恢复的渲染。没有连接或驱动硬件；不能据此宣称第一只传感器已修好。

在地面站目录，激活agentscope后运行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -c "import stereo_runtime,pytest; raise SystemExit(pytest.main(['-q','tests/test_depth_missing_values.py']))"
```

实际qt5隔离窗口验证（输出目录必须新建且不能已存在）：

```powershell
$env:QT_QPA_PLATFORM='windows'
& 'D:\Programs\anaconda\envs\qt5\python.exe' ref/verify_depth_missing_values.py --output 'D:\Documents\Study\codex-fish\tmp\depth_missing_demo_new'
```

默认使用100条合成消息；`--replay 文件.jsonl`可替换为带payload字段的既有depth日志。输出first_missing.png、both_missing.png、recovered.png及result.json，不读取/覆盖真实零点，不建立网络连接。

## 生效与仍存在的问题

先停止控制、保存数据，再重启地面站加载新代码；不用为本次UI修复重启Pico。不要擅自关闭用户当前窗口。

板上`[wf5803] sensor_1 read failed`是另一层真实I2C故障告警，不是UI的None格式化异常。最初网口断开；用户恢复SSH后核对当前src/install节点一致并双侧备份，板端仅修改故障日志：每路首次告警、持续失败每30秒汇总、恢复提示一次，读取/重试和零点不变。没有隐藏真实故障，也不在本地UI仓库内交付ROS代码。新boot再次读取I2C3第二路100/100成功、I2C8第一路0/100；此前0x6D也无应答。原因需断电交叉单只传感器/线束测试，不能仅凭这些日志判定传感器损坏。两只同为0x6C但位于不同总线，不构成地址冲突。
