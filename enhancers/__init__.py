"""地面站图像增强模型的延迟加载入口。"""


MODEL_METHODS = {"uiec2", "ushape", "ucolor", "light_ucolor_retinex"}


def create_enhancer(model_id):
    """按模型标识延迟导入并创建增强器，避免启动 UI 时加载 PyTorch。"""
    if model_id == "uiec2":
        from .uiec2_enhancer import UIEC2Enhancer
        return UIEC2Enhancer()
    if model_id == "ushape":
        from .ushape_enhancer import UShapeEnhancer
        return UShapeEnhancer()
    if model_id == "ucolor":
        from .ucolor_enhancer import UcolorEnhancer
        return UcolorEnhancer()
    raise ValueError(f"尚未接入增强模型: {model_id}")
