# 会话结构

## 1. 目的
定义一次会话（Session）的生命周期、参与方、核心字段，以及会话的开启和关闭条件。

## 2. 核心概念
- **会话（Session）**：一次交互的完整过程，由多轮（Rounds）组成。
- **发起方（Initiator）**：提出诉求或开启话题的人。
- **接收方（Responder）**：被请求或回应的人。
- **话题（Topic）**：这次交互的核心目的（借粮、商量婚期、争论水权）。
- **诉求（Proposal）**：发起方具体要什么（如“借我三斗米”）。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| session_id | string | 唯一 ID |
| topic | enum | 借粮/求爱/争论/换工/调解 |
| initiator_id | string | 发起方 |
| responder_id | string | 接收方 |
| current_round | int | 当前轮数 |
| stage | enum | 试探/交锋/僵持/达成/破裂/悬置 |
| proposal | dict | 当前的条件（如借粮数量、利息） |
| pending_effect | dict | 若达成，将要执行的状态改变 |

## 4. 演化规则

### 4.1 发起会话
```
条件：人物决策系统选择 talk / trade / help 等动作
效果：生成 session_started 事件
      stage = 试探
      进入第 1 轮
```

### 4.2 轮次结算
```
条件：发起方提出诉求
效果：Responder 按 02-negotiation-dynamics 的规则生成回应
      根据回应的结果（接受、拒绝、反提条件）更新 proposal 和 stage
      生成 session_round_completed 事件
```

### 4.3 结束条件
```
条件：满足以下之一
- 达成（Responder 同意 proposal）
- 破裂（Responder 拒绝或发起方放弃）
- 悬置（超过最大轮数，或某方因时间/体力原因离场）
效果：stage = 达成/破裂/悬置
      生成 session_ended 事件
```

### 4.4 悬置处理
```
条件：会话悬置
效果：记录 pending_effect，允许在未来的某个 tick 重新发起
      悬置的会话可能因环境变化（如灾荒加剧）自行破裂
```