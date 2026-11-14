# 教育子系统总览

## 1. 目的
定义 Brookvale 的人文环境如何持续塑造人：家庭教养、生计技能、社区规训、仪式信仰、信息经验、代际传递。教育不是独立的“教育系统”，而是嵌在日常生活里的总机制。它回答“一个人怎么一点点变成现在这个样子”。

## 2. 核心概念
- **家庭教养**：谁带大、听什么故事、看父母怎么处理纠纷，传递价值观、性别角色、辈分规矩、生存态度。
- **生计技能**：跟着父母下田、跟船捕鱼、跟老人采药、跟母亲织布、跟师傅学木工。教育嵌入在生产里，失败也是教育。
- **社区规训**：村规、舆论、惩罚、排挤。通过围观、议论、被罚、被孤立让人学会规矩。
- **仪式信仰**：祭山神、祭祖、婚丧节庆、禁忌，塑造世界观和“什么不能碰”。
- **信息经验**：洪水冲过哪块田、哪条山路会滑坡、谁家借粮不还，通过老人讲述和邻里闲聊进入认知。环境事件本身就是教材。
- **代际传递与断裂**：老人教孙辈、师傅带徒弟，但年轻人可能不信老规矩、看不上旧活计，产生冲突。
- **教育事件**：每个教育行为是一个事件，带施教者、受教者、内容、结果（接受/抗拒/部分接受）。
- **教育线**：一个人的教育线是他一生中所有教育事件的序列，可追溯“他怎么变成现在这个人”。

## 3. 教育状态变量（按角色挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| values | dict | 价值观（如勤劳/节俭/孝顺/冒险） | 慢变，按事件 |
| gender_role_beliefs | dict | 性别角色观念 | 慢变 |
| hierarchy_beliefs | dict | 辈分和权威观念 | 慢变 |
| survival_attitudes | dict | 生存态度（谨慎/冒险/依赖/自立） | 慢变 |
| skills | dict | 技能等级（农事/捕鱼/采药/木工/织布/识字） | 按学习实践 |
| norms_internalized | dict | 内化的社区规范 | 按规训事件 |
| world_view | dict | 世界观（敬畏山神/相信禁忌/怀疑传统） | 慢变 |
| knowledge_experience | list | 从经验中获得的知识 | 按事件 |
| education_history | list | 教育事件序列 | 只追加 |

## 4. 演化规则分类
- tick 驱动：技能随实践缓慢提升；价值观随年龄和经历缓慢变化。
- 事件驱动：家庭教养事件、技能学习事件、社区规训事件、仪式参与、经验学习、代际教导。
- 累积效应：多次教育事件累积成稳定的价值观和技能。
- 外部注入：接口写入的教育事件（如“外来先生授课”），标注为外部事件。

## 5. 事件类型
- `upbringing_event`：{child_id, caregiver_id, content, outcome}
- `skill_learning_event`：{learner_id, teacher_id, skill, progress, outcome}
- `discipline_event`：{agent_id, rule_id, punishment_type, witnesses, internalization}
- `ritual_participation`：{agent_id, ritual_id, role, belief_effect}
- `experience_learning`：{agent_id, event_id, lesson, internalization}
- `teaching_event`：{teacher_id, learner_id, content, outcome, resistance}

> 各教育子文件另声明专有事件：upbringing_conflict（`01-family-upbringing.md`）；observer_learning、internalization_changed、social_exclusion_started / social_exclusion_ended（`03-community-discipline.md`）；role_effect_changed（`04-rituals-beliefs.md`）；transfer_method_effect、generational_break、generational_conflict、break_consequence（`06-generational-transfer.md`），本表只列通用教育事件。

## 6. 与其他系统的接口
- 读：
  - 03-relationships：家庭、师徒、邻里关系是教育通道。
  - 02-institutions：制度通过社区规训传递。
  - 08-rituals-beliefs：仪式传递信仰和禁忌。
  - 04-information：信息经验是教育的一部分。
  - 自然环境：`03-hydrology`、`05-soil-and-fields`、`08-hazards` 的环境事件是教材。
  - 07-conflicts：冲突作为规训和内化事件。
- 写：
  - 人物系统的价值观、技能、规范内化、世界观。
  - 06-stratification：教育是向上流动的主要通道。
  - 03-relationships：共同学习形成关系。
  - 02-institutions：教育传递制度，也可能产生代际断裂。
- 因果链：跟随父亲学犁田 → 技能提升 → 失败一次 → 经验学习 → 以后更谨慎 → 价值观形成。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 初始角色的价值观、技能、世界观
- 家庭教养的内容和传递规则
- 生计技能清单和学习曲线
- 社区规训的惩罚和内化规则
- 仪式清单和信仰影响
- 信息经验的来源和传递规则
- 代际传递的内容和断裂条件

## 8. 扩展预留
- 正式教育（私塾、学堂）：作为生计技能和识字教育的扩展。
- 外来教育（外来先生、新观念）：作为外部注入事件。
- 成人教育（婚后学习新技能）：作为技能学习的扩展。
- 教育制度（谁有资格受教育）：作为 06-stratification 的扩展。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。