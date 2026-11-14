# 交互状态与记录

## 1. 目的
定义会话在事件流中的记录方式，以及交互历史的查询语义。

## 2. 记录结构（Session Cluster）
交互不是零散的事件，而是一个**会话簇**。
```json
{
  "session_id": "sess_001",
  "tick_start": 50,
  "tick_end": 52,
  "initiator_id": "agent_a",
  "responder_id": "agent_b",
  "topic": "borrow_grain",
  "importance": 0.8,
  "rounds": [
    {"round": 1, "actor": "agent_a", "action": "propose", "text": "借我三斗米"},
    {"round": 1, "actor": "agent_b", "action": "counter", "text": "要借可以，拿你家那块坡地做抵押"},
    {"round": 2, "actor": "agent_a", "action": "accept", "text": "好，秋收后还你"}
  ],
  "outcome": "agreement",
  "relation_impact": {"trust_delta": -0.1, "obligation_delta": 3.0}
}
```

## 3. 人生轨迹查询
- 一次会话在人物的传记中呈现为一个完整的章节。
- 查询某人经历时，按 `initiator_id` 或 `responder_id` 过滤事件流，即可还原所有会话簇。
- **文字渲染示例**：
  > `第 50 天，张三向李四借粮。李四试探底线并索要土地抵押，张三犹豫一轮后同意。最终借到三斗米，但张三对李四的信任下降。`

## 4. 查询接口
```
get_agent_sessions(world_id, agent_id, since_tick=None, until_tick=None) -> List[SessionCluster]
get_session_detail(world_id, session_id) -> SessionCluster
```

## 5. 与其他系统的接口
- 读：会话的完整轮次、结果、影响。
- 写：记录系统的会话簇；人物系统的人生轨迹；03-relationships 的关系变化历史。

## 6. 横切引用
- SessionCluster 是全局 `10-state-and-records/` 事件流的投影：事件流不可变、按 `agent_id` 索引、带 `cause_event_id` 因果链；会话簇由属于同一 `session_id` 的事件聚合而成。
