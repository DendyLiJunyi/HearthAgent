# Hearth Agent

Rust 主控 + 可替换本地模型后端的炉石 Agent 工程起点。

当前版本支持本地环境检测、Power.log 离线回放、实时 JSON 观测，以及离线决策与执行保护演示。
**通过游戏日志读取观测，尚未连接本地模型，不会读取游戏进程内存或发送鼠标输入。实时观测仍标记为不可执行。**

## 运行

```powershell
cd D:\HearthAgent
cargo run --offline -- demo
cargo run --offline -- inspect D:\Hearthstone
cargo run --offline -- watch D:\Hearthstone
cargo run --offline -- replay <Power.log路径> --json
cargo test --offline
cargo clippy --offline --all-targets -- -D warnings
```

当前无第三方依赖，需要已安装 Rust 工具链。离线示例中的卡牌实体和动作是虚构测试数据。

## 目录与接口

- `src/protocol.rs`：快照、候选、决策及 `ObservationSource`。
- `src/policy.rs`：`PolicyBackend` 和选择第一个候选的演示基线。
- `src/executor.rs`：`ActionExecutor` 和仅记录的执行器。
- `src/controller.rs`：过期决策、交互阶段和重复尝试检查。
- `src/board.rs`：公开局面类型化与隐藏区域遮蔽，缺失属性保持未知。
- `src/structure.rs`：Power block/sub-spell 边界和 metadata 序列诊断。
- `src/export.rs`：实时/离线共用的 JSON 序列化。
- `src/options.rs`：日志选项包、目标和失效标记，尚不作为可执行候选。
- `tests/control_loop.rs`：状态变化、超时重试、阶段约束等测试。
- `docs/design.md`：完整初步设计。
- `docs/roadmap.md`：后续接入顺序。

`Recorded` 只表示离线记录，不能解读为真实游戏执行成功。候选的炉石规则合法性由未来适配器/规则模块保证；当前控制器只检查协议身份与交互阶段。

接入真实模型时实现 `PolicyBackend`；读取游戏时实现 `ObservationSource`；执行游戏操作时实现 `ActionExecutor`。模型计算后必须重新采集状态，不能把旧输入原样作为“新状态”交给执行器。

当前尝试账本只保存在内存中。进程重启后，未来的真实适配器必须重新同步；一次状态只能提交一次动作，超时需通过重新观察和协调恢复，不能用改决策 ID 的方式重发。

用户已指定 Laya；模型与本地服务接口调查见 [Laya 接入](docs/laya.md)。尚未安装模型或验证炉石决策能力。Rust 核心不依赖 Hearthbuddy/GreyMagic DLL，未复制其反编译实现。

日志接入说明：[实时监听](docs/watch.md)，[第三局验证](docs/third-game-validation.md)。
