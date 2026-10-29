# 本机接入调查（2026-10-27）

## 已确认

- 安装目录：`D:\Hearthstone`。
- Hearthstone.exe / UnityPlayer.dll 文件版本：`6000.3.11.3145967`。
- 存在 `MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll` 与 `Hearthstone_Data/Managed/Assembly-CSharp.dll`，该安装包含 Mono 托管游戏代码。
- 本次 Assembly-CSharp.dll SHA256：`786376BDDAD544709639D4B3AB60CE8799D4B1C6C7D7FC4C225CE79FE07228C6`。
- 检查时没有运行中的 Hearthstone 进程。
- 初次检查最新日志会话是 `Hearthstone_2026_10_27_00_07_53`，可见大厅/开包切换，没有 Power.log；不能据此重建对局。
- 标准 AppData 路径下的 log.config 已存在 `[Power]`、`LogLevel=1`、`FilePrinting=true`、`Verbose=true`。未修改配置。

## 游戏侧实现的静态证据

本次只读反编译本机 Assembly-CSharp.dll，未加载执行程序集。

- `GameState.Get()` 返回静态字段 `s_instance`。
- `GameState` 含 `Map<int, Entity> m_entityMap`。
- `GetEntity(int id)` 对该 map 调用 `TryGetValue` 并返回实体。
- `Entity` 继承 `EntityBase`；`EntityBase` 保存 `TagMap m_tags` 和卡牌 ID 相关字段。
- `GetFriendlySidePlayer()` 遍历玩家映射，筛选友方和队伍领队。
- `Log` 声明 Power、Options、Zone 等日志分类；存在分类不代表当前已开启或输出所需完整数据。
- `Log.LogsPath` 的 Windows 分支返回 `Application.dataPath + "/../Logs"`。

这些是游戏内部真实方法，而不是 Hearthbuddy 的受保护代理空壳。它们明确了对象关系，但没有提供跨进程直接调用权限、当前内存地址、字段偏移或已完成的桥接。后续 Mono 适配仍需解决实例定位、对象生命周期与线程时机，不能把游戏 DLL 当本地 SDK 直接加载即可读取运行游戏。

反编译材料保留在原研究工作区 `.analysis/output/Local*.cs`，未把游戏源码复制进此工程。

## 新增诊断命令

```powershell
cd D:\HearthAgent
cargo run --offline -- inspect D:\Hearthstone
```

只读检查安装文件、按标准时间戳目录名称选取最新会话、读取最后记录的场景和 Power.log 标记计数。

它不会启动游戏、附加进程、读取账户日志正文、执行点击或调用模型。日志计数可能包含重复流，只用于可用性诊断；不是对局次数或去重后的实体事件。没有 Power.log 时不会返回一个虚假的“完整空场”。它也不判断游戏进程是否存活。

## 下一次真实验证

启动炉石，进入练习对局，完成换牌并打出一张牌，再运行 inspect。若配置是在当前进程启动后才写入，需要退出并重新启动游戏。

获得 Power.log 后，先核对创建游戏、创建/显示实体、tag 变化、回合、选择与选项的实际文本格式，再实现增量解析和局面归并。需要处理日志轮换、多个同名事件流、未结束的最后一行、隐藏卡牌和会话重置。

当前仅完成接入调查与诊断工具；尚未完成实时状态采集、合法动作生成、进程桥接或自动打牌。
