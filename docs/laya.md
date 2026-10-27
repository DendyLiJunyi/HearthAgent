# Laya 接入调查（2026-10-27）

用户已指定模型家族为 Laya。核验的官方模型为 [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)，源码为 [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya)。本次仅调查接口和本机硬件，没有安装运行时、下载权重或执行推理。

## 已核验

- Apache-2.0，输入文本/JSON 状态与 typed questions，输出 choice、score、noul 和概率；不是自由文本生成接口。
- 英文根模型 421M，默认上下文 512 tokens；multilingual 322M，默认 1024，可显式设置至 8192；typed-decisions 421M，默认 1024。
- 模型卡明确指出基础模型在其 typed-decisions 零样本评估中表现有限，专门微调后才显著提高。所检查的官方材料没有提供炉石对局评估；不能把发布方的延迟或概率校准结论当成本项目实测。

来源：[模型卡](https://huggingface.co/convaiinnovations/laya)。

[Hub 元数据](https://huggingface.co/api/models/convaiinnovations/laya) 本次返回 revision `7b928d828b7b0e022f929d9bd2e44165aa270148`，根目录及 `multilingual`、`typed-decisions` 子目录都有独立 safetensors/config/tokenizer 文件。该 revision 是后续复现实验的候选固定版本，尚未下载。

本机 `nvidia-smi`：NVIDIA GeForce RTX 4060 Laptop GPU，8188 MiB 显存，驱动 566.36。尚未验证 PyTorch/CUDA 兼容性、运行峰值显存和延迟。当前 PATH 未发现 Python；其他项目之前记录的 Python 路径也不存在。

## 项目接入决定

保留 Rust 主控，通过本地 Python Laya 服务调用 `POST /v1/systemone`。请求使用 `state` 和 `questions`；选择题的 criteria 映射候选 ID 到简短动作描述。对应 [官方服务源码](https://github.com/NandhaKishorM/laya/blob/main/laya/serve.py)。

初次评估建议显式选择 `multilingual`，以容纳中文描述和较长局面；这只是集成起点，不代表它已证明最适合炉石。先只加载一个 checkpoint，并明确设置 token 预算。官方 [router 实现](https://github.com/NandhaKishorM/laya/blob/main/laya/router.py) 默认将该名称映射到根仓库的 `multilingual` 子目录。

拟用服务配置：`LAYA_HOST=127.0.0.1`、`LAYA_DEVICE=cuda`、`LAYA_MODELS=multilingual`、`LAYA_MAX_LOADED=1`、`USE_TF=0`。客户端仍需在请求中指定模型；预加载列表不是路由白名单。实际安装版本、启动方式及设备支持在搭建环境时再验证。

## 实施和验收

1. 在本项目建立隔离 Python 环境，固定 Laya/PyTorch 和模型 revision；先用合成请求验证响应。
2. 测量冷启动、热推理 p50/p95、峰值显存、输入截断与候选描述截断。候选数量不能静默截取前 N 项。
3. 模型只接收明确视角的精简局面和经过规则检查的候选。当前 board 未确认我方、logged_options 未证明完整，不能直接转成可执行候选。
4. Rust 校验返回候选 ID、会话、局面版本、超时和弃权；执行前重新观测。分布置信度不等于出牌合法性或胜率。
5. 用离线炉石样本与确定性基线比较，按对局划分评估集；需要时训练策略头并重新校准。

目前模型身份已明确；尚缺本机推理环境、合法候选与视角确认、炉石能力评估。现有 49 项 Rust 测试不包含任何 Laya 推理测试。
