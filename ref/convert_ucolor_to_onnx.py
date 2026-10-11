"""把 Ucolor TensorFlow 2.4 检查点冻结并转换为双输入 ONNX 模型。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args():
    """解析源码、检查点、样例图和输出路径。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--sample-image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--opset", type=int, default=13)
    return parser.parse_args()


def rgb_to_hsv_onnx_safe(tf, rgb):
    """用 ONNX 可转换的基础算子等价实现 TensorFlow RGB→HSV。"""
    red, green, blue = tf.unstack(rgb, axis=-1)
    maximum = tf.maximum(red, tf.maximum(green, blue))
    minimum = tf.minimum(red, tf.minimum(green, blue))
    delta = maximum - minimum
    safe_delta = tf.where(delta > 0.0, delta, tf.ones_like(delta))

    red_hue = (green - blue) / safe_delta
    green_hue = 2.0 + (blue - red) / safe_delta
    blue_hue = 4.0 + (red - green) / safe_delta
    hue = tf.where(
        tf.equal(maximum, red),
        red_hue,
        tf.where(tf.equal(maximum, green), green_hue, blue_hue),
    ) / 6.0
    hue = tf.where(hue < 0.0, hue + 1.0, hue)
    hue = tf.where(delta > 0.0, hue, tf.zeros_like(hue))
    saturation = tf.where(
        maximum > 0.0, delta / tf.maximum(maximum, 1e-8), tf.zeros_like(maximum))
    return tf.stack((hue, saturation, maximum), axis=-1)


def main():
    """加载官方检查点、冻结变量并调用 tf2onnx 完成转换。"""
    args = parse_args()
    required = (
        args.source / "model_test.py",
        args.checkpoint_root / "coarse_128" / "checkpoint",
        args.sample_image,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("缺少转换输入:\n" + "\n".join(missing))
    if args.size % 8:
        raise ValueError("--size 必须能被 8 整除")

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    sys.path.insert(0, str(args.source))
    os.chdir(args.source)

    import tensorflow.compat.v1 as tf
    import tf2onnx

    tf.disable_v2_behavior()
    original_rgb_to_hsv = tf.image.rgb_to_hsv
    with tf.Graph().as_default(), tf.Session() as validation_session:
        sample = tf.constant([
            [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 0.0, 0.0]],
            [[0.1, 0.7, 0.2], [0.2, 0.3, 0.9], [0.8, 0.8, 0.2]],
        ], dtype=tf.float32)
        reference = original_rgb_to_hsv(sample)
        replacement = rgb_to_hsv_onnx_safe(tf, sample)
        reference_value, replacement_value = validation_session.run(
            (reference, replacement))
        max_error = abs(reference_value - replacement_value).max()
        if max_error > 1e-6:
            raise RuntimeError(
                f"RGB→HSV 替换实现未通过数值对齐: max_error={max_error}")
        print(f"RGB→HSV replacement max_error={max_error:.3g}")

    tf.reset_default_graph()
    tf.image.rgb_to_hsv = lambda rgb, name=None: rgb_to_hsv_onnx_safe(tf, rgb)
    from model_test import T_CNN

    session_config = tf.ConfigProto(device_count={"GPU": 0})
    with tf.Session(config=session_config) as session:
        model = T_CNN(
            session,
            image_height=args.size,
            image_width=args.size,
            label_height=128,
            label_width=128,
            batch_size=1,
            c_dim=3,
            c_depth_dim=1,
            checkpoint_dir=str(args.checkpoint_root),
            sample_dir=str(args.output.parent),
            test_image_name=str(args.sample_image),
        )
        session.run(tf.global_variables_initializer())
        if not model.load(str(args.checkpoint_root)):
            raise RuntimeError("Ucolor TensorFlow 检查点加载失败")

        input_names = [model.images.name, model._depth.name]
        output_names = [model.pred_h.name]
        output_nodes = [model.pred_h.op.name]
        frozen = tf.graph_util.convert_variables_to_constants(
            session, session.graph.as_graph_def(), output_nodes)
        frozen = tf.graph_util.remove_training_nodes(frozen)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tf2onnx.convert.from_graph_def(
        frozen,
        input_names=input_names,
        output_names=output_names,
        opset=args.opset,
        large_model=True,
        output_path=str(args.output),
    )
    print(args.output)


if __name__ == "__main__":
    main()
