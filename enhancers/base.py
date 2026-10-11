"""神经网络增强器公共接口与图像尺寸转换工具。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import cv2
import numpy as np


class EnhancerError(RuntimeError):
    """表示模型配置、加载或推理阶段的可恢复错误。"""


@dataclass(frozen=True)
class ResizeMetadata:
    """记录等比例缩放与补边信息，用于恢复原始图像尺寸。"""

    original_width: int
    original_height: int
    resized_width: int
    resized_height: int
    left: int
    top: int


def letterbox(image, target_width, target_height):
    """等比例缩放 BGR 图像并使用反射像素补到目标尺寸。"""
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise EnhancerError("输入图像尺寸无效")
    scale = min(target_width / width, target_height / height)
    resized_width = max(1, min(target_width, round(width * scale)))
    resized_height = max(1, min(target_height, round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(
        image, (resized_width, resized_height), interpolation=interpolation)
    left = (target_width - resized_width) // 2
    right = target_width - resized_width - left
    top = (target_height - resized_height) // 2
    bottom = target_height - resized_height - top
    border_mode = cv2.BORDER_REFLECT_101 if min(height, width) > 1 else cv2.BORDER_REPLICATE
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, border_mode)
    metadata = ResizeMetadata(
        original_width=width,
        original_height=height,
        resized_width=resized_width,
        resized_height=resized_height,
        left=left,
        top=top,
    )
    return padded, metadata


def restore_letterbox(image, metadata):
    """移除补边并把模型输出恢复到原始图像尺寸。"""
    cropped = image[
        metadata.top:metadata.top + metadata.resized_height,
        metadata.left:metadata.left + metadata.resized_width,
    ]
    return cv2.resize(
        cropped,
        (metadata.original_width, metadata.original_height),
        interpolation=cv2.INTER_CUBIC,
    )


def split_frames(image, stereo_pair):
    """按需把左右目横向画面拆成两个独立帧。"""
    if not stereo_pair:
        return [image]
    width = image.shape[1]
    if width % 2:
        raise EnhancerError(f"双目画面宽度必须为偶数，当前为 {width}")
    midpoint = width // 2
    return [image[:, :midpoint], image[:, midpoint:]]


def join_frames(frames, stereo_pair):
    """把增强后的左右目恢复为横向双目画面。"""
    if stereo_pair:
        if len(frames) != 2:
            raise EnhancerError("双目推理输出数量不是 2")
        return np.hstack(frames)
    if len(frames) != 1:
        raise EnhancerError("单目推理输出数量不是 1")
    return frames[0]


class BaseModelEnhancer(ABC):
    """统一神经网络增强器生命周期和推理接口。"""

    model_id = "base"
    display_name = "Base"

    def __init__(self):
        """初始化尚未加载的模型状态。"""
        self.loaded = False
        self.device_description = "未加载"
        self.input_description = "--"

    @abstractmethod
    def load(self):
        """加载模型结构、权重并完成必要预热。"""

    @abstractmethod
    def process(self, bgr_frame, stereo_pair=False):
        """增强一张 BGR 图像或横向拼接的左右目图像。"""

    def close(self):
        """释放模型资源；子类可覆盖以主动清理显存。"""
        self.loaded = False

    def status_text(self):
        """返回适合 UI 展示的设备和输入尺寸摘要。"""
        return (
            f"{self.display_name} 就绪 | {self.device_description} | "
            f"模型输入 {self.input_description}"
        )
