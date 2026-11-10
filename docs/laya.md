# Laya 接入调查（2026-10-27）

> 后续实施已完成：本机安装了隔离运行时和固定 revision 模型，已验证 CUDA 推理。以下调查段落保留当时记录；当前的加载与微调方式见 [Live agent](agent.md) 和 [Learning](learning.md)。

用户已指定模型家族为 Laya。核验的官方模型为 [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)，源码为 [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya)。本次仅调查接口和本机硬件，没有安装运行时、下载权重或执行推理。

## 已核验

- Apache-2.0，输入文本/JSON 状态与 typed questions，输出 choice、score、noul 和概率；不是自由文本生成接口。
- 英文根模型 421M，默认上下文 512 tokens；multilingual 322M，默认 1024，可显式设置至 8192；typed-decisions 421M，默认 1024。
- 模型卡明确指出基础模型在其 typed-decisions 零样本评估中表现有限，专门微调后才显著提高。所检查的官方材料没有提供炉石对局评估；不能把发布方的延迟或概率校准结论当成本项目实测。

来源：[模型卡](https://huggingface.co/convaiinnovations/laya)。

[Hub 元数据](https://huggingface.co/api/models/convaiinnovations/laya) 本次返回 revision `7b928d828b7b0e022f929d9bd2e44165aa270148`，根目录及 `multilingual`、`typed-decisions` 子目录都有独立 safetensors/config/tokenizer 文件。该 revision 是后续复现实验的候选固定版本，尚未下载。

本机 `nvidia-smi`：NVIDIA GeForce RTX 4060 Laptop GPU，8188 MiB 显存，驱动 566.36。尚未验证 PyTorch/CUDA 兼容性、运行峰值显存和延迟。当前 PATH 未发现 Python；其他项目之前记录的 Python 路径也不存在。

## 当前接入方式

不再通过 HTTP 服务调用。`agent/policy.py` 的 `LayaPolicy.load()` 在 Agent 进程内用 `laya.load()` 直接加载微调后的 checkpoint（默认 `.data/imitation/laya-wild-reviewed-20261105`），在 CUDA 上推理。基座为固定 revision 的 `multilingual` 子目录，见 `services/laya/runtime.py`；运行环境由 `scripts/setup-laya.ps1` 按 `services/laya/pyproject.toml` 与 `uv.lock` 安装。

局面和候选动作由 `experiments/imitation/features.py` 渲染为文字。模型只在游戏给出的候选中打分，并在多种候选顺序下取平均；斩杀、换牌和选择交给规则。微调与评估流程见 [learning](learning.md)。
