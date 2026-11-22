# 代际传递与断裂

## 1. 目的
定义长辈如何向晚辈传递价值观、技能、信仰、经验，以及代际之间的冲突和断裂。代际传递不是单向复制，是传递、选择、抗拒、冲突的过程。

## 2. 核心概念
- **传递内容**：价值观、技能、信仰、经验、禁忌、规矩。
- **传递方式**：日常教导、带在身边、讲故事、正式传授、仪式参与。
- **传递结果**：晚辈接受、部分接受、抗拒、反感。
- **代际断裂**：年轻人不信老规矩、看不上旧活计、追求新观念，产生冲突。
- **代际冲突**：长辈坚持传统，晚辈追求改变，冲突影响家庭和社区。
- **传递与地位**：代际传递影响晚辈的起点地位和技能基础。

## 3. 代际传递字段
| 字段 | 类型 | 说明 |
|---|---|---|
| transfer_id | string | 唯一 ID |
| elder_id | string | 长辈 |
| younger_id | string | 晚辈 |
| content_type | enum | 价值观/技能/信仰/经验/禁忌/规矩 |
| content | string | 具体内容 |
| method | enum | 日常教导/带在身边/讲故事/正式传授/仪式参与 |
| outcome | enum | 接受/部分接受/抗拒/反感 |
| internalization | float 0–1 | 内化程度 |

## 4. 演化规则

### 4.1 代际传递
```
条件：长辈向晚辈传递内容
效果：晚辈获得或强化对应状态
      internalization 受关系、内容、晚辈性格影响
      生成 teaching_event
滞后：长期过程
影响范围：晚辈
```

### 4.2 传递方式
```
条件：不同传递方式
效果：带在身边（身教）内化最深
      讲故事（言传）内化中等
      正式传授（技能）内化取决于学徒态度
      仪式参与（信仰）内化取决于庄严程度
      生成 transfer_method_effect 事件
滞后：长期过程
影响范围：晚辈
```

### 4.3 代际断裂
```
条件：晚辈抗拒传统、外部观念冲击、长辈失信
效果：晚辈不接受传递内容
      可能形成与长辈不同的价值观
      生成 generational_break 事件
滞后：长期过程
影响范围：晚辈和家庭
```

### 4.4 代际冲突
```
条件：长辈坚持传统，晚辈追求改变
效果：家庭关系紧张
      可能引发公开冲突
      生成 generational_conflict 事件
滞后：按冲突时机
影响范围：家庭和社区
```

### 4.5 传递与地位
```
条件：晚辈接受传递
效果：晚辈获得技能、价值观、关系网络
      起点地位受长辈地位影响
      见 06-stratification
滞后：成年时
影响范围：晚辈
```

### 4.6 断裂的后果
```
条件：代际断裂发生
效果：晚辈可能失去长辈支持
      可能另寻出路（学新手艺、向外）
      社区可能议论
      生成 break_consequence 事件
滞后：长期过程
影响范围：晚辈、家庭、社区
```

## 5. 事件类型
- `teaching_event`：{elder_id, younger_id, content_type, content, method, outcome, internalization}
- `generational_break`：{younger_id, elder_id, content_type, cause}
- `generational_conflict`：{parties, conflict_area, severity}
- `break_consequence`：{younger_id, consequence_type, severity}

## 6. 与其他系统的接口
- 读：03-kinship 的家庭关系；05-education 的其他五条线；04-information 的外来消息（冲击传统）；06-stratification 的流动意图。
- 写：人物系统的价值观、技能、信仰；06-stratification 的起点地位；03-relationships 的家庭关系；07-conflicts 的代际冲突。
- 因果链：父亲教儿子木工 → 儿子抗拒 → 代际断裂 → 儿子想学新手艺 → 家庭冲突 → 儿子向外意图增强。

## 7. 地点参数占位
- 传递内容清单
- 各传递方式的内化系数
- 代际断裂的触发条件
- 代际冲突的严重度
- 断裂后果的映射