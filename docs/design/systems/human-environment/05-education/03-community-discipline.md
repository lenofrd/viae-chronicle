# 社区规训

## 1. 目的
定义社区如何通过村规、舆论、惩罚、排挤让人学会规矩。社区规训是制度内化的主要通道，也是“什么能做、什么不能做”的深刻教育。

## 2. 核心概念
- **规训方式**：公开惩罚、私下训诫、舆论谴责、排挤孤立、围观议论。
- **规训场所**：祠堂（公开惩罚）、里正家（私下训诫）、水井边（舆论）、集市（围观）。
- **规训内容**：村规、禁忌、水权、地界、换工规矩。
- **内化**：被规训者可能内化规矩（认同）、表面服从（畏惧）、反感抗拒（叛逆）。
- **旁观者学习**：围观者通过观看惩罚学会规矩，不需要亲身经历。
- **规训与心理**：公开羞辱可能终身影响心理和地位。

## 3. 规训事件字段
| 字段 | 类型 | 说明 |
|---|---|---|
| discipline_id | string | 唯一 ID |
| agent_id | string | 被规训者 |
| rule_id | string | 违反的制度 |
| method | enum | 公开惩罚/私下训诫/舆论谴责/排挤/围观 |
| punishment_type | enum | 批评/赔礼/赔粮/罚工/公开羞辱/驱逐 |
| witnesses | list | 旁观者 |
| internalization | enum | 认同/表面服从/反感抗拒 |

## 4. 演化规则

### 4.1 公开惩罚
```
条件：严重违规，祠堂公开执行
效果：被规训者受到惩罚
      旁观者围观学习
      被规训者 internalization 取决于惩罚是否公正、关系、性格
      生成 discipline_event（method = 公开惩罚）
滞后：按惩罚执行
影响范围：被规训者、旁观者、社区
```

### 4.2 私下训诫
```
条件：轻微违规，里正私下训诫
效果：被规训者受到训诫
      没有旁观者，影响范围小
      被规训者可能接受也可能不服
      生成 discipline_event（method = 私下训诫）
滞后：按训诫执行
影响范围：被规训者
```

### 4.3 舆论谴责
```
条件：违规被传播，邻里议论
效果：被规训者感受到舆论压力
      舆论影响 trust 和地位
      可能促使被规训者改正或更加抵触
      生成 discipline_event（method = 舆论谴责）
滞后：舆论形成需要时间
影响范围：被规训者、邻里
```

### 4.4 排挤孤立
```
条件：严重违规或长期不改
效果：被规训者被排挤（不换工、不借粮、不往来）
      地位下降，生存困难
      可能迫使被规训者离开（第一版只记录意图）
      生成 discipline_event（method = 排挤）
滞后：长期过程
影响范围：被规训者、社区
```

### 4.5 旁观者学习
```
条件：旁观者目睹规训
效果：旁观者内化规矩（不一定需要亲身被罚）
      形成“什么能做、什么不能做”的认知
      生成 observer_learning 事件
滞后：按围观时机
影响范围：旁观者
```

### 4.6 内化结果
```
条件：规训事件后
效果：被规训者形成 internalization
      认同 → 规矩内化，以后自觉遵守
      表面服从 → 畏惧，可能偷偷违反
      反感抗拒 → 可能反复违反，成为“刺头”
      生成 internalization_changed 事件
滞后：长期过程
影响范围：被规训者
```

## 5. 事件类型
- `discipline_event`：{agent_id, rule_id, method, punishment_type, witnesses, internalization}
- `observer_learning`：{observer_id, discipline_id, lesson, internalization}
- `internalization_changed`：{agent_id, rule_id, old, new, cause}
- `social_exclusion_started` / `social_exclusion_ended`：{agent_id, cause}

## 6. 与其他系统的接口
- 读：02-institutions 的违规和惩罚；01-social-spaces 的祠堂、水井、集市；04-information 的舆论传播。
- 写：人物系统的 norms_internalized；03-relationships 的排挤和关系变化；06-stratification 的地位下降；02-institutions 的规则强化或松动。
- 因果链：偷盗 → 祠堂公开惩罚 → 围观者学习 → 被罚者地位下降 → 邻里排挤 → 被罚者可能改过或更加抵触。

## 7. 地点参数占位
- 规训方式清单
- 各惩罚类型的内化系数
- 旁观者学习的概率
- 排挤的触发条件和持续时间
- 内化结果的影响因素（公正性、关系、性格）