"""UIEC²-Net 的实时 PyTorch/CUDA 适配器。"""

import gc
import sys

import cv2
import numpy as np

from .base import (BaseModelEnhancer, EnhancerError, join_frames, letterbox,
                   restore_letterbox, split_frames)
from .model_paths import uiec2_paths


class UIEC2Enhancer(BaseModelEnhancer):
    """以 320×240 实时输入运行官方 UIEC²-Net 权重。"""

    model_id = "uiec2"
    display_name = "UIEC²-Net"
    target_width = 320
    target_height = 240

    def __init__(self):
        """初始化延迟加载所需引用。"""
        super().__init__()
        self._torch = None
        self._model = None
        self._device = None
        self.input_description = f"{self.target_width}×{self.target_height}/目"

    def load(self):
        """加载兼容版网络、严格载入官方权重并执行一次 CUDA 预热。"""
        source, checkpoint = uiec2_paths()
        source_text = str(source)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)

        try:
            import torch
            from core.Models.UWModels.UIEC2Net import UIEC2Net
        except Exception as exc:
            raise EnhancerError(f"导入 UIEC²-Net 失败: {exc}") from exc
        if not torch.cuda.is_available():
            raise EnhancerError(
                "UIEC²-Net 实时模式需要 CUDA；请用 fish_ui_gpu 环境启动")

        device = torch.device("cuda")
        model = UIEC2Net().to(device)
        try:
            state = torch.load(checkpoint, map_location=device, weights_only=True)
        except TypeError:
            state = torch.load(checkpoint, map_location=device)
        if isinstance(state, dict):
            for key in ("state_dict", "model", "params"):
                if key in state and isinstance(state[key], dict):
                    state = state[key]
                    break
        state = {key.removeprefix("module."): value for key, value in state.items()}
        model.load_state_dict(state, strict=True)
        model.eval()

        warmup = torch.zeros(
            2, 3, self.target_height, self.target_width, device=device)
        with torch.inference_mode():
            model(warmup)
        torch.cuda.synchronize()

        self._torch = torch
        self._device = device
        self._model = model
        self.device_description = torch.cuda.get_device_name(device)
        self.loaded = True

    def process(self, bgr_frame, stereo_pair=False):
        """成批增强单帧或左右目，并恢复到输入分辨率。"""
        if not self.loaded or self._model is None:
            raise EnhancerError("UIEC²-Net 尚未加载")
        frames = split_frames(bgr_frame, stereo_pair)
        prepared = []
        metadata = []
        for frame in frames:
            resized, item_metadata = letterbox(
                frame, self.target_width, self.target_height)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            prepared.append(rgb)
            metadata.append(item_metadata)

        batch = np.stack(prepared, axis=0).astype(np.float32) / 255.0
        tensor = self._torch.from_numpy(
            np.ascontiguousarray(batch)).permute(0, 3, 1, 2).to(self._device)
        with self._torch.inference_mode():
            output = self._model(tensor).clamp(0.0, 1.0)
        output = (
            output.permute(0, 2, 3, 1).mul(255.0).round()
            .byte().cpu().numpy()
        )

        restored = []
        for rgb, item_metadata in zip(output, metadata):
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            restored.append(restore_letterbox(bgr, item_metadata))
        return join_frames(restored, stereo_pair)

    def close(self):
        """释放 UIEC²-Net 和缓存显存。"""
        torch = self._torch
        self._model = None
        self._device = None
        self._torch = None
        self.loaded = False
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
