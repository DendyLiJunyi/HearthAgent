# 类型化局面与结构诊断

`watch` 的 `game.board` 和 `replay <Power.log> --json` 的 `game.board` 使用同一投影。它面向后续只读分析，目前没有生成合法动作或调用模型。

```powershell
cargo run --offline -- replay D:\Hearthstone\Logs\<session>\Power.log --json
cargo run --offline -- watch D:\Hearthstone --once
```

回放 JSON 每局一行，带 `source=offline_replay`、从 1 开始的 `game_number` 和文件尾部 `ignored_partial_line`。它没有实时会话身份，不能作为执行输入；没有 CREATE_GAME 时不输出局面。默认回放仍输出文本摘要。

## board 字段

| 字段 | 含义 |
|---|---|
| `perspective` | 通过本地普通回合动作提交识别的玩家编号；证据不足或冲突时为 null |
| `perspective_source` | 已识别时为 `local_main_action_submission`，否则 null |
| `perspective_conflicting` | 同一局出现不同本地提交者时为 true；该局视角不再恢复 |
| `complete` / `actionable` | 始终 false |
| `turn` | TURN 的非负整数；缺失/无效为 null |
| `active_player` | 所有玩家的 CURRENT_PLAYER 都已知且恰好一个为 1 时，给出该玩家编号；不是“我方”，也不说明对局仍在进行 |
| `invalid_fields` | 投影发现的数字/布尔格式错误和不一致英雄引用次数；不包含未出现的字段 |
| `players` | 按玩家编号排序的视图 |

玩家视图保留 `player_id`、`entity_id`、`current_player`、`hero_entity`、`resources`、`resources_used`、`temporary_resources`。英雄引用要求实体存在、类型为 HERO、控制者匹配且区域为 PLAY 或 GRAVEYARD；败方英雄进入墓地仍可被引用。法力字段是原始观测值，未自行计算可用法力。

区域列表：

- `in_play`：PLAY 区域，含英雄、随从、武器、英雄技能等，不等同于随从列表。
- `hand`：视角未知时只保留实体编号和位置；识别后，仅我方且有已观测卡牌 ID 的手牌公开最后观测的身份和属性，对手手牌仍遮蔽。我方手牌的 `public_zone` 仍为 false。
- `graveyard`：GRAVEYARD 区域的历史观测。
- `observed_deck_count` / `observed_secret_count`：目前归并到 DECK / SECRET 的实体数量，不保证是实际总数，也不输出卡牌身份。

列表先按正数 ZONE_POSITION 排序，未知或 0 位置排在后面，同位置按实体编号排序。卡牌字段包括 `entity_id`、`position`、`public_zone`、`card_id`、`card_type`、`cost`、`attack`、`health`、`damage`、`armor`、`durability`、`exhausted`。`public_zone=true` 只说明实体位于投影的公开区域，缺失身份仍为 null；不证明属性新鲜、可攻击或可操作。

缺失值不填 0。数字只接受 u32 范围，布尔标签只接受 0/1。没有 DAMAGE 不等于零伤害，没有 EXHAUSTED 不等于可攻击。

`cost_resource` 仅根据已观测 CARD_ALTERNATE_COST 映射：0=mana、1=health、2=armor、3=corpses、4=opponents_health、5=alt_tavern_coin。映射经本机客户端 enum 和消费代码核对；缺失为 null，未知值计入 invalid_fields，不能默认法力支付。该字段遵守相同手牌遮蔽规则。静态卡牌费用不覆盖实时 COST，也不构成支付可行性判断。

## 原始数据与隐藏信息

`game.entities` 仍是原始诊断历史，会保留之前观察到的卡牌 ID 和 tags。`game.board` 单独实施隐藏区域遮蔽：例如已公开随从回到手牌，原始实体可能仍有卡牌 ID，但 board 中的 ID、类型、费用及战斗属性全部置为 null。后续模型输入应从受控投影构建，不能直接传整个诊断对象。

视角确认前没有暴露“我方手牌”的接口。HIDE_ENTITY 清除卡牌 ID 后，即使还保留历史属性，我方手牌也整体遮蔽。区域和属性本身只代表最后观测，尚未实现完整隐藏信息时效、牌库洗牌身份失效、规则与模式覆盖。

## 我方视角的证据与限制

本机客户端静态检查显示 `GameState.SendOption` 的日志位于非观战分支；`SendChoices` 日志则在观战判断之前，因此不能单独用于我方识别。这里只使用格式完整的 `SendOption`，并要求提交时已观测到恰好两名玩家、STATE=RUNNING、STEP=MAIN_ACTION、完整且唯一的 CURRENT_PLAYER 标志，以及此前无未解析引用或格式错误。按事件顺序绑定提交时的玩家，后续换回合不改变身份；不同提交指向不同玩家时，该局视角失效并重新遮蔽双方手牌。

证据不会跨 CREATE_GAME、文件重置或会话轮换继承；玩家姓名、手牌是否可见、玩家编号 1、收到的选项/选择包均不是识别依据。原始 `game.entities` 仍是诊断历史，不能作为模型输入。视角识别也不能证明日志没有缺失，或视角在观战切换后仍有效；当前所有快照继续 `complete=false`、`actionable=false`。

此方式需要本局至少一次有效的人工动作提交，不能独立启动换牌或自动执行第一步。后续仍需对局开始时的可靠身份来源、模式与观战状态确认。

2026-10-27 本地四个会话共 20 局回放中，15 局识别出一致视角，5 局保持未知，未出现冲突。这是日志一致性验证，尚非与画面逐局核对的身份准确率。新增测试覆盖提交时序、未知/冲突状态、手牌遮蔽和逐字节实时/离线一致性。

## power_structure 字段

结构诊断仅处理 GameState 的权威 Power 流，PowerTaskList 动画流不参与状态更新。

- `blocks_started` / `blocks_completed`、`sub_spells_started` / `sub_spells_completed`：开始次数和成功匹配的结束次数。
- `open_blocks` / `open_sub_spells`、`max_depth`：未结束数量与最大嵌套深度。
- `metadata_records` / `metadata_entries`：META_DATA 次数与按连续索引匹配的 Info 项数。
- `pending_metadata_entries`：当前 META_DATA 尚待收到的项数；完整行尚未到达时保持 pending。
- `errors`：不匹配结束、缺失头字段、无效计数、孤立/重复/跳号 Info 项，或下一条 Power 记录到来时发现项数不足。错误在本局内保持，只有新局/传输重置才清除。
- `error_types` / `first_error_power_sequence`：固定错误类型计数及首次错误的本局 Power 记录序号（从 1 开始，包括 CREATE_GAME）；没有错误时序号为 null。无需输出原始记录即可定位异常。
- `closed`：当前已处理前缀没有未关闭框架、待收元数据或结构错误。它不表示日志无缺失、动画已结束、游戏仍运行或快照可执行。

这里只验证边界和元数据序列，没有解释 Meta 的规则含义，也没有验证 sub-spell 的 Source/Targets 列表语义。`ignored_power_records` 继续统计未作为实体状态更新应用的记录，因此包括用于结构诊断的边界与元数据，不能与结构计数相加作为总行数。

## logged_options 字段

`game.logged_options` 保存当前局最后一组 `GameState.DebugPrintOptions`。它与实体更新独立；仅有选项追加也会触发实时 JSON 发布。

- `packets_seen`、`malformed_records`、`unsupported_records` 是本局累计诊断。
- `latest.id` 是日志选项包编号，不是实体编号。
- `latest.observed_power_sequence` 是收到包头时已经处理的 Power 记录数，可与结构错误序号对应；不是跨会话局面 ID。
- `latest.options` 保留 `index`、`kind`（END_TURN / POWER / UNKNOWN）、`entity_id`、`error` 与 `targets`；目标保留自己的索引、实体编号和错误码。没有导出显示名称或 errorParam。
- `latest.stale` 在后续 Power 记录、选项/选择提交或选择记录出现后置为 true；新包头替换旧包，错误包头直接清空旧包。动画流不会刷新或清除该标志。
- `latest.complete=false`、`actionable=false`：包没有声明长度，也没有实现子选项或完整规则校验。即使 `error=NONE` 且 `stale=false`，也不是可执行候选。

索引要求从 0 连续递增；孤立、重复、缺号或无法解析的记录进入诊断。已支持 `sub_options` 及各自独立的目标索引；损坏或未知行会切断目标归属，后续目标不会被错误挂到上一个主选项。错误码仅保留 NONE、INVALID 或格式受限的 REQ_*，其他内容使用 UNKNOWN。每包新增 malformed_records/unsupported_records，累计计数继续保留。详见 [动作预览](action-preview.md)。

`game.logged_choices` 现保留选择包、来源、候选和提交列表，见 [选择事件](choices.md)。

这些选项属于原始诊断对象；尚未将其并入中立 `board` 或 `protocol::Candidate`。

## 验证结果（2026-10-27）

09:44:35 会话三局均无结构错误；最大嵌套深度分别 4、6、4。补充分类型后该会话的 OTHER 归零，但仍有未实现的事件语义。

12:30:44 会话五局的实体数为 178、82、112、256、116；均无未解析引用、状态格式错误或 board 无效字段。第四局第 10187 条 Power 记录有一个无法匹配的 SUB_SPELL_END，结构错误为 1，即使最终所有已知开始均已匹配，也保持 `closed=false`。没有将这条异常静默丢弃。

两会话共 259 个选项包：09:44:35 三局分别 38、33、60 个；12:30:44 五局分别 34、1、24、60、9 个。均无选项格式错误或不支持记录；每局最终选项均已被后续状态更新标记 stale。

真实 JSON 使用 PowerShell ConvertFrom-Json 独立解析；未提交原始日志或玩家名称。回归测试逐字节比较实时流和冻结离线前缀的完整 JSON，覆盖 UTF-8、CRLF、晚到别名、元数据、隐藏区域变化和切局。
