# 传说与山神故事

## 1. 目的
定义山神传说、祖辈故事、禁忌由来等传说性信息的产生、传播、可信度变化，以及传说如何塑造世界观和行为规范。

## 2. 核心概念
- **传说**：关于山神、祖先、神树、禁忌由来的故事，通常没有可验证的事实基础。
- **传说类型**：山神显灵、祖先创业、神树禁忌、灾害由来、外人故事。
- **可信度**：传说可信度不靠验证，靠代际传递、仪式强化、舆论共识。
- **行为规范**：传说支撑禁忌和制度（如“砍神树会遭报应”）。
- **传说变形**：代际传递中变形，越传越神。
- **传说与心理**：传说影响人物心理（敬畏、恐惧、安慰）。
- **传说与自然环境**：山神传说往往与特定地点（山神庙、神树、深山）绑定。

## 3. 传说字段
| 字段 | 类型 | 说明 |
|---|---|---|
| legend_id | string | 唯一 ID |
| legend_type | enum | 山神/祖先/神树/灾害/外人 |
| content | string | 故事内容 |
| associated_place | string? | 绑定的地点（山神庙/神树/深山） |
| associated_taboo | string? | 绑定的禁忌 |
| belief_strength | float 0–1 | 社区信仰强度 |
| distortion_level | float 0–1 | 代际变形程度 |

## 4. 演化规则

### 4.1 传说形成
```
条件：重大事件（山神“显灵”、祖先创业、灾害）被故事化
效果：生成传说条目
      设置 content、associated_place、associated_taboo
      生成 information_created 事件（info_type = 传说）
滞后：事件后经过讲述和传播
影响范围：社区
```

### 4.2 传说传播
```
条件：长辈讲述、仪式传述、节庆重演
效果：传说沿代际和关系网络传播
      传播中变形，distortion_level 上升
      belief_strength 受仪式和舆论强化
      生成 information_spread 事件
滞后：代际传递
影响范围：社区
```

### 4.3 传说变形
```
条件：代际传递、多次讲述
效果：content 变形，越传越神
      distortion_level 上升
      生成 information_distorted 事件
滞后：长期过程
影响范围：传说
```

### 4.4 传说强化信仰
```
条件：仪式、节庆、灾害后讲述
效果：belief_strength 上升
      支撑禁忌和制度
      生成 belief_strength_changed 事件
滞后：按仪式和事件
影响范围：社区
```

### 4.5 传说弱化
```
条件：长期无仪式、外来观念冲击、禁忌被反复违反无人受罚
效果：belief_strength 下降
      禁忌和制度松动
      生成 belief_strength_changed 事件
滞后：长期过程
影响范围：社区
```

### 4.6 传说影响行为
```
条件：角色相信传说
效果：影响心理（敬畏、恐惧、安慰）
      影响行为（遵守禁忌、祭拜、回避某些地点）
      生成 legend_influenced_behavior 事件
滞后：按行为时机
影响范围：角色
```

## 5. 事件类型
- `information_created`：{info_id, info_type: 传说, content, associated_place, associated_taboo}
- `information_spread`：{info_id, from_agent, to_agent, tick, distortion}
- `information_distorted`：{info_id, old_content, new_content, distortion_level}
- `belief_strength_changed`：{info_id, old, new, cause}
- `legend_influenced_behavior`：{agent_id, legend_id, behavior}

## 6. 与其他系统的接口
- 读：08-rituals-beliefs 的仪式和节庆；06-vegetation 的神树和禁伐区；02-institutions 的禁忌。
- 写：02-institutions 的禁忌支撑；08-rituals-beliefs 的仪式内容；人物系统的心理状态（敬畏、恐惧）；05-education 的代际传递。
- 因果链：山洪灾害 → 山神发怒传说 → 祭祀强化 → 禁忌遵守 → 植被保护 → 灾害减少（或传说继续）。

## 7. 地点参数占位
- 初始传说清单
- 传说与地点、禁忌的绑定
- belief_strength 的初始值和变化规则
- 变形概率
- 传说影响行为的规则