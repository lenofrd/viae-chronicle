# 交涉动力学

## 1. 目的
定义会话中每一轮回应的计算逻辑。这不是一个简单的“Yes/No”判断，而是跨过门槛的过程。

## 2. 核心概念
- **说服门槛（Persuasion Threshold）**：接收方同意诉求所需的阈值。
- **门槛的构成**：信任门槛（trust）、利益冲突（interest_conflict）、情绪门槛（emotion）、信息不对称（information_gap）、规范门槛（norm）。
- **回应选项池（Response Pool）**：
  - **同意（Accept）**：直接接受。
  - **拒绝（Reject）**：直接驳回。
  - **拖延（Delay）**：不表态，要求时间。
  - **提条件（Counter）**：同意，但要求补偿。
  - **试探（Probe）**：反问，探底牌。
  - **情绪化（Outburst）**：生气、委屈、道德绑架。

## 3. 演化规则

### 3.1 门槛计算
```
条件：接收到 proposal
效果：Compute:
      trust_score = initiator 对 responder 的 trust
      interest_score = responder 认为该诉求对自身利益的损害/收益
      emotion_score = responder 的压力和恐惧
      norm_score = 诉求是否违背接收方的性别规范
      
      总阻力 (Resistance) = weight1 * (1 - trust_score) 
                          + weight2 * interest_risk 
                          + weight3 * emotion_volatility 
                          + weight4 * norm_violation
```

### 3.2 回应选择逻辑
```
条件：计算出总阻力
效果：如果 Resistance < 接受阈值：选择 [同意]
      如果 Resistance > 破裂阈值：选择 [拒绝] 或 [情绪化]
      如果在两者之间：
        如果诉求价值高且接收方资源稀缺：选择 [提条件]
        如果接收方信任低且想探底：选择 [试探]
        如果接收方感到压力或时间不够：选择 [拖延]
```

### 3.3 信息不对称与谎言
```
条件：发起方掌握接收方不知道的信息（如快下雨了、粮价要涨）
效果：发起方可在 proposal 中加入隐瞒或虚假承诺
      若接收方没有识破（看信任度和认知），门槛降低
      若识破，信任大幅下降，直接转入拒绝或情绪化
```

### 3.4 规范门槛（性别影响）
```
条件：诉求违背接收方内化的社会规范
效果：如“女性向男性借巨款”、“男性要求妻子去抛头露面做买卖”
      直接增加 Resistance
      接收方可能触发 [情绪化] 的“你怎么能这样”回应。
```