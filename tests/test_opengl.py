#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试PyQtGraph OpenGL是否可用
"""

print("测试开始...")

try:
    print("1. 测试PyQt5导入...")
    from PyQt5.QtWidgets import QApplication
    print("   ✓ PyQt5导入成功")
except Exception as e:
    print(f"   ✗ PyQt5导入失败: {e}")
    exit(1)

try:
    print("2. 测试PyQtGraph导入...")
    import pyqtgraph as pg
    print("   ✓ PyQtGraph导入成功")
except Exception as e:
    print(f"   ✗ PyQtGraph导入失败: {e}")
    exit(1)

try:
    print("3. 测试PyOpenGL导入...")
    import OpenGL
    print(f"   ✓ PyOpenGL导入成功，版本: {OpenGL.__version__}")
except Exception as e:
    print(f"   ✗ PyOpenGL导入失败: {e}")
    exit(1)

try:
    print("4. 测试PyQtGraph OpenGL模块导入...")
    import pyqtgraph.opengl as gl
    print("   ✓ PyQtGraph OpenGL模块导入成功")
except Exception as e:
    print(f"   ✗ PyQtGraph OpenGL模块导入失败: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

try:
    print("5. 测试创建QApplication...")
    import sys
    app = QApplication(sys.argv)
    print("   ✓ QApplication创建成功")
except Exception as e:
    print(f"   ✗ QApplication创建失败: {e}")
    exit(1)

try:
    print("6. 测试创建GLViewWidget...")
    view = gl.GLViewWidget()
    view.setWindowTitle('OpenGL测试')
    view.show()
    print("   ✓ GLViewWidget创建成功")
    print("\n如果看到3D窗口，说明OpenGL工作正常！")
    print("正在显示窗口3秒...")
    
    from PyQt5.QtCore import QTimer
    QTimer.singleShot(3000, app.quit)
    app.exec_()
    print("   ✓ 测试完成，OpenGL工作正常")
    
except Exception as e:
    print(f"   ✗ GLViewWidget创建失败: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n✓✓✓ 所有测试通过！OpenGL可用 ✓✓✓")
