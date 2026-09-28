#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼地面站控制系统主程序
Fish Robot Ground Station Control System

启动时先选择机器鱼版本（双尾双目鱼 / 单尾单目鱼），
再按版本加载对应的主窗口（视频、通信对象与控制面板不同）。
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtCore import Qt

# 添加项目路径到系统路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ui.fish_variant_dialog import FishVariantDialog
from ui.main_window import MainWindow

def main():
    """主函数：先选版本，再启动对应配置的主窗口。"""
    # 在创建QApplication之前设置高DPI属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # 版本选择对话框
    dialog = FishVariantDialog()
    if dialog.exec_() != QDialog.Accepted or not dialog.selected_variant:
        print("未选择机器鱼版本，退出")
        return

    # 创建主窗口（按变体加载不同视频页/通信默认值）
    main_window = MainWindow(variant=dialog.selected_variant)
    main_window.show()

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
