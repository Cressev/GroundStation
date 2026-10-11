"""Ucolor 的 ONNX Runtime/CUDA 实时流适配器。"""

import gc

import cv2
import numpy as np
from scipy.ndimage import maximum_filter, median_filter, minimum_filter, sobel

from .base import (BaseModelEnhancer, EnhancerError, join_frames, letterbox,
                   restore_letterbox, split_frames)
from .model_paths import ucolor_onnx_path


def estimate_gdcp_transmission(rgb, window=15):
    """按 Ucolor 随附 MATLAB 流程估算单通道 GDCP 透射率图。"""
    luminance = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gradient_x = sobel(luminance, axis=1, mode="reflect")
    gradient_y = sobel(luminance, axis=0, mode="reflect")
    gradient = np.hypot(gradient_x, gradient_y)
    gradient = maximum_filter(gradient, size=window, mode="reflect")
    gradient -= gradient.min()
    gradient /= max(float(gradient.max()), 1e-8)
    rough_depth = 1.0 - gradient

    design = np.stack(
        (np.ones_like(rough_depth), rough_depth), axis=-1).reshape(-1, 2)
    slopes = []
    for channel in range(3):
        coefficients, *_ = np.linalg.lstsq(
            design, rgb[..., channel].reshape(-1), rcond=None)
        slopes.append(float(coefficients[1]))
    slopes = np.asarray(slopes, dtype=np.float32)
    weights = np.tanh(4.0 * np.abs(slopes))
    directions = (slopes <= 0.0).astype(np.float32)

    depth_channels = []
    for channel in range(3):
        local_minimum = minimum_filter(
            np.abs(directions[channel] - rgb[..., channel]),
            size=window,
            mode="reflect",
        )
        depth_channels.append(
            weights[channel] * local_minimum + (1.0 - weights[channel]))
    depth_map = np.min(np.stack(depth_channels, axis=-1), axis=-1)

    atmospheric_count = max(1, depth_map.size // 1000)
    indices = np.argpartition(
        depth_map.reshape(-1), -atmospheric_count)[-atmospheric_count:]
    atmospheric_light = rgb.reshape(-1, 3)[indices].mean(axis=0)
    denominator = np.maximum(atmospheric_light, 1.0 - atmospheric_light)
    difference = np.abs(rgb - atmospheric_light) / np.maximum(denominator, 1e-6)
    transmission = np.max(difference, axis=-1)
    transmission = median_filter(transmission, size=window, mode="reflect")
    transmission = np.clip(transmission, 0.0, 1.0)

    low = float(transmission.min())
    high = float(transmission.max())
    if high - low < 1e-8:
        return np.full_like(transmission, 0.2, dtype=np.float32)
    transmission = (transmission - low) / (high - low) * (high - 0.2) + 0.2
    return transmission.astype(np.float32)


class UcolorEnhancer(BaseModelEnhancer):
    """使用 CUDAExecutionProvider 运行转换后的官方 Ucolor 权重。"""

    model_id = "ucolor"
    display_name = "Ucolor"
    target_size = 256

    def __init__(self):
        """初始化延迟加载的 ONNX Runtime 会话引用。"""
        super().__init__()
        self._ort = None
        self._session = None
        self._input_names = None
        self._output_name = None
        self.input_description = "256×256/目（双目逐目推理）"

    def load(self):
        """加载带外部权重的 ONNX 模型、核对 CUDA Provider 并预热。"""
        model_path = ucolor_onnx_path()
        # 先让 PyTorch 从自身 torch/lib 载入 CUDA/cuDNN。Windows 若由 ORT
        # 先载入 Conda 的 CUDA DLL，之后切换到 PyTorch 模型会发生 DLL 遮蔽。
        try:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("PyTorch CUDA 不可用")
            probe = torch.zeros((1, 3, 64, 64), device="cuda")
            kernel = torch.zeros((8, 3, 3, 3), device="cuda")
            torch.nn.functional.conv2d(probe, kernel, padding=1)
            torch.cuda.synchronize()
            del probe, kernel
        except Exception as exc:
            raise EnhancerError(
                "Ucolor 无法预载 PyTorch CUDA/cuDNN；请用 fish_ui_gpu 环境启动"
            ) from exc
        try:
            import onnxruntime as ort
        except Exception as exc:
            raise EnhancerError(
                "导入 ONNX Runtime 失败；请用 fish_ui_gpu 环境启动") from exc
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise EnhancerError(
                "Ucolor 实时模式需要 ONNX Runtime CUDA Provider；"
                "请用 fish_ui_gpu 环境启动")

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        try:
            session = ort.InferenceSession(
                str(model_path),
                sess_options=options,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
        except Exception as exc:
            raise EnhancerError(f"加载 Ucolor ONNX 模型失败: {exc}") from exc
        if not session.get_providers() or session.get_providers()[0] != "CUDAExecutionProvider":
            raise EnhancerError("Ucolor 未启用 CUDAExecutionProvider，拒绝退回慢速 CPU")

        inputs = session.get_inputs()
        if len(inputs) != 2 or inputs[0].shape != [1, 256, 256, 3]:
            raise EnhancerError("Ucolor ONNX 输入结构与适配器不一致")
        self._input_names = (inputs[0].name, inputs[1].name)
        self._output_name = session.get_outputs()[0].name
        warmup_rgb = np.zeros((1, 256, 256, 3), dtype=np.float32)
        warmup_depth = np.full((1, 256, 256, 1), 0.2, dtype=np.float32)
        session.run(
            [self._output_name],
            {self._input_names[0]: warmup_rgb,
             self._input_names[1]: warmup_depth},
        )

        self._ort = ort
        self._session = session
        self.device_description = (
            f"ONNX Runtime CUDA / {torch.cuda.get_device_name(0)}")
        self.loaded = True

    def _process_one(self, bgr_frame):
        """缩放、生成 GDCP 输入并增强单目 BGR 帧。"""
        resized, metadata = letterbox(
            bgr_frame, self.target_size, self.target_size)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        transmission = estimate_gdcp_transmission(rgb)
        feeds = {
            self._input_names[0]: np.ascontiguousarray(rgb[None, ...]),
            self._input_names[1]: np.ascontiguousarray(
                transmission[None, ..., None]),
        }
        output = self._session.run([self._output_name], feeds)[0][0]
        output = np.clip(output, 0.0, 1.0)
        output = (output * 255.0).round().astype(np.uint8)
        bgr = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
        return restore_letterbox(bgr, metadata)

    def process(self, bgr_frame, stereo_pair=False):
        """增强单帧；固定 batch=1 的官方图按左右目顺序运行。"""
        if not self.loaded or self._session is None:
            raise EnhancerError("Ucolor 尚未加载")
        frames = split_frames(bgr_frame, stereo_pair)
        restored = [self._process_one(frame) for frame in frames]
        return join_frames(restored, stereo_pair)

    def close(self):
        """释放 ONNX Runtime 会话和关联的 CUDA 显存。"""
        self._session = None
        self._input_names = None
        self._output_name = None
        self._ort = None
        self.loaded = False
        gc.collect()
