# 地位与角色

## 1. 目的
定义角色的地位层级、社会角色、财富、声誉，以及地位如何随事件变化。地位是流动的起点和结果。

## 2. 核心概念
- **地位层级**：贫户、自耕农、富户、工匠、里正、长老。
- **社会角色**：农夫、织户、木匠、郎中、货郎、学徒、里正、长老。
- **财富**：粮、田、钱、工具、房屋。
- **声誉**：社区对角色的评价（勤劳、诚实、刻薄、懒惰）。
- **地位变化**：通过财富积累、技能提升、婚配、继承、争里正、声誉变化。
- **地位与关系**：高地位者在关系中更有话语权；低地位者依赖关系网络。

## 3. 地位层级（第一版）
| 地位 | 特征 | 典型角色 |
|---|---|---|
| 贫户 | 少地或无地，靠帮工、租地 | 帮工、佃户、寡妇 |
| 自耕农 | 有少量田地，自给自足 | 农夫、织户 |
| 富户 | 田地多，有余粮，可能放贷 | 大户、粮商 |
| 工匠 | 有手艺，收入稳定 | 木匠、郎中、磨坊主 |
| 里正 | 社区管理者，有制度权力 | 里正 |
| 长老 | 年长有威望，参与议事 | 长老 |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| status | enum | 地位层级 |
| roles | list | 社会角色 |
| wealth | float | 财富水平 |
| reputation | float -1–1 | 声誉 |
| status_trend | enum | 上升/稳定/下降 |

## 5. 演化规则

### 5.1 财富变化
```
条件：收成、交易、借还、灾害、继承
效果：wealth 按事件变化
      财富跨过阈值 → status 可能变化
      生成 wealth_changed 事件
滞后：按事件
影响范围：角色
```

### 5.2 声誉变化
```
条件：日常行为、公开事件、舆论
效果：reputation 按行为变化
      勤劳、诚实、互助 → 声誉上升
      懒惰、欺诈、违规 → 声誉下降
      受 max_delta_per_tick 约束
      生成 reputation_changed 事件
滞后：渐进，舆论形成需要时间
影响范围：角色
```

### 5.3 角色获取与失去
```
条件：拜师学成、婚配、继承、被选为里正、年老退位
效果：roles 增加或减少
      生成 role_gained / role_lost 事件
滞后：按事件
影响范围：角色
```

### 5.4 地位变化
```
条件：财富、声誉、角色综合变化
效果：status 跨阈值迁移
      上升：贫户→自耕农→富户；自耕农→工匠
      下降：富户→自耕农→贫户
      生成 status_changed 事件
滞后：长期过程
影响范围：角色
```

### 5.5 地位与关系
```
条件：地位变化
效果：高地位者在关系中话语权上升
      低地位者依赖关系网络
      影响 trust 和 interest_weight 的不对称
      生成 status_relation_effect 事件
滞后：渐进
影响范围：关系网络
```

### 5.6 地位与心理
```
条件：地位上升或下降
效果：地位上升 → 自信、aspiration 上升
      地位下降 → 焦虑、aspiration 变化（更强或放弃）
      生成 status_psychological_effect 事件
滞后：按事件
影响范围：角色
```

## 6. 事件类型
- `wealth_changed`：{agent_id, old, new, cause}
- `reputation_changed`：{agent_id, old, new, cause}
- `role_gained` / `role_lost`：{agent_id, role, cause}
- `status_changed`：{agent_id, old, new, cause}
- `status_relation_effect`：{agent_id, relation_id, effect}
- `status_psychological_effect`：{agent_id, effect, severity}

## 7. 与其他系统的接口
- 读：05-soil-and-fields 的收成；03-debt 的借贷；05-education 的技能；02-institutions 的制度角色；04-information 的舆论。
- 写：03-relationships 的权力不对等；07-conflicts 的阶层冲突；人物系统的心理和 aspiration；记录系统的人生主线。
- 因果链：连续丰收 → wealth 上升 → status 从自耕农升为富户 → 关系中话语权上升 → 可能被选为里正。

## 8. 地点参数占位
- 地位层级定义和阈值
- 角色清单和获取条件
- wealth 阈值
- reputation 变化系数
- 地位变化的综合规则
- 初始角色的 status、wealth、reputation