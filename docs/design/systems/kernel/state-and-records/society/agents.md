# 人物状态与记录

## 1. 目的
定义人物快照的结构，以及人生轨迹的查询方式。

## 2. 快照结构
```json
{
  "agent_id": "female_agent_01",
  "tick": 100,
  "physical": { 
    "sex": "female", "age": 22, "health": 90, "hunger": 40, "stamina": 80,
    "pregnancy_stage": "none"
  },
  "psychological": { 
    "stress": 30, "fear": 10, "valence": 0.1, "role_conflict_pressure": 40 
  },
  "needs": { "survival": 0.8, "economy": 0.6 },
  "location": "field_east",
  "current_action": "farming",
  "gender_norms": { "female_outdoor": 0.3, "female_medicine": 0.8 }
}
```

## 3. 人生轨迹查询
- 人的一生由 `event_log` 中 `agent_id` 对应的所有事件组成。
- 关键事件包括：生育、突破性别规范的尝试、角色冲突爆发、婚丧嫁娶、生老病死。
- 按 tick 排序后，呈现一段充满社会羁绊与个人选择的传记。

## 4. 横切引用
- 快照与事件流遵循全局 `10-state-and-records/` 规范：事件流不可变、按 `agent_id` 索引、带 `cause_event_id` 因果链；人物快照可从事件流投影生成。