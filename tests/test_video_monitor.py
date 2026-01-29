# UI改造完成测试
import sys
sys.path.append('d:\\Documents\\Study\\Code\\py\\GroundStation')

from PyQt5.QtWidgets import QApplication
from ui.video_display import VideoMonitorWidget

app = QApplication(sys.argv)
widget = VideoMonitorWidget()
widget.show()

print("测试VideoMonitorWidget创建成功")
print(f"标签页数量: {widget.tabs.count()}")
print(f"标签页1: {widget.tabs.tabText(0)}")
print(f"标签页2: {widget.tabs.tabText(1)}")

widget.close()
print("✓ UI改造测试通过")
