#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
替换visualization.py中的_create_fish_3d_model方法

将219-314行替换为新代码
"""

import re

# 读取原文件
with open(r'd:\Documents\Study\Code\py\GroundStation\ui\visualization.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 读取新方法代码
with open(r'd:\Documents\Study\Code\py\GroundStation\fish_model_new.txt', 'r', encoding='utf-8') as f:
    new_method = f.read()

# 替换：删除219-314行，插入新代码
new_lines = lines[:218] + [new_method + '\n'] + lines[314:]

# 写回文件
with open(r'd:\Documents\Study\Code\py\GroundStation\ui\visualization.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("✓ 已成功替换_create_fish_3d_model方法")
print(f"原文件已备份到 visualization.py.backup")
