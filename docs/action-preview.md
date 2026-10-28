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

### 待审查样本导出（2026-10-28）

```powershell
.venv/Scripts/python.exe scripts/review-corpus.py D:/Hearthstone/Logs --dataset .data/attack-review.jsonl
.venv/Scripts/python.exe -m unittest discover -s scripts -p test_*.py
```

`--dataset` 导出 JSONL，只保留已观察到后续记录边界、无整体阻塞且存在受支持攻击的窗口。边界不证明候选完整，样本始终 `complete=false`、`actionable=false`。EOF 未闭合窗口仍计入诊断，但不进入待审查样本。

每条包含当时 board、候选及其来源索引、session/game 的 `group_id`、窗口序号及内容哈希 `sample_id`。划分训练/评估数据时必须按 `group_id` 分组，不能把同一局的不同窗口随机分散到两组。哈希标识内容，不构成源文件真实性证明。标注初始为 `unreviewed`，不把玩家实际选择或第一候选自动当作正确答案。

报告新增我方可见目标卡牌 ID 和我方英雄 ID；目标卡牌交集只是证据，不自动认证卡组。未知视角不收集此证据。样本仅使用原始前缀信息，每局报告的卡牌并集仅用于诊断，不能倒灌到早期样本。

可用 `--user-target-session <会话文件夹名>` 记录用户报告该会话使用目标卡组，允许重复指定。该信息与 `target_deck_confirmed=false` 分开，不能证明会话内每局均为指定卡组。参数必须匹配实际发现的会话目录。

每次运行重写 dataset，零样本时输出空文件；无示例时示例文件写入 JSON null，避免残留上次结果。本工具生成待审查材料，不执行模型推理或游戏输入。

2026-10-28 重新检查得到四个含 Power.log 的会话、16 个有选项窗口的局、563 个窗口、0 个受支持攻击样本。[诊断报告](attack-corpus-review.json) 保存了每局原因。20:27 会话中有选项窗口的四局均投影出 `HERO_09`，未见我方目标卡牌；原 Power.log 也没有 `CardID=HERO_06` 记录。用户随后澄清目前尚未进行德鲁伊对局，将稍后游玩；此前会话确认已撤销。目标卡组真实样本采集等待新对局，日志来源疑问已解决。

同日追加日志后的最新报告已更新为五个会话、18 个有窗口的局、688 个窗口，受支持攻击样本仍为 0。报告里的目标卡组证据继续保持未确认。

2026-10-27 的四会话语料检查得到 563 个历史选项窗口。限定用户目标卡组的来源后，没有窗口产生受支持攻击候选；不能把这些旧局的窗口统计当成目标卡组覆盖验证。合成目标卡组样例见 `fixtures/wild-druid-attacks.log`。

## 只读模型排序

```powershell
cargo run --offline -- advise fixtures/wild-druid-attacks.log
cargo run --offline -- advise <Power.log> http://127.0.0.1:8791
```

只分析文件冻结前缀的最后一局当前状态，不回退到早先可用窗口。末尾有未结束行、没有受支持候选或状态阻塞时不尝试模型查询；模型输入仅用受控 board 投影和候选覆盖说明。结果 `source=frozen_log_advice`，始终不可执行，不表示游戏仍处于该位置。

`LayaPolicy::advise` 返回独立的 AdvisoryChoice 类型，不能直接传入需要 Decision 的控制器。原 `decide` 路径仍拒绝 incomplete 快照；即使外部代码手工复制字段造出 Decision，控制器仍拒绝不完整观测。HTTP 大小、超时、候选标签、概率和置信度检查共用原验证代码。

命令保留默认 0.8 阈值，不通过降低阈值制造建议。本次合成攻击样例的真实 GPU 调用被模型弃权门槛拒绝，输出 `status=no_advice`。`model_query_attempted` 只说明尝试了查询流程，不保证网络请求已经发出。CLI 成功退出表示完成报告，不表示存在建议或建议正确。
