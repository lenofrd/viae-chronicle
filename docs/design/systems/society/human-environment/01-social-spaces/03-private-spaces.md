# 私人空间

## 1. 目的
定义私人空间的特点、功能、信息保守规则、关系经营机制，以及私人空间如何影响人物行为。

## 2. 核心概念
- **私人空间**：住家、私家田地、私家作坊。有门槛，不是谁都能进。
- **信息保守**：在私人空间发生的事，只有在场的人知道，不公开传播。
- **关系经营**：私下交涉、借粮、说亲、调解在私人空间进行。
- **访问门槛**：进入私人空间需要关系、身份、邀请或理由。
- **亲密等级**：私人空间内部也有亲密等级（堂屋可以进，卧房不能进）。

## 3. 私人空间字段
| 字段 | 类型 | 说明 |
|---|---|---|
| space_id | string | 唯一 ID |
| space_type | enum | 住家/私田/私坊 |
| owner_id | string | 所有者/主要居住者 |
| intimacy_levels | dict | 不同区域的亲密等级（堂屋/灶房/卧房） |
| access_rules | dict | 谁能进、需要什么条件 |
| information_privacy | float 0–1 | 信息保守程度 |
| typical_activities | list | 典型活动（做饭、家庭教养、私下交涉） |
| current_occupants | list | 当前在场人物 |

## 4. 私人空间类型示例
| 空间 | 信息保守 | 访问门槛 | 典型活动 |
|---|---|---|---|
| 住家 | 高 | 需邀请或亲属关系 | 做饭、休息、家庭教养、私下交涉 |
| 私田 | 中 | 需所有者许可 | 劳作、私下交谈、查看庄稼 |
| 私坊 | 中 | 需业务关系或邀请 | 加工、议价、师徒传授 |

## 5. 演化规则

### 5.1 信息保守
```
条件：私人空间发生事件
效果：信息只传播给在场人物
      信息不会自动进入公共空间
      在场人物可以主动选择是否外传
滞后：无
影响范围：私人空间及在场人物
```

### 5.2 访问控制
```
条件：人物尝试进入私人空间
效果：检查 access_rules
      不满足则访问拒绝
      满足则进入，更新 current_occupants
      生成 space_access_granted / space_access_denied 事件
滞后：无
影响范围：人物和私人空间
```

### 5.3 私下交涉
```
条件：人物在私人空间进行交涉（借粮、说亲、调解）
效果：交涉内容不公开
      交涉结果影响关系状态
      生成 private_negotiation 事件
滞后：无
影响范围：参与交涉的人物和私人空间
```

### 5.4 亲密等级
```
条件：人物进入私人空间
效果：根据关系亲密度决定能进入哪些区域
      如陌生人只能进堂屋，亲属可进灶房，家人可进卧房
      违反亲密等级可能触犯规范
滞后：无
影响范围：人物和私人空间
```

### 5.5 家庭教养
```
条件：家庭成员在私人空间互动
效果：家庭教养事件发生
      子女人格倾向、价值观、技能受到影响
      见 05-education/family-upbringing.md
滞后：长期过程
影响范围：家庭成员
```

## 6. 事件类型
- `space_access_granted` / `space_access_denied`：{agent_id, space_id, reason}
- `private_negotiation`：{space_id, participants, topic, outcome}
- `private_event`：{space_id, event_type, participants, details}
- `intimacy_violation`：{space_id, agent_id, violation}

## 7. 与其他系统的接口
- 读：01-buildings 的建筑状态；03-relationships 的关系状态（决定访问权限）；05-education 的家庭教养规则。
- 写：03-relationships 读私下交涉对关系的影响；04-information 读信息保守（信息是否外传）；人物系统读访问权限做决策。
- 因果链：私下交涉 → 关系变化 → 信息是否外传 → 公共空间的传闻 → 舆论形成。

## 8. 地点参数占位
- 私人空间清单：ID、类型、所有者、intimacy_levels、access_rules
- information_privacy 程度
- 典型活动和规范
- 访问权限的关系阈值（陌生人/熟人/亲属/家人）