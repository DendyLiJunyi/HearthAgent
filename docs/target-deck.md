# 首版目标：狂野德鲁伊

用户已确认首个模式为 Wild（狂野），并指定以下 30 张卡组。此约束取代初步设计中“模式/卡组待确认”的状态。

```text
AAEBAZarBAbNuwL1/ALw1AOK4AOV4AOTsgcM/K0D/60D7PUDr4AErsAEzuQFsPoF2f8F/Y0GydAGreIGqq8HAAA=
```

版本化卡组配置：[wild-druid.json](../config/decks/wild-druid.json)。`cargo run --offline -- deck` 输出解码结果及卡片清单；可用 `deck <code>` 检查其他代码，但不代表规则合法性已验证。当前 decoder 支持 v1 的单英雄 Wild/Standard 格式；非空 sideboard 会明确拒绝。

卡牌 ID/名称/静态费用来自 [HearthstoneJSON](https://api.hearthstonejson.com/v1/latest/enUS/cards.json)，下载日期和完整源文件 SHA-256 保存在配置中。卡组编码格式参照 [HearthSim 的格式实现](https://github.com/HearthSim/python-hearthstone/blob/master/hearthstone/deckstrings.py)，项目自行实现有长度限制的解析。静态费用仅供识别，不代替实时费用、变形或费用支付方式。

| 数量 | 卡牌 | 主要待支持能力 |
| --- | --- | --- |
| 1 | Mark of the Lotus | 全场增益 |
| 1 | Flobbidinous Floop | 手牌变形、上一张随从、站位 |
| 1 | Lightning Bloom | 法力恢复、过载 |
| 1 | Solar Eclipse | 下一法术双重施放 |
| 1 | Umbral Owl | 动态费用、施法历史、突袭 |
| 1 | Splintered Reality | 树人死亡历史、衍生物 |
| 2 | Aeroponics | 树人数量、动态费用、抽牌 |
| 2 | Treenforcements | 抉择、目标增益、嘲讽、衍生物 |
| 2 | Sow the Soil | 抉择、全场增益、衍生物 |
| 2 | Moonlit Guidance | 发现、牌库复制、条件抽牌 |
| 2 | Aquatic Form | 探底、费用判断、条件抽牌 |
| 2 | Blood Treant | 生命费用、站位 |
| 2 | Forest Seedlings | 手牌成长、回合历史、衍生物 |
| 2 | Cultivation | 树人召唤历史、动态费用、全场增益 |
| 2 | Lifebinder's Gift | 抉择、随机生成、手牌减费 |
| 2 | Overgrown Beanstalk | 树人数量、衍生物、抽牌 |
| 2 | Arkonite Revelation | 抽牌、手牌减费 |
| 2 | Waveshaping | 发现、牌库顺序 |

目前没有卡牌效果模拟器，配置中所有卡牌的 `simulation_supported=false`。已支持的是基于日志的只读攻击预览：限定这套卡组的已审查随从/衍生物及已确认的德鲁伊英雄来源，仅保留客户端明确报告 `NONE` 的目标。未知随从的 POWER 不能直接当成攻击，例如主动技能可能也使用 POWER 选项。

下一阶段优先级：

1. 选择包（抉择/发现/探底）的身份、来源、数量与提交归并。
2. 区分手牌费用类型，使用观测动态费用，避免把 Blood Treant 当作法力支付。
3. 为召唤、增益和选目标建立多阶段动作协议，保留未支持标志。
4. 用该卡组真实窗口建立只读建议集，再评估策略和单步执行。

仅凭对局日志出现部分卡片不能证明正在使用这套卡组；目前不自动把任意对局标记成目标卡组。
