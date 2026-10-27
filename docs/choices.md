# 选择事件诊断

`game.logged_choices` 保留 GameState 的选择包和最近一次服务器选择提交记录，不导出显示名称。它是后续抉择、发现、探底和换牌状态机的输入，当前 `actionable=false`。

`sets` 按 choice ID 保存本局包：`owner_entity` 是玩家实体 ID（不是 PlayerID），`kind` 为 MULLIGAN/GENERAL/TARGET/UNKNOWN，`source_entity` 为来源实体，`minimum`/`maximum` 为选择数量范围，`entities` 为按日志索引排列的候选实体。

选择数量上限不是候选总数。例如三选一的 maximum=1，不表示只应读取一个候选。因此包的 `complete` 始终 false。Source 必须先于 Entities；候选索引连续且实体不重复；未支持类型、损坏行和未知所有者保留为诊断，未知所有者不会根据候选控制者猜测。

新包取代同一已知所有者的旧选择；状态事件、选项包或本地提交使已有选择 stale。不同玩家的包可以同时保存。切局和文件重置清空全部历史。

`latest_submission` 保存最近 `DebugPrintEntitiesChosen` 的 choice ID、所有者、声明的 EntitiesCount 和实际选择列表。只有数量完全匹配、索引连续、没有重复/坏行时，`list_complete=true`。这只验证已记录的提交列表完整，不证明动作效果完成，也不将其当作本地玩家识别证据。

本次对四个本机会话共 20 局的 129 个选择包回放，格式错误与未知选择类型均为 0；其中 MULLIGAN 40、GENERAL 88、TARGET 1。原始日志未提交，通用回归采用合成数据。尚待验证这些选择与具体卡牌、多阶段 UI 和实际执行结果之间的对应关系。
