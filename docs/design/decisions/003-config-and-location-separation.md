# 003 - 强制分离“系统机制”与“地点配置”

- **状态**：已采纳 (Accepted)
- **日期**：2026-11-14
- **决策者**：架构组

## 1. 背景与上下文 (Context)
在设计小镇规则时，很容易将具体的世界内容（如“偷牛判几年”、“溪谷镇有几亩田”）直接写死在核心代码里，导致代码与特定世界（Brookvale）深度耦合，未来无法扩展城市或其他世界。

## 2. 决策 (Decision)
严格执行 **“机制与内容分离”**：
1. **系统层（`src/vale/modules/`）**：只写抽象机制。例如，代码里只有 `steal_asset` 这个动作大类，以及判定它违规的通用逻辑。
2. **配置层（`config/worlds/`）**：存放具体世界的 YAML 数据。例如，在 `brookvale-town-001` 里配置：`偷牛` = 触发 `steal_asset`，`severity` = 10，触发祠堂公开重罚。
3. **加载与校验**：必须使用 Pydantic 定义 Schema。启动时严格校验 YAML 的格式、字段类型、数值范围。不合格直接拒绝启动。

## 3. 后果与影响 (Consequences)

### 优势：
- **无限扩展**：未来要加入“修仙宗门”或“现代城市”，底层 Python 代码一行不用改，只需写新的 YAML 配置。
- **平衡性调整极快**：如果觉得旱灾太少，直接去 YAML 里改 `drought_threshold`，不用重启代码编译。
- **避免魔法数字**：代码里绝不出现 `if hunger > 80`，而是 `if hunger > config.starvation_threshold`。

### 代价：
- 需要维护一套相当复杂的 YAML 层级目录和 Pydantic Schema。
- 调试时，如果查不到数据，需要同时检查 Python 代码和 YAML 配置。
## 落地注记（E1 审计归位，2026-11-22）

正文「系统层（`src/vale/modules/`）」为当时（ADR 003 期）的单层模块布局举例。阶段二分层重构（ADR 009）后，机制层为 `src/vale/domains/{environment,wildlife,society}` 三域 + `src/vale/core` 内核 + `src/vale/contracts` 契约 + `src/vale/world` 组装与场景。正文不改；「机制与内容分离」原则不变。
