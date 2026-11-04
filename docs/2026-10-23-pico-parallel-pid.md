# Pico本机单环与并联双环定深

## 计算位置

最终架构：单双环均在Pico计算，电脑只调参、启停、显示；WF5803/IMU不经电脑往返参与闭环。
公式：PWM=限幅(中位+深度方向×深度PID输出+俯仰方向×俯仰PID输出)。两个目标独立，不是串级。
正式UI使用remote_depth.py代理；旧电脑PID类只作离线回归母本，不是正式运行路径。

## 使用步骤与预期

1. 接线不变：Pico原IMU USB串口、WF5803 I2C及到STM32的/dev/ttyS0。未改供电或STM32固件。
   首次整定先隔离舵机供电、核对传感器与极性，不能用软件开关代替硬件安全。
2. Pico按原方式运行`/root/catkin_ws/src/pico_stereo/scripts/start_dual_fish.sh`；电脑重开地面站选双尾鱼并连接。
   本轮未自动启动整机/舵机串口桥/相机，仅运行隔离传感器验收。
3. 深度下拉选单闭环或并联双闭环。双环左深度、右俯仰始终并排；参数区9pt紧凑字号、较小间距，选择时按表单实际宽度收拢侧栏，小屏仍可横向滚动。其他页面字号不变，输出方向缩写的完整含义可悬停查看。
4. 未启动参数置灰、启动可调、运行禁止换类型。启动/应用把参数和深度零点发给Pico，状态应显示“Pico计算”。
   旧服务无兼容回执时超时报错并撤销启动，绝不暗中切回电脑计算。
5. 两列独立设置目标、Kp/Ki/Kd、积分限幅、方向、数据超时；公共设置为中位、PWM上下限及控制周期。
   **两种模式周期都可调50～1000ms，默认100ms=10Hz；250ms=4Hz。** 这是Pico ROS定时器周期，不是UI刷新周期。
   点击应用并保存才下发生效；配置变化清积分并等待新样本。双环默认零增益，单环原设置保留，未照搬旧平台增益。
6. 定深启动后，QE/脉宽设定、Xbox Y/A/RT胸鳍调节与回中被屏蔽，相关控件置灰；尾鳍/转向不受影响。
   航向帧省略胸鳍值，Pico也拒绝旧版手动PWM覆盖。停止后等待Pico实际PWM回执再交手动，避免旧显示值跳变。
7. 全部停止明确停尾、胸鳍回1500μs；X/B撤销两路并保持实际胸鳍。断链停止定深，不自动恢复。

## 单位与失效

- 深度cm、向下正，Pico使用fused−zero_offset；深度面板零点随启动/应用发送。
- 俯仰UI/增益使用度。旧µs/rad增益不能直接当µs/°；俯仰符号和增益尚未实物整定。
- 每环按新样本计算，积分error×真实间隔；首次dt取设置周期，后续限0.001～1秒。重复样本不重复积分。
- 双环任一反馈超时整体回配置中位、清积分并等待两路新样本，不静默降级；单环不依赖IMU。
- 源编号/年龄由本机传感器回调生成，缓存重发不算新反馈；控制和超时使用Pico单调时间，不依赖电脑时钟。
- 参数分开保存在depth_pid_params.json、parallel_depth_pid_params.json，不提交个人值到Git；重启不自动启用。

## 备份与验证

本地备份：tmp/gs_parallel_20261023_1315/backup/；Pico原版：/root/parallel_pid_backup_20261023_1315/。
隔离测试端口19999、ROS_DOMAIN_ID=71、话题/fish/diagnostics/parallel_pid_no_actuators，订阅者为0，无舵机桥。
正式报告：docs/test-reports/pico/parallel_depth_20261023/report.md；原始日志保留上述tmp目录。
GUI复现：进入GroundStation执行`python ref/verify_parallel_depth.py --output ../../tmp/parallel_ui_repeat_NEW`。
预期5场景、two_columns=true、board_commands_sent=0、user_configs_unchanged=true，已有目录拒绝覆盖。
这些是算术、协议、周期和UI验证，不是水中运动效果或PID整定完成的证据。
