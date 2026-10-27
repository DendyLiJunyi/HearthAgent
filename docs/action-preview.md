# 只读动作预览与历史选项窗口

`watch` 和 `replay --json` 的 `game.action_preview` 现在解释一部分客户端选项。它不是完整合法动作集，固定输出 `complete=false`、`actionable=false`、`legality_verified=false`。这两个命令不调用模型或执行器；显式 `advise` 命令可请求只读排序。

## 当前范围

- 必须已识别我方，处于我方 MAIN_ACTION，STATE=RUNNING。
- 局面没有已知未解析引用、格式错误或非法数字字段，Power 结构已闭合。
- 当前选项包没有被后续事件标记 stale，也没有该包内的格式/不支持记录。
- 主选项和目标都必须为 `error=NONE`；本机 Network.Options 的 `PlayErrorInfo.IsValid()` 仅接受 NONE。INVALID 不等于合法。
- 只解释目标卡组中已审查来源的普通攻击；目标须是对方在场英雄/随从。
- 拒绝未知来源机制、子选项事务及没有明确目标行的选项。未看到目标不能推断“无需目标”，因为包可能还没读完。

输出保留选项包 ID、Power 序号、主选项索引、目标索引和源/目标实体 ID。候选 ID 只在外层会话/局面范围内有意义；不能跨游戏复用。`blocked_by` 给出整体阻塞原因，`omitted` 统计被略过的选项/目标原因，二者不是完整度证明。

`logged_options` 同时新增 `sub_options` 及其独立目标列表、每包 malformed/unsupported 计数。子选项可以正确解析，但尚未被转为动作。累计诊断不因新包消失，每包诊断则重新开始。

## 历史窗口

完整对局的最后一个选项包通常已失效。新命令在每个选项包结束后、下一条记录处理前重建当时前缀：

```powershell
cargo run --offline -- review <Power.log>
```

每行包含当时 board 和 action_preview，不包含原始实体历史或玩家名称。不会使用未来才学到的视角或别名来伪造当时可用的信息。`packet_boundary_observed` 表示读到了后续记录；它不证明包完整。EOF 的窗口标为 false，未结束的最后一行不参与解析。

批量验证：

```powershell
cargo build --offline --target-dir target/validation
.venv/Scripts/python.exe scripts/review-corpus.py D:/Hearthstone/Logs
```

脚本输出计数报告到 `.data/preview-review.json`，并保存第一份可解释窗口示例。这些计数不等于规则覆盖率或执行成功率。使用独立 target 目录可避免与正在运行的旧版 watcher 争用 Windows 可执行文件；运行中的旧进程不会自动加载新代码。

2026-10-27 的四会话语料检查得到 563 个历史选项窗口。限定用户目标卡组的来源后，没有窗口产生受支持攻击候选；不能把这些旧局的窗口统计当成目标卡组覆盖验证。合成目标卡组样例见 `fixtures/wild-druid-attacks.log`。

## 只读模型排序

```powershell
cargo run --offline -- advise fixtures/wild-druid-attacks.log
cargo run --offline -- advise <Power.log> http://127.0.0.1:8791
```

只分析文件冻结前缀的最后一局当前状态，不回退到早先可用窗口。末尾有未结束行、没有受支持候选或状态阻塞时不尝试模型查询；模型输入仅用受控 board 投影和候选覆盖说明。结果 `source=frozen_log_advice`，始终不可执行，不表示游戏仍处于该位置。

`LayaPolicy::advise` 返回独立的 AdvisoryChoice 类型，不能直接传入需要 Decision 的控制器。原 `decide` 路径仍拒绝 incomplete 快照；即使外部代码手工复制字段造出 Decision，控制器仍拒绝不完整观测。HTTP 大小、超时、候选标签、概率和置信度检查共用原验证代码。

命令保留默认 0.8 阈值，不通过降低阈值制造建议。本次合成攻击样例的真实 GPU 调用被模型弃权门槛拒绝，输出 `status=no_advice`。`model_query_attempted` 只说明尝试了查询流程，不保证网络请求已经发出。CLI 成功退出表示完成报告，不表示存在建议或建议正确。
