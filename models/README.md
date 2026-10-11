# 神经网络模型目录

本目录存放地面站图像增强的本地模型产物。权重体积较大，不提交 Git；源码通过
`GROUNDSTATION_BASELINE_ROOT` 指向外部 `baseline` 目录。

当前路径约定：

| 路径 | 内容 | 生成方式 |
|---|---|---|
| `ucolor/ucolor_256.onnx.zip` | Ucolor 256×256、RGB+GDCP 双输入 ONNX 外部张量压缩包 | 运行 `ref/convert_ucolor_to_onnx.py` |
| `ucolor/runtime/` | 解压后的 `__MODEL_PROTO.onnx` 和外部张量文件，供 ONNX Runtime 加载 | 解压上述 zip |

## 当前模型校验值

| 模型文件 | 字节数 | SHA256 |
|---|---:|---|
| `UIEC2Net.pth` | 2,145,026 | `C839F9980F3AD99BB397B945DF6F748C0FB64C05D157D3CA853B2524BFF05AFE` |
| `generator_795.pth` | 126,569,949 | `C595C2AA49CD9623D02379B3990AD955C46D65DD3095B2B1C5612744981D8FAE` |
| `ucolor_256.onnx.zip` | 595,704,322 | `5B601D3835094C969DFA22C3D3719F27BB1C56B959ECE1E514DD1BD237A604D1` |

当前 Ucolor 原始 TensorFlow 权重位于
`D:\PycharmProjects\Ucolor_final_model_corrected\checkpoint\coarse_128`。主数据文件
`coarse.model.data-00000-of-00001` 为 629,699,093 字节，SHA256 为
`CF0F8BF430E3239F8BC2776C011C56D1CF390F7E5648563CF685A7FF6D3EDE8D`。

## Ucolor 转换与解压

转换必须在兼容旧 TensorFlow 2.4 的 `ucolor_convert` 环境执行：

```powershell
conda run --no-capture-output -n ucolor_convert python ref\convert_ucolor_to_onnx.py `
  --source 'C:\Users\yiiixw\Documents\ChatGPT\图像增强\baseline\Ucolor' `
  --checkpoint-root 'D:\PycharmProjects\Ucolor_final_model_corrected\checkpoint' `
  --sample-image 'C:\Users\yiiixw\Documents\ChatGPT\图像增强\baseline\Ucolor\resolution_check_256\frame_08s_ucolor.png' `
  --output 'models\ucolor\ucolor_256.onnx.zip'

Expand-Archive -LiteralPath 'models\ucolor\ucolor_256.onnx.zip' `
  -DestinationPath 'models\ucolor\runtime'
```

`tf2onnx` 不支持 TensorFlow 的原生 `RGBToHSV`，转换脚本会换成基础算子等价实现；模型超过
2 GB 的 protobuf 限制，因此使用外部张量 zip。固定图像对齐结果：TensorFlow 与 ONNX 输出
最大像素差 1、平均绝对差 0.020、PSNR 65.08 dB。不能仅凭模型能够加载就视为转换成功。
