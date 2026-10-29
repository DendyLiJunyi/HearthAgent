# 完整对局日志验证（2026-10-27）

## 命令

```powershell
cd D:\HearthAgent
cargo run --offline -- replay D:\Hearthstone\Logs\Hearthstone_2026_10_27_09_44_35\Power.log
cargo test --offline
```

新增 `src/replay.rs` 和 5 个回放测试。总计 13 个测试通过。对真实已完成对局的读取验证结果：

| 项目 | 结果 |
|---|---|
| GameState 创建对局数量 | 1 |
| 最终实体数量 | 135 |
| 游戏 TURN 标签 | 15（全局轮次，不表示双方各打了 15 回合） |
| STEP / STATE | FINAL_GAMEOVER / COMPLETE |
| 玩家 1 / 玩家 2 PLAYSTATE | WON / LOST |
| 未解析的实体引用 | 0 |
| 支持记录中的格式异常 | 0 |
| 其他未应用的 Power 记录 | 1146 |
| 文件尾部未结束行 | 无 |

不依据玩家编号宣称哪方是当前用户。玩家名、账号 ID 不输出，也未将真实原始日志加入项目或测试。

随后验证时同一日志追加了第二局，解析器分别输出第一局 COMPLETE 与第二局 BEGIN_MULLIGAN/RUNNING，确认实际日志中的对局边界可区分。上表针对第一局完成时的结果。

## 解决的问题

- 只让 `GameState.DebugPrintPower` 修改模型，避免重复应用 `PowerTaskList` 动画流。
- 支持数字实体 ID、GameEntity 别名和含嵌套方括号的实体描述。
- 初始玩家信息可能只有占位名；从换牌选择日志中的 Player 与候选卡牌 controller 建立别名。普通选择不采用这个推断，以免将敌方目标控制者误认为选择者。
- 实际换牌记录在头部和实体列表之间有 `Source=GameEntity`，解析时保留上下文。
- 别名可晚于 TAG_CHANGE 出现，采用两遍离线处理；冲突别名保持未解析，不随意猜测。
- 按 CREATE_GAME 分隔对局；SHOW/CHANGE 更新卡牌 ID，HIDE 清除当前可见卡牌 ID。
- 读取开始时限定文件字节长度，避免持续追加延长本次读取；忽略没有换行结束的最后一行。

## 明确边界

这是离线诊断回放，不是实时 ObservationSource。它还不输出自动执行需要的“完整局面”或合法动作。

`ignored_power_records` 包含尚未应用的事件，当前没有完整处理 BLOCK、SHUFFLE、选项、选择与所有机制；零未解析引用只证明已支持事件中的实体可解析，不代表游戏规则完整。

标签保留原字符串；未出现的标签不默认填 0。HIDE 后其他标签只是最后观测值，不保证仍是当前值。没有还原隐藏手牌身份，也没有实现我方识别、动画稳定性或回合行动截止时间。

下一步：把离线事件解析拆成逐行增量事件与状态归并，处理别名待解析队列、日志轮换/截断和断线重连；在快照中区分事实、未知与最后观测值，再接模型。
