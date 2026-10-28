# 选择事件诊断

`game.logged_choices` 保留 GameState 的选择包和最近一次服务器选择提交记录，不导出显示名称。它是后续抉择、发现、探底和换牌状态机的输入，当前 `actionable=false`。

`sets` 按 choice ID 保存本局包：`owner_entity` 是玩家实体 ID（不是 PlayerID），`kind` 为 MULLIGAN/GENERAL/TARGET/UNKNOWN，`source_entity` 为来源实体，`minimum`/`maximum` 为选择数量范围，`entities` 为按日志索引排列的候选实体。

选择数量上限不是候选总数。例如三选一的 maximum=1，不表示只应读取一个候选。因此包的 `complete` 始终 false。Source 必须先于 Entities；候选索引连续且实体不重复；未支持类型、损坏行和未知所有者保留为诊断，未知所有者不会根据候选控制者猜测。

新包取代同一已知所有者的旧选择；状态事件、选项包或本地提交使已有选择 stale。不同玩家的包可以同时保存。切局和文件重置清空全部历史。

`latest_submission` 保存最近 `DebugPrintEntitiesChosen` 的 choice ID、所有者、声明的 EntitiesCount 和实际选择列表。只有数量完全匹配、索引连续、没有重复/坏行时，`list_complete=true`。这只验证已记录的提交列表完整，不证明动作效果完成，也不将其当作本地玩家识别证据。

## 提交与选择包关联（2026-10-28）

`latest_submission.correlation` 新增以下诊断：

- `packet_seen`：在提交头之前是否见过同 ID 的选择包。
- `packet_kind`、`packet_was_stale`、`packet_malformed_records`：提交头到达前该包的类型、失效状态和格式错误数。提交自身造成的 stale 不会倒灌进这里。
- `owner_matches`：两侧所有者都已解析时比较实体 ID，否则 null。
- `declared_count_within_bounds`：提交声明数量是否位于原包的 minimum/maximum 内；没有原包时为 null。与提交列表自身的 `list_complete` 独立。
- `unobserved_entities`：已正确解析的提交实体中，没有出现在原包已观察候选列表里的 ID。由于原包不保证完整，此字段不能单独证明游戏选择非法；未见原包时不进行此比较。
- `candidate_list_complete=false`、`execution_confirmed=false`：关联成功不认证候选完整或执行完成。

关联使用提交头处冻结的包，后到包或同 ID 的替换包不能修补历史提交。重复/跳号等坏提交行仍由原来的 `malformed_records` 和 `list_complete` 表达；关联字段不会消除这些错误。冻结上下文仅在内存保存，不重复导出，不包含显示名称。

四项新增回归覆盖所有者/数量/实体不一致、正常匹配仍非执行确认、后到及复用 ID、未知所有者/类型、损坏包和未完成列表；原逐行回放与实时一致性测试也覆盖新增字段。全套 85 项 Rust 测试通过，Clippy 无警告。

The existing corpus check covered the last retained submission in each of 20 games: lists, owners and declared counts matched, with no unobserved entities. See [correlation report](choice-correlation-review.json). This does not cover all historical choice packets, establish Rogue deck coverage, or validate multi-stage UI execution.

本次对四个本机会话共 20 局的 129 个选择包回放，格式错误与未知选择类型均为 0；其中 MULLIGAN 40、GENERAL 88、TARGET 1。原始日志未提交，通用回归采用合成数据。尚待验证这些选择与具体卡牌、多阶段 UI 和实际执行结果之间的对应关系。

The newer [choice-window exporter](choice-windows.md) reviews every packet and submission prefix, instead of only the last retained submission in each game.
