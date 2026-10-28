# Laya 接入验收（2026-10-27）

2026-10-28 更新：[多局面与输入顺序评估](laya-evaluation.md) 已完成，包含 90 次离线推理和可复现脚本。以下保留初次单局面基准结果。

本地 CUDA 推理和 Rust → HTTP → Laya 通路已验证；当前 checkpoint 未通过合成斩杀样例。没有连接真实对局候选或发送游戏输入。

## 运行

在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-laya.ps1
.venv/Scripts/python.exe services/laya/probe.py --runs 20
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start-laya.ps1
Invoke-RestMethod http://127.0.0.1:8791/health
cargo run --offline -- laya-demo
```

首次 setup/probe 需要下载依赖和权重。模型已缓存后使用 `probe.py --offline --runs 20`。启动脚本返回只代表已创建进程，应等待 `/health` 返回 `status=ok`，并确认 `checkpoint_devices.multilingual=cuda` 和固定 revision 后再调用 demo。启动日志位于 `.data/laya-stderr.log`。

## 本机结果

环境：RTX 4060 Laptop 8 GB，Laya 0.4.15、PyTorch 2.7.1+cu126、Transformers 4.57.6。模型为 multilingual，revision `7b928d828b7b0e022f929d9bd2e44165aa270148`。完整直接推理结果保存在 [laya-benchmark.json](laya-benchmark.json)。

| 指标 | 实测 |
| --- | --- |
| 离线缓存模型加载 | 4.85 秒 |
| 首次推理（不计入热统计） | 449.01 ms |
| 20 次热推理中位数 | 25.54 ms |
| 热推理 p95（nearest rank） | 33.49 ms |
| 当前 probe 进程峰值 CUDA allocated | 1500.70 MiB |
| 输入 tokens | 209，无截断 |
| 合成斩杀样例正确次数 | 0/20 |

计时在 CUDA 同步后读取，不包含 HTTP 开销。显存指标不是整张显卡总占用。20 次重复同一输入只验证该样例及计时，不是独立评估集。

Rust 首次 HTTP 请求耗时 676 ms，返回 `end_turn`，概率 0.5506；预期 `attack`，概率 0.4494。`laya-demo` 为观察输出将阈值设为 0；生产适配器默认阈值 0.8 会拒绝该结果。CLI 成功退出表示协议调用成功，正确性必须查看 `correct` 字段。

## 修复的评估偏差

旧 probe 直接传入 fixture，缺少 Rust 的 session/revision/board 外层；还使用 Python 插入顺序，而 Rust 的 serde_json 对象键按字母排序。Laya 将对象转为文本，字段顺序会改变模型输入。

本次对照中，带外层但未排序的 Python 输入得到 attack（0.7827）；将所有嵌套对象按 Rust 顺序排序后，Python 和 HTTP 均得到 end_turn（0.5506）。probe 现在与 Rust 的状态外层及字段顺序一致，避免直接推理测试误报能力。

下一步应增加多局面离线评估、候选顺序和状态字段顺序扰动，并与确定性基线比较。真实观测的我方视角、合法候选和完整性仍需单独实现。

## 验证

```powershell
cargo test --offline
cargo clippy --offline --all-targets -- -D warnings
.venv/Scripts/python.exe -m unittest discover -s services/laya -p test_*.py
```

本次 55 项 Rust 测试和 4 项 Python 测试通过，Clippy 无警告。Python 测试覆盖百分位计算、无效测量拒绝，以及包含列表内对象的递归字段排序；不需要加载模型。
