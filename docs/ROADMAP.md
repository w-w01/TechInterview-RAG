# 开发路线图（InterviewMate）

后端 **练习会话** 采用进程内存储（`POST /sessions`），单实例演示；多副本部署时需替换为 Redis 等。

## 阶段 1（已实现）

- **真题**：`POST /generate-question` — topic OR + 难度随机抽种子题；可选 `session_id` 记入会话。
- **AI 出题**：`POST /generate-question-llm` — 同过滤池内随机抽样至多 `reference_max` 条作少样本，LLM 生成新题；池空为零样本；返回 `generation_id` 与快照，评卷走 `generation_id` 分支。
- **评卷**：`POST /evaluate-answer` — `question_id` 与 `generation_id` **二选一**；LLM rubric 不变；AI 题参考片段来自出题时抽样种子。
- **前端**：出题前选择 **真题 / AI 生成**；页面加载时创建 `session_id` 并随出题请求携带。

## 阶段 2（已收口）

- **JD 纯文本组卷（已实现）**：启动 **Embedding** 全库种子；`POST /generate-paper-from-jd` 先做 **JD 向量检索候选**，再 **LLM Planner**（只输出白名单 `topic_priority`）→ **LLM Selector**（仅允许选择候选中的 `question_id`，并输出 `ai_slots`）→ 程序校验后 AI 出题与混卷；`meta` 含 `planner_notes`、`selector_notes`、`program_fixes` 等。
- **混卷（已实现）**：真题 + AI 穿插；AI 道数仍由「真题优先 + 短缺抬升」规则决定；Selector 在固定槽位内指定 AI 考查 `topics`/`difficulty`。
- **会话留档（已实现）**：SQLite 持久化；session 下显式 `paper` 实体 + `attempt` 明细，记录题目来源、分数与薄弱点；薄弱点用于后续补弱组卷。
- **重复控制（已实现）**：同一会话内已评估过题目默认不重复进入新卷；AI 题按题干规范化去重。
- **改进点（保留）**：当前“已答过”定义为 `score != null`（已评估）；可后续扩展为“已展开/已作答未评估”也计入已答集合。

## 阶段 3（规则版已实现）

- **与 JD 组卷联动**：`auto_adapt=true` 时检索跨三难度建候选；**最近 3 卷** 的 `topic_level_plan` 注入 **Selector** 提示词，供选题与 AI 槽位难度参考；`topic_priority` 以 **Planner** 为主（无合法输出时程序回退为频次+弱点排序）。
- **最近3卷 baseline**：会话层按 topic 聚合最近 3 卷的均分、题量、难度分布、高低分次数，用于后续解释性调节。
- **按 topic 自适应**：仅当“连续偏离”满足阈值（如连续高分/低分）才上调/下调该 topic 推荐难度，避免一次波动触发。
- **解释接口**：新增 `GET /sessions/{session_id}/next-paper-plan` 返回 `topic_priority`、baseline 与推荐难度及原因。

## 阶段 4（规划，仅文档）

- **AI tutor 学习计划**：基于 JD 考点优先级 + 会话薄弱点，生成阶段化补弱计划（周目标、题量、难度梯度）。
- **薄弱点问答辅导**：支持针对错题知识点进行追问、反问、纠偏讲解与例题再练。
- **学习资料推荐与复测闭环**：给出资料建议、复测节奏与进步追踪，形成“练-评-学-测”闭环。

## 横切增强（规划）

- 每次评卷除 **改进版回答** 外，增加结构化 **建议学习方向** 字段（如 `study_topics`），便于展示与后续组卷联动。
