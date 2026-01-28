#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
替换为改进的鱼形模型
"""

# 读取原文件
with open(r'd:\Documents\Study\Code\py\GroundStation\ui\visualization.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 新的方法代码
new_method = '''    def _create_fish_3d_model(self):
        """创建3D鱼形模型（兼容版）"""
        import pyqtgraph.opengl as gl
        
        # 鱼身体参数
        body_length = 1.2
        body_width = 0.3
        body_height = 0.25
        
        # 创建更流线型的鱼身体（增加顶点让形状更圆滑）
        verts = np.array([
            # 鱼头尖端
            [body_length/2, 0, 0],
            
            # 头部截面（较小）
            [body_length/3, body_width*0.4, body_height*0.3],
            [body_length/3, body_width*0.2, body_height*0.5],
            [body_length/3, -body_width*0.2, body_height*0.5],
            [body_length/3, -body_width*0.4, body_height*0.3],
            [body_length/3, -body_width*0.4, -body_height*0.3],
            [body_length/3, -body_width*0.2, -body_height*0.5],
            [body_length/3, body_width*0.2, -body_height*0.5],
            [body_length/3, body_width*0.4, -body_height*0.3],
            
            # 身体中部（最粗）
            [0, body_width*0.7, body_height*0.5],
            [0, body_width*0.5, body_height*0.8],
            [0, -body_width*0.5, body_height*0.8],
            [0, -body_width*0.7, body_height*0.5],
            [0, -body_width*0.7, -body_height*0.5],
            [0, -body_width*0.5, -body_height*0.8],
            [0, body_width*0.5, -body_height*0.8],
            [0, body_width*0.7, -body_height*0.5],
            
            # 尾部收窄
            [-body_length*0.35, body_width*0.3, body_height*0.2],
            [-body_length*0.35, -body_width*0.3, body_height*0.2],
            [-body_length*0.35, -body_width*0.3, -body_height*0.2],
            [-body_length*0.35, body_width*0.3, -body_height*0.2],
            
            # 尾巴根部
            [-body_length/2, 0, 0],
            
            # 月牙形尾巴上叶
            [-body_length/2 - 0.15, 0, 0.15],
            [-body_length/2 - 0.3, 0, 0.25],
            [-body_length/2 - 0.4, 0, 0.2],
            
            # 尾巴尖端
            [-body_length/2 - 0.45, 0, 0],
            
            # 月牙形尾巴下叶
            [-body_length/2 - 0.4, 0, -0.2],
            [-body_length/2 - 0.3, 0, -0.25],
            [-body_length/2 - 0.15, 0, -0.15],
        ], dtype=float)
        
        # 定义三角面
        faces = []
        
        # 头部锥形（0是尖端，1-8是第一圈）
        for i in range(1, 9):
            next_i = i + 1 if i < 8 else 1
            faces.append([0, i, next_i])
        
        # 第一圈到第二圈（1-8 到 9-16）
        for i in range(8):
            curr = i + 1
            next = (i + 1) % 8 + 1
            curr2 = i + 9
            next2 = (i + 1) % 8 + 9
            faces.append([curr, curr2, next2])
            faces.append([curr, next2, next])
        
        # 第二圈到第三圈（9-16 到 17-20）
        faces.extend([
            [9, 17, 10], [10, 17, 18], [10, 18, 11],
            [11, 18, 19], [11, 19, 12], [12, 19, 13],
            [13, 19, 20], [13, 20, 14], [14, 20, 15],
            [15, 20, 17], [15, 17, 16], [16, 17, 9],
        ])
        
        # 第三圈到尾根（17-20 到 21）
        faces.extend([
            [17, 21, 18], [18, 21, 19],
            [19, 21, 20], [20, 21, 17],
        ])
        
        # 尾巴上叶（21-22-23-24-25）
        faces.extend([
            [21, 22, 23], [21, 23, 24],
            [21, 24, 25],
        ])
        
        # 尾巴下叶（21-28-27-26-25）
        faces.extend([
            [21, 28, 27], [21, 27, 26],
            [21, 26, 25],
        ])
        
        faces = np.array(faces, dtype=np.uint32)
        
        # 橙红色锦鲤配色
        colors = np.ones((len(faces), 4))
        colors[:, 0] = 0.9   # R
        colors[:, 1] = 0.45  # G
        colors[:, 2] = 0.15  # B
        colors[:, 3] = 0.95  # Alpha
        
        # 尾巴颜色稍深
        tail_start_face = len(faces) - 6
        colors[tail_start_face:, 0] = 0.8
        colors[tail_start_face:, 1] = 0.35
        colors[tail_start_face:, 2] = 0.1
        
        # 创建鱼身网格（不使用shader参数）
        self.fish_mesh = gl.GLMeshItem(
            vertexes=verts,
            faces=faces,
            faceColors=colors,
            smooth=True,
            drawEdges=False  # 不画边缘更光滑
        )
        self.gl_widget.addItem(self.fish_mesh)
        
        # 方向箭头
        arrow_verts = np.array([
            [body_length/2 + 0.1, 0, 0],
            [body_length/2 + 0.5, 0, 0],
        ])
        self.direction_line = gl.GLLinePlotItem(
            pos=arrow_verts,
            color=(1, 0, 0, 1),
            width=4,
            antialias=True
        )
        self.gl_widget.addItem(self.direction_line)
        
        # 箭头尖
        arrow_head = np.array([
            [body_length/2 + 0.5, 0, 0],
            [body_length/2 + 0.35, 0.08, 0],
            [body_length/2 + 0.35, -0.08, 0],
            [body_length/2 + 0.5, 0, 0],
        ])
        self.arrow_head = gl.GLLinePlotItem(
            pos=arrow_head,
            color=(1, 0, 0, 1),
            width=4,
            antialias=True,
            mode='line_strip'
        )
        self.gl_widget.addItem(self.arrow_head)
'''

# 找到方法开始和结束位置
import re
pattern = r'    def _create_fish_3d_model\(self\):.*?(?=\n    def |\nclass |\Z)'
match = re.search(pattern, content, re.DOTALL)

if match:
    new_content = content[:match.start()] + new_method + '\n' + content[match.end():]
    
    # 写回文件
    with open(r'd:\Documents\Study\Code\py\GroundStation\ui\visualization.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("✓ 成功替换为改进的鱼形模型")
else:
    print("✗ 未找到方法")
