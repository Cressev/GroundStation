#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试3D鱼形模型显示
"""

import sys
import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import pyqtgraph.opengl as gl

print("创建应用...")
app = QApplication(sys.argv)

print("创建3D视图...")
view = gl.GLViewWidget()
view.setWindowTitle('3D鱼形模型测试')
view.setCameraPosition(distance=5, elevation=30, azimuth=45)
view.setBackgroundColor('w')
view.resize(800, 600)

print("添加坐标网格...")
grid = gl.GLGridItem()
grid.scale(1, 1, 1)
view.addItem(grid)

print("添加坐标轴...")
axis = gl.GLAxisItem()
axis.setSize(2, 2, 2)
view.addItem(axis)

print("创建鱼形模型...")
# 鱼身体顶点
body_length = 1.5
body_width = 0.4
body_height = 0.3

verts = np.array([
    # 鱼头 (尖端)
    [body_length/2, 0, 0],
    # 鱼身体上部
    [body_length/4, body_width/2, body_height/2],
    [body_length/4, -body_width/2, body_height/2],
    [-body_length/4, body_width/2, body_height/2],
    [-body_length/4, -body_width/2, body_height/2],
    # 鱼身体下部
    [body_length/4, body_width/2, -body_height/2],
    [body_length/4, -body_width/2, -body_height/2],
    [-body_length/4, body_width/2, -body_height/2],
    [-body_length/4, -body_width/2, -body_height/2],
    # 尾巴根部
    [-body_length/2, 0, 0],
    # 尾巴尖端
    [-body_length/2 - 0.4, 0.3, 0],
    [-body_length/2 - 0.4, -0.3, 0],
], dtype=float)

print(f"顶点数量: {len(verts)}")
print(f"顶点范围: X[{verts[:,0].min():.2f}, {verts[:,0].max():.2f}], Y[{verts[:,1].min():.2f}, {verts[:,1].max():.2f}], Z[{verts[:,2].min():.2f}, {verts[:,2].max():.2f}]")

# 三角面定义
faces = np.array([
    # 头部
    [0, 1, 2], [0, 2, 6], [0, 6, 5], [0, 5, 1],
    # 上表面
    [1, 3, 4], [1, 4, 2],
    # 下表面
    [5, 6, 8], [5, 8, 7],
    # 右侧
    [1, 5, 7], [1, 7, 3],
    # 左侧
    [2, 4, 8], [2, 8, 6],
    # 后部
    [3, 7, 8], [3, 8, 4],
    # 尾巴
    [9, 10, 11],
    [3, 9, 10], [4, 9, 11],
    [7, 9, 10], [8, 9, 11],
], dtype=np.uint32)

print(f"面数量: {len(faces)}")

# 颜色
colors = np.ones((len(faces), 4))
colors[:, 0] = 0.4  # R
colors[:, 1] = 0.6  # G
colors[:, 2] = 0.9  # B
colors[:, 3] = 0.8  # Alpha

print("创建网格...")
try:
    fish_mesh = gl.GLMeshItem(
        vertexes=verts,
        faces=faces,
        faceColors=colors,
        smooth=True,
        drawEdges=True,
        edgeColor=(0, 0, 0.5, 1)
    )
    view.addItem(fish_mesh)
    print("✓ 鱼形网格创建成功")
except Exception as e:
    print(f"✗ 鱼形网格创建失败: {e}")
    import traceback
    traceback.print_exc()

print("添加方向箭头...")
arrow_verts = np.array([
    [body_length/2 + 0.1, 0, 0],
    [body_length/2 + 0.6, 0, 0],
])
direction_line = gl.GLLinePlotItem(
    pos=arrow_verts,
    color=(1, 0, 0, 1),
    width=4,
    antialias=True
)
view.addItem(direction_line)

print("\n显示窗口...")
print("窗口应该显示: 坐标网格、坐标轴、蓝色鱼形模型、红色箭头")
print("可以用鼠标拖拽旋转视角")
print("窗口将在10秒后自动关闭...")

view.show()

# 10秒后自动关闭
QTimer.singleShot(10000, app.quit)
app.exec_()

print("\n测试完成")
