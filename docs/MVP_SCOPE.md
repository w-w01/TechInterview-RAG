# MVP 范围说明（InterviewMate RAG）

## 项目目标

构建一个可在本地快速演示的 **题库 + LLM 评卷** 技术面试练习小工具，用于简历展示：选题与难度、生成题目、提交答案后对照本题参考要点获得结构化评分与反馈。

## MVP 功能

### 已实现

- 外置 topic 白名单 + **多标签 `topics`**，与难度组合后：**真题**从种子随机抽题（标签 OR）；**AI 题**在同过滤池内抽样至多 k 条作少样本，由 LLM 生成新题（池空为零样本）。
- **评卷不做向量检索**：真题用 `question_id` 锚定 canonical；AI 题用 `generation_id` 快照 + 抽样种子片段构造 prompt；调用大模型按 rubric 输出 **JSON**（分数、亮点、缺失、改进回答、薄弱点 **`weak_topics`**、建议学习方向 **`study_topics`**）。
- **练习会话**：`POST /sessions`；练习记录与薄弱点计数等写入本地 **SQLite**（`backend/data/session_store.sqlite3`），单机演示可持久化。**题库正文**仍以 **JSON 种子文件**为准，不设独立业务数据库。
- 单页前端：选题、**真题 / AI 生成**、展示题目、填写答案、评估结果展示；顶栏 **答题 | 学习**，学习区为 **AI Tutor**（学习计划含 JD 侧重点推断、对话）与 **AI 小测**。

### JD 向量组卷（已实现）

- 用户 **粘贴 JD 纯文本**；启动时对全库种子 **Embedding**；`POST /generate-paper-from-jd`：**向量检索候选** → **LLM Planner**（白名单 topic 优先级）→ **LLM Selector**（仅从候选 id 选题 + `ai_slots`）→ 程序校验与 AI 出题；整卷 **真题 + AI 穿插**。
- **评卷仍为 LLM rubric + 本题 canonical**，不把 JD 或检索邻居并入评卷 prompt。
- **`GET /sessions/{id}/next-paper-plan`**：`topic_priority` 优先来自**上一张卷** `meta`（与当次 JD Planner 一致仅当该卷为 JD 组卷）；否则为**题库 stub + 弱点**近似排序，响应内 **`topic_priority_source` / `topic_priority_explanation`** 标明来源，避免与实时 Planner 混淆。

### AI Tutor（已实现，MVP 级）

- 会话路径：`POST /sessions/{session_id}/tutor/learning-plan`（含 `plan_days`、JD 侧重点推断字段）、`POST /sessions/{session_id}/tutor/chat`（一次性 JSON）、`POST /sessions/{session_id}/tutor/chat/stream`（**SSE** 流式；学习页默认）。依赖 OpenAI Chat / Embedding，**不做**服务端请求限流（个人本地演示，见 README）。
- 学习页 Tutor **助手**消息以 **Markdown** 展示（`react-markdown` + GFM + 消毒）；用户消息仍为纯文本。
- **非目标**：个人后台、账号体系、资料爬虫与长期学习档案（见下节）。

### LangChain 知识库 RAG（学习向：核心已纳入 MVP）

- **已实现**：规范化文档摄入（`POST /knowledge/documents`）、启动时 FAISS 索引、**Tutor** 检索 + stuff 链（可选 `use_knowledge_rag`）、调试检索 `POST /knowledge/search`；与题库 seed 的 JD 组卷向量索引分离。
- **仍属增强 / 未做全**：成体系 ETL 流水线、学习计划内嵌阅读、**评卷后推荐阅读** 独立接口、薄弱点复测命题等（不替代现有题库 seed）。
- **评卷边界不变**：默认评卷仍只基于本题 canonical / AI generation snapshot；知识库检索结果不直接进入评分 prompt。
- **多语言与流式**：见 [RAG_DESIGN.md](RAG_DESIGN.md)「多语言与答复语言控制」「流式输出」。

## 非目标（刻意不做）

- 用户体系、鉴权、权限角色、管理后台。
- 支付、职位搜索、简历解析、大规模生产运维。
- 外部/云端业务数据库（题库为 JSON；会话状态仅为本地 SQLite 演示）。
- 当前 MVP 不包含知识库文章后台管理、在线编辑、资料质量审核工作流。

## 演示局限

- 需要可用的 **OpenAI API Key**（启动 **Embedding** + 评卷 / 出题 Chat），无离线降级。
- 题库规模小，评分仅供演示，不代表真实面试评分标准。
- JD 组卷为 **相对排序**（Top‑N），不设额外语义阈值时仍返回池中相对最相近的题目。
- CORS 仅放行本地前端常用端口，非生产安全配置。
- **无限流**：未实现按 IP/Key 的配额或节流；对外部署需自行加固。
