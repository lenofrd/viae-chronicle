# 行动类型

## 1. 目的
定义人物能执行的具体动作，并区分“符合社会期望”与“越轨行为”。

## 2. 动作清单（第一版）

### 2.1 生存与生产（普遍适用）
- `eat`：消耗食物，降低饥饿。
- `sleep`：恢复体力。
- `farm`：在田地劳作，提升作物长势。
- `collect_water`：从河流/水井取水。
- `gather_firewood`：砍柴，影响植被。
- `hunt` / `fish`：获取肉类，影响动物种群。
- `cook`：消耗柴薪和生食，产出可吃食物。
- `raise_livestock`：喂养照料家畜（消耗饲料，增加家畜健康）。
- `graze`：放牧（消耗体力，若越界可能触发邻里或地界冲突）。
- `use_ox`：使用役畜（如牛）拉犁，大幅提升 `farm` 的劳作效率（消耗家畜体力）。
- `slaughter`：宰杀家畜（获得肉类，同时家畜资产从系统中移除）。

### 2.2 人际交互（普遍适用）
- `talk`：发起对话。
- `trade`：交换物资。
- `help`：帮助他人。
- `conflict`：攻击、争吵。

### 2.3 移动（普遍适用）
- `move`：从当前节点走到另一节点。

### 2.4 传统性别规范关联动作（可能产生 norm_penalty）
- **男性主导（女性执行会有惩罚）**：深山伐木、重型开垦、祭祖主祭。
- **女性主导（男性执行会有惩罚）**：纺织、精细采集、照顾幼儿。

### 2.5 越轨动作大类（Deviant Actions）
*注：系统只提供动作类型，具体某动作是否违法、严重度多少，由地点配置（location rules）决定。*

- `steal_asset`：窃取资产（可指向食物、财物、家畜）。
- `violate_rule`：违背制度（如截水、越界、盗伐、盗猎）。
- `assault`：人身攻击。
- `sacrilege`：亵渎信仰（破坏神树、冒犯禁忌）。

## 3. 演化规则
```
条件：决策系统选定动作
效果：检查前置条件（体力、怀孕状态、社会硬限制）
      若违背制度硬限制（如女性不能继承），直接失败
      若违背软限制（如女性进深山），执行成功但产生角色冲突压力和舆论风险
      满足条件则执行，修改状态，生成 action_executed 事件。
```

## 4. 可行性门控（任务 08 补充）

### 4.1 farm 长势封顶
- 当前作物模型为简化标量：`world.state.field_growth` 以节点为键存 0–100 的长势值，agent 取其 `work_node` 对应值作为感知字段 `work_field_growth`。完整作物模型见 `human-environment/01-production/...` 下的作物设计（未来落地），当前以标量近似。
- 当 `work_field_growth >= agriculture.max_field_growth`（长势封顶）时，`farm` 在**决策评分阶段即判为不可行**（返回 `IMPOSSIBLE`），而非仅降分——避免长势已满仍无效劳作、白白消耗体力，且封顶后不再产生 `farm` 事件。
- 所有动作均不可行时，沿用现有兜底（无动作、不崩溃），可通过观察层排查。

## 5. 采集类生计与未来接入指南（任务 09）

### 5.1 通用采集机制（不写死动作名）
打猎（`hunt`）是首个「采集类动作」，与 `eat/rest/farm/...` 这类硬编码基础动作不同，采集动作走**配置驱动的通用分支**：
- 候选动作由 `_candidate_actions(tuning)` = 基础动作 + `tuning.gathering.actions` 的键动态生成；
- 目标节点由 `gathering.actions[action].target_node` 指定（`_target_node` 通用解析）；
- 执行走 `AgentModule._execute_gather`：成功率 = `base × season_modifier × bad_weather_mult`，成功则 `setattr(agent, output_field, +amount)`，受伤独立判定（`max(0, health - loss)` 不致死）；
- 事件统一为 `gather_success` / `gather_fail` / `gather_injury`，payload 带 `action`/`output_field`，观察层按 `GATHER_DESC` 映射中文动词与产物。
- `agents.py` 中**不出现** `if action == "hunt"` 式散落分支，新增第二生计无需改核心结算（`_settle` 催收/回血）。

### 5.2 接入新生计（以渔业为例）的步骤
1. **资源节点**：在 `config/worlds/<world>/spatial-units.yaml` 声明或复用一个资源节点（如水域 `river_town`），无需改代码。
2. **状态字段**：在 `src/vale/core/state.py` 的 `AgentState` 加产出字段 `fish: float = Field(default=0, ge=0)`。
3. **配置**：在 `agents.yaml` 的 `tuning.gathering.actions` 下加一项（`target_node` / `output_field: fish` / 成功率 / 产出 / 季节修正 / 风险）；在 `action.fulfill` / `stamina_cost` / `outdoor` 加 `fish`；在 `physiology.food_fields` 追加 `"fish"`（使 `eat` 可消耗）。
4. **观察层**：在 `render.py` 的 `GATHER_DESC` 加一行 `"fish": ("捕鱼", "鱼")`，三种 gather 事件渲染自动复用，无需新增渲染函数。
5. **核心结算**：`_settle`（催收/回血）**不用改**——这正是扩展点验证目标。
6. 写测试：在 `tests/test_hunting_and_sustainability.py` 仿照 `test_execute_gather_works_for_arbitrary_action_name` 加用例，断言新动作产出到指定字段且结算事件照常。

### 5.3 守恒与可追溯
- 每次采集产出写入 `gather_success` 事件（`output_before/after` + `amount`），可重建世界总产出；
- `eat` 按 `food_fields` 优先级消耗，粮与肉各自守恒、不为负；
- 打猎不凭空消灭角色（受伤 `max(0, ...)`），死亡仍只由 `health<=0` 触发生命周期。