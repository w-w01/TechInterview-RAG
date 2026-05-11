# 开发路线图（InterviewMate）

后端 **练习会话** 使用本地 **SQLite**（`POST /sessions`），单机演示可持久化；多副本部署时需替换为 Redis 等。

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

## 阶段 4（MVP 已部分落地）

- **评卷 `study_topics`**：与 `weak_topics` 配套，模型输出后续学习方向短句；前端展示；旧模型输出缺字段时服务端解析为空数组。
- **学习计划**：`POST /sessions/{id}/tutor/learning-plan`；请求 **`plan_days`**（几天内学完）；响应含 **`jd_priority_guess_markdown`**（基于 JD 推断对方更看重的考查重心，避免平铺技能列表）+ 逐日任务。
- **Tutor 对话**：`POST /sessions/{id}/tutor/chat`（JSON 一次返回）；`POST /sessions/{id}/tutor/chat/stream`（**SSE** 流式正文，学习页默认）；知识库开启时含 citations / 改写元数据。前端助手气泡 **Markdown 渲染**（react-markdown）。
- **前端**：顶栏 **答题 | 学习**；学习区为计划/对话与 **AI 小测**（复用 `generate-question-llm` + 评卷）；异步请求时有加载提示。
- **保留/后续**：资料外链推荐、进步曲线、与个人后台（本阶段**不开发**、入口隐藏）等可后续扩展。
- **文档**：多语言与流式细节见 [RAG_DESIGN.md](RAG_DESIGN.md)（「多语言与答复语言控制」「流式输出」）。

## 横切增强（已实现）

- 评卷 JSON 含 **`study_topics`**，与 Tutor、学习区展示联动。

## 阶段 5（LangChain 知识库 RAG：核心已落地，ETL/推荐阅读等可扩展）

目标：IT 面试“八股”**可追溯学习知识库**，与 JD 组卷用的 seed 向量索引分离；**不默认进入评卷 prompt**。

- **知识库 ETL（可扩展）**：成体系原始资料目录与批量入库脚本、更强 metadata 等仍属增强项；当前可通过 `POST /knowledge/documents` 写入规范化 JSON。
- **LangChain 分块与索引（已实现）**：`RecursiveCharacterTextSplitter` + OpenAI Embeddings + 本地 **FAISS**；启动构建，与 seed 索引分离。
- **知识库检索 API（已实现）**：`POST /knowledge/search`（调试召回）；摄入见 `POST /knowledge/documents`。
- **Tutor 引用式答疑（已实现）**：`/sessions/{id}/tutor/chat` 与 **`/tutor/chat/stream`** 在启用知识库时检索并注入上下文；响应 / `meta` 事件含 **citations**；前端可后续增加独立「参考来源」区块（当前以 API 字段为主）。
- **评卷后推荐阅读**：基于 `/evaluate-answer` 的 `study_topics` / `weak_topics` 检索相关文章，规划独立推荐接口（例如 `POST /sessions/{id}/knowledge/recommend`），把“评卷结果”接到“下一步阅读”。
- **学习计划资料绑定**：`/tutor/learning-plan` 在 JD 侧重点推断后检索高相关知识库片段，让每日任务附推荐阅读 / 复述任务 / 小测建议，减少纯 LLM 泛化计划。
- **知识点掌握图谱（后续）**：将 topic 白名单、题库 seed、知识库 chunks 与用户弱点关联，形成 topic -> 子知识点 -> 文章 -> 相关题目的学习路径。
- **多语言**：知识库 chunk 的 `lang` / `primary_lang` 与会话 `locale_mode`、检索过滤策略见 [RAG_DESIGN.md](RAG_DESIGN.md)。

边界原则：

- **JD RAG** 仍主要用于组卷：输入 JD，检索面试题 seed，进入 Planner / Selector。
- **Knowledge RAG** 用于学习：输入弱点、学习问题或 Tutor query，检索八股知识文章。
- **Grading** 仍锚定 canonical / generation snapshot；知识库只用于评卷后的讲解、推荐阅读或明确标记的“知识库生成题”。
