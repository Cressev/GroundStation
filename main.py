#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器鱼地面站控制系统主程序
Fish Robot Ground Station Control System
"""

import sys
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# 添加项目路径到系统路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import MainWindow

def main():
    """主函数"""
    # 在创建QApplication之前设置高DPI属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    # 创建主窗口
    main_window = MainWindow()
    main_window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
