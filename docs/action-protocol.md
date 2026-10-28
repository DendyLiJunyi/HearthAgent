# 动作身份、换牌与多选协议

Rust 语义协议新增以下表达能力，供未来经过规则核验的候选适配器使用。此处没有新增日志到可执行动作的转换，也没有实现实际鼠标事务。

| 阶段 | 可接受动作 | 字段 |
| --- | --- | --- |
| Mulligan | Mulligan | `choice_id`、`replace` 实体列表；空列表表示全留 |
| Choosing | ChooseOptions | `choice_id`、`entities` 实体列表；是否允许空列表由实际 CountMin 决定 |
| OurTurn | PlayCard | `source`、可选 `target`、可选一基 `position` |
| OurTurn | Attack / HeroPower / EndTurn | 保留原有字段 |
| OpponentTurn / Animating / Finished | 无 | 不允许提交 |

`ChooseOptions` 取代不带包身份的单实体 `ChooseOption`。选择一张卡使用长度为一的列表；多选保持所给顺序，不擅自排序。`choice_id` 为日志选择包 ID，不是实体 ID。牌位 `None` 表示未提供位置，不能自动解释成随从可任意放置；实际动作是否要求位置仍由适配器保证。

`Action::allowed_in` 集中定义阶段匹配，Laya、runner 和控制器共用，避免各自漏掉新动作。`Action::well_formed` 只检查非零实体 ID、非零显式位置、无重复列表及最多 32 个选择实体的协议上限，不证明卡牌效果、费用、候选成员关系或 CountMin/CountMax 合法。32 是消息保护上限，不是游戏选择规则。

Laya 的候选描述保留包 ID、实体列表和位置，短标签仍只在本次请求内映射。模型最多 16 个候选的限制不变，不会为了支持新动作静默截断列表。HTTP 测试使用模拟响应验证传输与映射，不能据此认为真实模型已经学会换牌或多选。

新回归验证阶段矩阵、全留换牌、多实体选择、包身份、零实体/零位置/重复选择拒绝和模型 HTTP 字段保留。
