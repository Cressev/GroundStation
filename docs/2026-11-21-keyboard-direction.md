# 双尾鱼键盘左右方向修复计划与说明

目标：根据用户实体测试，反转双尾鱼键盘左右转向；不修改Pico/STM32、Xbox、单尾鱼或自动实验的原始带符号参数。用户当前窗口不强制退出，不发送运动指令。

设计：不在串口桥或全局偏置处反号，避免影响其他控制器；键盘控制器新增构造参数turn_direction（默认1保留旧行为），主窗口仅双尾传-1。反转的是相对基础偏置的转向增量与κ左右取值，基础校准偏置不反号。UI仍显示A左/D右，自动实验直接数值语义不变。

实施与验证：

1. 当前源码、分支及用户脏文件已核对；备份到项目根tmp/keyboard_direction_fix_20261121_2344。
2. 新建无网络回归，覆盖快慢/Shift写法、三种模式、基础偏置、停止/前进、胸鳍、自动实验与单尾，先红后绿。
3. 修改controllers/base.py与ui/main_window.py，修正κ提示，保留既有逻辑状态与显示标签。
4. 实例化真实主窗口及发送器，用假通信/假socket验证发送JSON，绝不连Pico或启动尾摆；回归现有键盘/κ/控制轴/自主/Xbox/状态机。
5. 更新本README及上级索引，中文提交并推送原feature/dual-fish-stereo分支，暂存仅本次文件。

生效方式：停止控制、保存数据后重开地面站；无需重启Pico或烧录STM32。修复后双尾键盘A/a使用基础偏置+转向量、D/d使用基础偏置−转向量；三模式中的κ为左1−设定值、右设定值，前进/停止κ0.5。κ实际水动力方向仍取决于设定值和鱼体，不承诺未经现场复测的转向效果。

验证结果：新增tests/test_keyboard_direction.py 9项通过（修改前8失败/1通过），覆盖快慢/Shift写法、三模式JSON、主窗口采用新方向与标签、原自动实验数值及单尾方向；现有turn_modes/tail_kappa/keyboard_parameters/control_axes/autonomous_controller/ui_state_machine共83项通过。测试采用qt5真实Qt/生产类、假通信和假socket，不接Pico，不启动尾摆，不操作用户当前窗口。agentscope用于语法/UTF-8与文件校验，qt5用于匹配实际地面站Qt运行环境。完整报告位于项目根docs/test-reports/pico/keyboard_direction_20261121/report.md，原始证据与备份位于项目根tmp/keyboard_direction_fix_20261121_2344。
