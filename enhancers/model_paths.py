"""集中解析外部基线源码和模型权重路径。"""

import os
from pathlib import Path

from .base import EnhancerError


def baseline_root():
    """返回基线算法根目录，允许使用环境变量覆盖默认位置。"""
    configured = os.environ.get("GROUNDSTATION_BASELINE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "ChatGPT" / "图像增强" / "baseline"


def require_paths(*paths):
    """检查模型依赖路径是否存在，并返回原始路径元组。"""
    missing = [str(path) for path in paths if not Path(path).exists()]
    if missing:
        raise EnhancerError("缺少模型文件:\n" + "\n".join(missing))
    return paths


def uiec2_paths():
    """返回 UIEC²-Net 源码目录和权重文件。"""
    source = baseline_root() / "UWEnhancement"
    checkpoint = source / "checkpoints" / "UIEC2Net.pth"
    require_paths(source / "core" / "Models" / "UWModels" / "UIEC2Net.py", checkpoint)
    return source, checkpoint


def ushape_paths():
    """返回 U-shape Transformer 源码目录和权重文件。"""
    source = baseline_root() / "UshapeTransformer"
    checkpoint = source / "saved_models" / "G" / "generator_795.pth"
    require_paths(source / "net" / "Ushape_Trans.py", checkpoint)
    return source, checkpoint


def ucolor_onnx_path():
    """返回转换并解压后的 Ucolor ONNX 主模型路径。"""
    project_root = Path(__file__).resolve().parents[1]
    model = project_root / "models" / "ucolor" / "runtime" / "__MODEL_PROTO.onnx"
    require_paths(model)
    return model
