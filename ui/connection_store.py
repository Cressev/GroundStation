#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连接档案持久化模块。

用本地 JSON 文件（connections.json，与程序同目录）记录常用连接：
每条为 {"remark": 备注, "ip": 地址, "port": 端口}。
不使用数据库；文件读写即完成持久化。IP 很少变动，保存后下拉直选。
"""

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "connections.json"


class ConnectionStore:
    """连接档案存取（本地 JSON）。"""

    def __init__(self, path=None):
        """path 为空则用程序目录下 connections.json。"""
        self.path = Path(path) if path else DEFAULT_PATH
        self.entries = []
        self.load()

    def load(self):
        """读取 JSON 文件；文件缺失或损坏时置空列表。"""
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = []
        if not isinstance(self.entries, list):
            self.entries = []

    def save(self):
        """写回 JSON 文件。"""
        self.path.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def add(self, remark, ip, port):
        """新增/更新一条连接（同 ip+port 视为同条，更新备注并置顶）。"""
        remark = (remark or "").strip()
        ip = (ip or "").strip()
        port = int(port)
        self.entries = [e for e in self.entries
                        if not (e.get("ip") == ip and e.get("port") == port)]
        self.entries.insert(0, {"remark": remark, "ip": ip, "port": port})
        self.save()

    def remove(self, index):
        """按序号删除一条连接。"""
        if 0 <= index < len(self.entries):
            del self.entries[index]
            self.save()
