#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图形保存工具
Graphics Exporter Tool
"""

import os
import datetime
import matplotlib.pyplot as plt
import matplotlib.backends.backend_qt5agg as backend
from matplotlib.figure import Figure
import numpy as np
from typing import Optional, Dict, List, Any

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QWidget, QFileDialog, QMessageBox
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
import pyqtgraph as pg
from config import RECORD_CONFIG

# 设置英文字体，避免中文字体问题
try:
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False  # 正常显示负号
except:
    # 使用默认字体
    pass

class GraphicsExporter(QObject):
    """图形导出器"""
    
    # 信号定义
    export_completed = pyqtSignal(str)  # 导出完成，参数为文件路径
    export_failed = pyqtSignal(str)     # 导出失败，参数为错误信息
    
    def __init__(self, save_directory: str = None):
        super().__init__()
        
        # 设置保存目录
        if save_directory is None:
            import datetime
            default_dir = f"records/{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.save_directory = default_dir
        else:
            self.save_directory = save_directory
            
        # 确保保存目录存在
        if not os.path.exists(self.save_directory):
            os.makedirs(self.save_directory)
    
    def export_pyqtgraph_plot(self, plot_widget: pg.PlotWidget, filename: Optional[str] = None) -> str:
        """导出PyQtGraph图表"""
        try:
            if filename is None:
                timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
                filename = f"plot_{timestamp}.png"
            
            filepath = os.path.join(self.save_directory, filename)
            
            # 使用PyQtGraph的导出功能
            try:
                # 尝试使用exporters模块
                import pyqtgraph.exporters as exporters
                exporter = exporters.ImageExporter(plot_widget.plotItem)
                exporter.export(filepath)
            except (ImportError, AttributeError):
                # 如果没有exporters模块，使用QPixmap方法
                pixmap = QPixmap(plot_widget.size())
                plot_widget.render(pixmap)
                pixmap.save(filepath)
            
            self.export_completed.emit(filepath)
            return filepath
            
        except Exception as e:
            error_msg = f"导出PyQtGraph图表失败: {str(e)}"
            self.export_failed.emit(error_msg)
            raise Exception(error_msg)
    
    def export_widget_as_image(self, widget: QWidget, filename: Optional[str] = None) -> str:
        """将QWidget导出为图片"""
        try:
            if filename is None:
                timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
                filename = f"widget_{timestamp}.png"
            
            filepath = os.path.join(self.save_directory, filename)
            
            # 创建pixmap并渲染widget
            pixmap = QPixmap(widget.size())
            widget.render(pixmap)
            pixmap.save(filepath)
            
            self.export_completed.emit(filepath)
            return filepath
            
        except Exception as e:
            error_msg = f"导出Widget图片失败: {str(e)}"
            self.export_failed.emit(error_msg)
            raise Exception(error_msg)
    
    def export_data_as_matplotlib(self, data_history: Dict[str, List], 
                                  plot_types: List[str] = None, 
                                  filename: Optional[str] = None) -> str:
        """使用Matplotlib导出数据图表"""
        try:
            if filename is None:
                timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
                filename = f"matplotlib_plots_{timestamp}.png"
            
            filepath = os.path.join(self.save_directory, filename)
            
            if plot_types is None:
                plot_types = ['xy_trajectory', 'z_time', 'rpy_time']
            
            # 准备数据
            times = list(data_history.get('time', []))
            x_data = list(data_history.get('x', []))
            y_data = list(data_history.get('y', []))
            z_data = list(data_history.get('z', []))
            roll_data = list(data_history.get('roll', []))
            pitch_data = list(data_history.get('pitch', []))
            yaw_data = list(data_history.get('yaw', []))
            
            if not times:
                raise ValueError("没有可导出的数据")
            
            # 创建matplotlib图形
            fig = plt.figure(figsize=(15, 10))
            
            # XY轨迹图
            if 'xy_trajectory' in plot_types and x_data and y_data:
                ax1 = plt.subplot(2, 2, 1)
                plt.plot(x_data, y_data, 'b-', linewidth=2, label='Trajectory')
                plt.plot(x_data[-1], y_data[-1], 'ro', markersize=8, label='Current Position')
                plt.xlabel('X Position (m)')
                plt.ylabel('Y Position (m)')
                plt.title('XY Trajectory')
                plt.grid(True)
                plt.legend()
                plt.axis('equal')
            
            # Z-时间图
            if 'z_time' in plot_types and z_data:
                ax2 = plt.subplot(2, 2, 2)
                plt.plot(times, z_data, 'g-', linewidth=2)
                plt.xlabel('Time (s)')
                plt.ylabel('Z Position (m)')
                plt.title('Depth vs Time')
                plt.grid(True)
            
            # RPY-时间图
            if 'rpy_time' in plot_types and roll_data and pitch_data and yaw_data:
                ax3 = plt.subplot(2, 2, 3)
                plt.plot(times, roll_data, 'r-', linewidth=2, label='Roll')
                plt.plot(times, pitch_data, 'm-', linewidth=2, label='Pitch')
                plt.plot(times, yaw_data, 'y-', linewidth=2, label='Yaw')
                plt.xlabel('Time (s)')
                plt.ylabel('Angle (rad)')
                plt.title('Attitude vs Time')
                plt.grid(True)
                plt.legend()
            
            # 3D轨迹图
            if '3d_trajectory' in plot_types and x_data and y_data and z_data:
                ax4 = plt.subplot(2, 2, 4, projection='3d')
                ax4.plot(x_data, y_data, z_data, 'b-', linewidth=2)
                ax4.scatter(x_data[-1], y_data[-1], z_data[-1], c='r', s=50)
                ax4.set_xlabel('X Position (m)')
                ax4.set_ylabel('Y Position (m)')
                ax4.set_zlabel('Z Position (m)')
                ax4.set_title('3D Trajectory')
            
            plt.tight_layout()
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.export_completed.emit(filepath)
            return filepath
            
        except Exception as e:
            error_msg = f"导出Matplotlib图表失败: {str(e)}"
            self.export_failed.emit(error_msg)
            raise Exception(error_msg)
    
    def export_all_plots(self, visualization_widget, filename_prefix: Optional[str] = None) -> List[str]:
        """导出所有图表"""
        exported_files = []
        
        try:
            if filename_prefix is None:
                timestamp = datetime.datetime.now().strftime(RECORD_CONFIG["timestamp_format"])
                filename_prefix = f"all_plots_{timestamp}"
            
            # 导出XY轨迹图
            try:
                xy_file = f"{filename_prefix}_xy_trajectory.png"
                xy_path = self.export_pyqtgraph_plot(visualization_widget.xy_plot, xy_file)
                exported_files.append(xy_path)
            except Exception as e:
                print(f"导出XY图失败: {e}")
            
            # 导出Z-时间图
            try:
                z_file = f"{filename_prefix}_z_time.png"
                z_path = self.export_pyqtgraph_plot(visualization_widget.z_plot, z_file)
                exported_files.append(z_path)
            except Exception as e:
                print(f"导出Z-时间图失败: {e}")
            
            # 导出RPY-时间图
            try:
                rpy_file = f"{filename_prefix}_rpy_time.png"
                rpy_path = self.export_pyqtgraph_plot(visualization_widget.rpy_plot, rpy_file)
                exported_files.append(rpy_path)
            except Exception as e:
                print(f"导出RPY图失败: {e}")
            
            # 导出整个可视化组件
            try:
                widget_file = f"{filename_prefix}_full_view.png"
                widget_path = self.export_widget_as_image(visualization_widget, widget_file)
                exported_files.append(widget_path)
            except Exception as e:
                print(f"导出完整视图失败: {e}")
            
            # 如果有数据，使用matplotlib导出高质量图表
            if hasattr(visualization_widget, 'data_history'):
                try:
                    matplotlib_file = f"{filename_prefix}_matplotlib.png"
                    matplotlib_path = self.export_data_as_matplotlib(
                        visualization_widget.data_history, 
                        filename=matplotlib_file
                    )
                    exported_files.append(matplotlib_path)
                except Exception as e:
                    print(f"导出Matplotlib图表失败: {e}")
            
            return exported_files
            
        except Exception as e:
            error_msg = f"批量导出图表失败: {str(e)}"
            self.export_failed.emit(error_msg)
            raise Exception(error_msg)
    
    def select_save_location(self, parent: QWidget, default_filename: str) -> Optional[str]:
        """选择保存位置"""
        filepath, _ = QFileDialog.getSaveFileName(
            parent,
            "保存图表",
            os.path.join(self.save_directory, default_filename),
            "PNG文件 (*.png);;JPG文件 (*.jpg);;所有文件 (*.*)"
        )
        return filepath if filepath else None
