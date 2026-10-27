# 实时日志监听与 JSON 快照

## 使用

```powershell
cd D:\HearthAgent
cargo run --offline -- watch D:\Hearthstone
```

每 500ms 检查最新会话和日志追加内容，改变时向标准输出写一行 JSON；Ctrl+C 退出。watch 尚未接入模型（另有合成 laya-demo），不会进行鼠标操作或进程附加。

只检查一次：

```powershell
cargo run --offline -- watch D:\Hearthstone --once
```

`--once` 最多处理 4 MiB；若输出 `backlog=true`，使用持续监听追上剩余记录，不能把该结果当文件末尾状态。没有日志时输出 waiting 状态，不回退到旧会话。

## 快照约定

- `protocol_version=1`。
- `session_id` 含本次 watcher 运行标识、日志会话名和重置代数；不同运行的快照不能混用。
- `revision` 在发布改变后递增，空闲轮询不重复发布。
- `game_number` 在当前文件代数内按 GameState CREATE_GAME 递增，切局后不保留上一局实体。
- `observed_at_unix_ms` 是本次采集时间，不是游戏事件时间，也不证明游戏仍在运行。
- `generation`：日志替换、截断、新会话等导致读取状态重置时增加。
- `pending_bytes`：尚未有换行符结束的字节，可能含半个 UTF-8 字符。
- `game`：实体 ID、当前已知卡牌 ID、`last_observed_tags`、玩家编号到实体 ID 的映射和解析诊断。
- `game.board`：带未知值与隐藏区域遮蔽的类型化视图；`game.power_structure`：嵌套边界及元数据序列诊断。详见 [局面字段](board.md)。
- `perspective`：与 `game.board.perspective` 一致；仅在本地普通回合提交和完整回合标志支持时给出玩家编号，否则 null。切局或传输重置清空。详见 [识别依据及限制](board.md)。
- `complete=false`、`actionable=false`：当前所有观测都不能直接交给执行器。规则、动画稳定性、合法动作和隐藏信息时效尚未验证。

示意：

```json
{
  "protocol_version": 1,
  "revision": 1,
  "complete": false,
  "actionable": false,
  "perspective": null,
  "status": "observed_log_state",
  "pending_bytes": 0,
  "backlog": false,
  "game": {
    "game_entity": 1,
    "players": [{"player_id": 1, "entity_id": 2}],
    "entities": [{"id": 1, "card_id": null, "last_observed_tags": {"TURN": "1"}}],
    "unresolved_references": 0
  }
}
```

示意省略部分字段。名字和账号 ID 不放入输出；标签名和值以 JSON 字符串保留，未出现的标签保持未知。隐藏后仍保留的其他标签只是历史观测值，不能当实时隐藏状态。

## 实现和边界

`src/watch.rs` 实现文件读取偏移、部分行缓冲与会话状态。只读新增字节，当前无新增相关事件时不重新归并。

为正确处理晚到别名，当前将这一局已收集的相关行交给原离线 reducer 再归并。每个变化批次的归并成本与当前局长度相关；不重读整个文件、不保存前几局，但还不是逐事件 O(1) 更新器。之后可用带序号的未决事件和每字段版本替代重建。

读取窗口每批上限 4 MiB；单行上限 1 MiB；当前局缓存上限 64 MiB。超过限制或读写竞争导致读取错误时，输出 error/null 快照并退出，调用方必须丢弃先前状态。

通过文件长度、创建时间、已读前缀与末端检查点识别截断/常见替换。它不能保证检测“保留创建时间、长度、前缀和检查点，仅改动中间内容”的人为改写；面向游戏正常追加/轮换日志，不是文件防篡改工具。

日志不提供可操作性的证明，未实现进程存活检查或心跳。消费者需自行设置接收超时，不能将长时间未更新的 JSON 视作实时局面。`GAME STATE=COMPLETE` 只表示游戏结束，不等同于快照 `complete=true`。

原始玩家名暂存在当前局的私有解析缓存中，用于别名匹配；没有落盘或导出。缓存随切局/重置清除。

## 验证

最初监听相关 12 项覆盖：

1. 分批行与跨批次 UTF-8 字符。
2. 追加只更新一次、空闲不重复发布。
3. 新会话没有 Power.log 时作废旧局面。
4. 相同长度文件替换触发重置。
5. 截断与切局清除旧实体。
6. 晚到别名按原顺序归并，不覆盖更晚的数字 ID 更新，且不导出名字。
7. 无效 UTF-8 报错。
8. JSON 控制字符与引号转义。
9. 未知玩家别名保留为未解析事件，不猜测归属或修改另一玩家的属性。
10. 换牌提交名称通过选择 ID 关联，修复早期事件并保持更新顺序；实时与离线结果一致。
11. 普通选择及不匹配选择 ID 不推断玩家身份。
12. 选择 ID 对应多个玩家时不推断提交名称归属。

后续加入忽略类型统计、结构诊断、类型化局面、选项包与失效标记、回放内存限制、CLI 错误处理、Laya 客户端、视角推断和逐字节实时/离线等价验证。

另对本机真实日志执行 `watch --once`，并用独立 JSON 解析器读取输出，确认协议可解析。实际读取结果随游戏进程继续写入变化；没有执行自动打牌。

真实日志第三局的玩家名称在换牌提交时才出现。现已读取 `DebugPrintEntitiesChosen`，通过相同选择 ID 对应的 MULLIGAN 候选卡唯一控制者建立映射。修复后第三局未解析引用从 669 降为 0，前两局仍为 0。未知或冲突引用仍保留为未解析；解析成功或 backlog=false 不表示完整规则状态。详见 [第三局验证](third-game-validation.md)。

## 下一步

验证我方识别、实体可见性和帧稳定条件；把通用 tags 转成英雄、随从、手牌及法力视图，再接只读模型建议。生产化时仍需逐事件归并、重连处理和合法动作验证。
