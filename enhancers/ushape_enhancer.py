"""U-shape Transformer 的实时 PyTorch/CUDA 适配器。"""

import gc
import sys

import cv2
import numpy as np

from .base import (BaseModelEnhancer, EnhancerError, join_frames, letterbox,
                   restore_letterbox, split_frames)
from .model_paths import ushape_paths


class UShapeEnhancer(BaseModelEnhancer):
    """以官方固定 256×256 输入运行 U-shape Transformer。"""

    model_id = "ushape"
    display_name = "U-shape Transformer"
    target_size = 256

    def __init__(self):
        """初始化延迟加载所需引用。"""
        super().__init__()
        self._torch = None
        self._model = None
        self._device = None
        self.input_description = "256×256/目"

    def load(self):
        """加载官方生成器与权重并执行一次双目 batch 预热。"""
        source, checkpoint = ushape_paths()
        source_text = str(source)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        try:
            import torch
            from net.Ushape_Trans import Generator
        except Exception as exc:
            raise EnhancerError(f"导入 U-shape Transformer 失败: {exc}") from exc
        if not torch.cuda.is_available():
            raise EnhancerError(
                "U-shape Transformer 实时模式需要 CUDA；请用 fish_ui_gpu 环境启动")

        device = torch.device("cuda")
        model = Generator().to(device)
        state = torch.load(
            checkpoint, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        model.eval()
        warmup = torch.zeros(
            2, 3, self.target_size, self.target_size, device=device)
        with torch.inference_mode():
            model(warmup)[-1]
        torch.cuda.synchronize()

        self._torch = torch
        self._device = device
        self._model = model
        self.device_description = torch.cuda.get_device_name(device)
        self.loaded = True

    def process(self, bgr_frame, stereo_pair=False):
        """成批增强左右目，并用共享范围归一化保证双目一致性。"""
        if not self.loaded or self._model is None:
            raise EnhancerError("U-shape Transformer 尚未加载")
        frames = split_frames(bgr_frame, stereo_pair)
        prepared = []
        metadata = []
        for frame in frames:
            resized, item_metadata = letterbox(
                frame, self.target_size, self.target_size)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            prepared.append(rgb)
            metadata.append(item_metadata)

        batch = np.stack(prepared, axis=0).astype(np.float32) / 255.0
        tensor = self._torch.from_numpy(
            np.ascontiguousarray(batch)).permute(0, 3, 1, 2).to(self._device)
        with self._torch.inference_mode():
            output = self._model(tensor)[-1]
        # 官方 notebook 使用全局 min-max；双目 batch 共用同一范围，避免左右亮度漂移。
        low = output.amin()
        high = output.amax()
        output = (output - low) / (high - low).clamp_min(1e-8)
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
        """释放 U-shape Transformer 和缓存显存。"""
        torch = self._torch
        self._model = None
        self._device = None
        self._torch = None
        self.loaded = False
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
