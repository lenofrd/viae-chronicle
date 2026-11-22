# 建筑节点

## 1. 目的
定义建筑节点作为人文空间单元的字段、属性、状态，以及建筑状态如何随事件变化。建筑是人物行动的物理依托，也是社会意义的载体。

## 2. 核心概念
- **建筑节点**：有名字、有位置、有功能、有状态的场所。
- **功能**：建筑的主要用途（居住、加工、祭祀、议事、交易、医疗、教育）。
- **社会意义**：建筑在社区中的象征意义和行为规范。
- **状态**：建筑是否完好、是否开放、当前谁在场、正在发生什么。
- **声誉标签**：建筑因历史事件形成的社区印象（如“被罚过的地方”“说亲常去的地方”）。

## 3. 建筑节点字段
| 字段 | 类型 | 说明 |
|---|---|---|
| building_id | string | 唯一 ID，如 `brookvale/ancestral-hall`、`brookvale/mill` |
| name | string | 显示名，如“祠堂”“磨坊” |
| building_type | enum | 居住/加工/祭祀/议事/交易/医疗/教育/信仰 |
| parent_space | string | 所属空间区域（如“镇中心”） |
| location_desc | string | 位置描述（如“镇中心北侧，地势较高”） |
| function | string | 主要功能描述 |
| social_significance | dict | 行为规范、禁忌、适合话题 |
| access_rules | dict | 谁能进、什么时候能进、需要什么条件 |
| condition | enum | 完好/受损/废弃 |
| openness | enum | 开放/受限/关闭 |
| current_occupants | list | 当前在场人物 ID |
| ongoing_activity | string? | 正在发生的事 |
| reputation_tag | enum | 社会标签 |
| linked_buildings | list | 相邻或功能关联的建筑 ID |

## 4. 建筑类型示例（第一版可配置）
| 建筑 | 类型 | 社会意义 | 典型活动 |
|---|---|---|---|
| 祠堂 | 祭祀/议事 | 宗族权威、公开惩罚、婚丧仪式 | 祭祖、议事、惩罚、婚丧 |
| 磨坊 | 加工 | 粮食加工、议价、信息交换 | 磨面、排队闲聊、讨价还价 |
| 水井 | 公共 | 日常取水、洗衣、传谣 | 取水、洗衣、闲聊 |
| 私塾 | 教育 | 识字、向上流动的门槛 | 授课、拜师、家长交涉 |
| 药铺 | 医疗 | 治病、认药、采药 | 看病、抓药、交流草药知识 |
| 里正家 | 议事 | 处理纠纷、收税、对外联络 | 调解、收税、接待外人 |
| 山神庙 | 信仰 | 祭祀、禁忌、心理安慰 | 祭山神、求签、节庆 |
| 集市空地 | 交易 | 定期交换、买卖、传谣 | 赶集、买卖、看热闹 |
| 住家片区 | 居住 | 私人生活、家庭教养 | 做饭、休息、家庭互动 |

## 5. 演化规则

### 5.1 建筑状态变化
```
条件：事件触发（灾害、年久失修、人为破坏、修复）
效果：condition 在 完好/受损/废弃 之间迁移
      受损建筑的部分功能受限
      废弃建筑不再有常规活动
      生成 building_condition_changed 事件
滞后：修复需要时间和人力
影响范围：单个建筑
```

### 5.2 开放状态变化
```
条件：时段、事件、制度规则
效果：openness 在 开放/受限/关闭 之间迁移
      如祠堂平时关闭，议事和仪式时开放
      如山神庙节庆开放，平日关闭
      生成 building_openness_changed 事件
滞后：按事件触发
影响范围：单个建筑
```

### 5.3 在场人物更新
```
条件：每 tick，人物移动后
效果：current_occupants 更新为当前 tick 在该建筑的人物列表
      生成 occupants_changed 事件（仅当列表变化）
滞后：无
影响范围：单个建筑
```

### 5.4 活动状态更新
```
条件：每 tick，根据在场人物和时段
效果：ongoing_activity 更新为当前正在发生的事
      如“祭祖”“磨坊加工”“议事”
      生成 activity_started / activity_ended 事件
滞后：无
影响范围：单个建筑
```

### 5.5 声誉标签变化
```
条件：重大事件在同一建筑反复发生
效果：reputation_tag 变化
      如祠堂前多次公开惩罚 → “让人畏惧的地方”
      水井边多次传谣 → “是非之地”
      生成 reputation_tag_changed 事件
滞后：多次事件累积后才变化
影响范围：单个建筑
```

### 5.6 访问拒绝
```
条件：人物尝试进入不满足 access_rules 的建筑
效果：生成 space_access_denied 事件
      人物移动失败或改去别处
滞后：无
影响范围：人物和建筑
```

## 6. 事件类型
- `building_condition_changed`：{building_id, old, new, cause}
- `building_openness_changed`：{building_id, old, new, cause}
- `occupants_changed`：{building_id, old_list, new_list}
- `activity_started` / `activity_ended`：{building_id, activity, participants}
- `reputation_tag_changed`：{building_id, old, new, cause}
- `space_access_denied`：{agent_id, building_id, reason}

## 7. 与其他系统的接口
- 读：自然环境 01-spatial-skeleton 的空间单元定义；02-institutions 的制度规则；08-rituals-beliefs 的仪式安排。
- 写：人物系统读建筑状态和 access_rules 做移动决策；04-information 读在场人物和活动状态判断信息流动；记录系统读建筑状态作为场景锚点。
- 因果链：灾害 → 建筑受损 → 功能受限 → 人物改去别处 → 其他场所压力上升。

## 8. 地点参数占位
- 建筑节点清单：ID、名称、类型、位置、功能、初始状态
- 每个建筑的社会意义：行为规范、禁忌、适合话题
- 每个建筑的 access_rules：谁能进、什么时候能进、需要什么条件
- 建筑之间的 linked_buildings
- reputation_tag 的初始值和变化条件