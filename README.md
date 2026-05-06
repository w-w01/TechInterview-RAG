# InterviewMate RAG

面向简历演示的**本地题库面试练习 MVP**：FastAPI + Next.js，出题支持 **真题（种子随机）** 与 **AI 生成题（结构化池少样本）**；评卷均为 **LLM rubric**。真题评卷锚定 **`question_id`**；AI 题锚定 **`generation_id`** 快照 + 抽样种子参考片段。**练习会话**：`POST /sessions`，出题可带 `session_id`；会话与试卷记录存本地 **SQLite**（题库仍为 JSON 种子）。

**当前已实现**：`/generate-question`、`/generate-question-llm`、`/generate-paper-from-jd`（JD **向量检索候选** + **LLM Planner** 白名单 topic 优先级 + **LLM Selector** 仅从候选 id 选题并规划 AI 槽位）、`/evaluate-answer`（含 **`study_topics`** 建议学习方向）、`/sessions`、**AI Tutor**：`POST /sessions/{id}/tutor/learning-plan`（含 **`plan_days`** 与 JD **侧重点推断** `jd_priority_guess_markdown`）、`/tutor/chat`。**启动时**对全库种子调用 `text-embedding-3-small` 建索引（需外网与 Key）。**评卷**仍为 **本题 canonical / AI 快照**，不把 JD 全文或检索邻居写入评卷 prompt。

**限流**：本仓库为**个人本地演示**，服务端**不实现** API 限流；若对外暴露请自行在网关或托管平台配置。

**路线图**：[docs/ROADMAP.md](docs/ROADMAP.md)（阶段 3 规则自适应与阶段 4 AI tutor 规划）。

## 项目叙事（可写进简历）

- **端到端**：前后端分离单页流程；真题 / AI 题 / **JD 向量组卷**；评卷为 LLM rubric，**不**把向量邻居并入评卷。
- **选题**：topic 随机；结构化池 + LLM 新题；**JD** 为向量候选 + **双阶段 LLM**（规划 topic、从候选选题并定 AI 方向）。
- **工程拆分**：`embedding_index`、`rag`、`prompts`、`session_store` / `generation_store`、`main`。
- **刻意不做**：账号体系、生产数据库、部署流水线（见 `docs/MVP_SCOPE.md`）。

## 数据与题库格式

- **权威说明**见 [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md)。
- 题库 **`backend/data/interview_qa_seed.json`**（约 200 条）与白名单 **`topic_allowlist.json`** 由脚本从 **`backend/data/kaggle-Software_Engineering_Interview_Questions_Dataset.json`** 生成；遵守该数据集在 Kaggle 上的 License。
- 重新生成：

```powershell
cd backend
python scripts\etl_kaggle_to_seed.py
```

- 前端通过 **`GET /topics`** 拉取可选标签；出题请求为 **`topics` 数组（OR：与题目标签有交集即入池）**。

## 技术栈

- **后端**：FastAPI、Pydantic、OpenAI API（Chat：出题 + 评卷；**Embedding**：启动建索引 + JD 查询）、numpy、本地 JSON 题库。
- **前端**：Next.js（App Router）、React、TypeScript、Tailwind CSS、shadcn/ui。

## 仓库结构

```
backend/          FastAPI、data/（种子与白名单、Kaggle 源 JSON）、scripts/etl_kaggle_to_seed.py
frontend/         Next.js 单页
docs/             ROADMAP、MVP、题库与评卷设计、DATA_SCHEMA
```

## 环境准备

1. **Python 3.11+**（建议）
2. **Node.js 20+** 与 npm
3. **OpenAI API Key**（必填：启动 **Embedding**、**出题**与**评卷** Chat）

## 后端：安装与运行

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 健康检查：<http://127.0.0.1:8000/health>（`rag_index_ready`：题库非空；`embedding_index_ready`：种子向量索引已构建。）
- Topic 列表：<http://127.0.0.1:8000/topics>
- 新建练习会话：`POST /sessions`
- JD 混卷策略可通过 `backend/.env` 调参（见 `.env.example` 中 `JD_*` 变量，默认“真题优先”）。

## 前端：安装与运行

```powershell
cd frontend
copy .env.example .env.local
# 若后端不是 127.0.0.1:8000，可修改 NEXT_PUBLIC_API_URL
npm install
npm run dev
```

浏览器打开：<http://localhost:3000>

## 示例 API

**创建会话（可选，用于记录出题历史）**

```http
POST http://127.0.0.1:8000/sessions
```

**生成题目 — 真题（topic 随机池）**

```http
POST http://127.0.0.1:8000/generate-question
Content-Type: application/json

{"topics": ["data_structures"], "difficulty": "beginner", "session_id": "可选"}
```

多选示例：`{"topics": ["devops", "system_design"], "difficulty": "intermediate"}`。合法 slug 以 **`GET /topics`** 为准。

响应含 **`question_id`**；评卷时 **仅带 `question_id`**（勿带 `generation_id`）。

**生成题目 — AI（结构化池少样本 / 池空则零样本）**

```http
POST http://127.0.0.1:8000/generate-question-llm
Content-Type: application/json

{
  "topics": ["data_structures"],
  "difficulty": "beginner",
  "reference_max": 5,
  "session_id": "可选"
}
```

响应含 **`generation_id`**、`reference_snippets`、`source_seed_ids`；评卷时 **仅带 `generation_id`**（勿带 `question_id`）。

**根据 JD 组卷（已实现）**

```http
POST http://127.0.0.1:8000/generate-paper-from-jd
Content-Type: application/json

{
  "jd_text": "粘贴的职位描述纯文本（API 校验最短约 40 字符）……",
  "difficulty": "intermediate",
  "count": 5
}
```

- **输入**：`jd_text` 过长时服务端截断（约 12k 字符）；`count` 为 1–20。
- **输出**：`questions` 与 **`/generate-question`** 同形；选题评卷时 **`topics` 须传该题自带的标签**（与真题一致）。
- **难度**：仅在对应难度子集中做 **余弦相似度** Top‑K（按 `id` 去重）。

**评估答案（真题：仅 `question_id`）**

```http
POST http://127.0.0.1:8000/evaluate-answer
Content-Type: application/json

{
  "question_id": "q_11",
  "question": "What is the difference between an array and a linked list?",
  "student_answer": "Array is fixed size, linked list uses nodes...",
  "topics": ["data_structures"],
  "difficulty": "beginner"
}
```

**评估答案（AI 题：仅 `generation_id`，题干须与出题响应一致）**

```json
{
  "generation_id": "uuid-from-generate-question-llm",
  "question": "（与快照一致）",
  "student_answer": "...",
  "topics": ["data_structures"],
  "difficulty": "beginner"
}
```

真题：响应中的 **`reference_evidence`** 为 **单条** canonical。AI 题：可为 **多条** 抽样种子片段。**JD 组卷已实现**，评卷仍按单题 canonical / AI 快照逻辑，不并入向量邻居。评卷 JSON 另含 **`study_topics`**（字符串数组），用于前端展示与「学习」页 Tutor 衔接。

**AI Tutor（需有效 `session_id`）**

学习计划（`jd_text` 不少于约 40 字；`weak_topic` 可空；**`plan_days`** 为 1–14，表示希望几天内完成；响应含 **`jd_priority_guess_markdown`**，为基于 JD 的考查侧重点推断，**非**简单罗列技术栈）：

```http
POST http://127.0.0.1:8000/sessions/{session_id}/tutor/learning-plan
Content-Type: application/json

{"jd_text": "……", "weak_topic": "", "plan_days": 5}
```

对话（`history` 为不含本轮的既往 `user`/`assistant` 消息；`jd_text` 可空）：

```http
POST http://127.0.0.1:8000/sessions/{session_id}/tutor/chat
Content-Type: application/json

{"jd_text": "", "weak_topic": "", "history": [], "user_message": "什么是 CAS？"}
```

前端首页顶栏可切换 **答题** / **学习**（学习计划可选天数）；**个人后台**不在本 MVP 中展示或开发。

## 文档

- [docs/ROADMAP.md](docs/ROADMAP.md) — 分阶段目标（JD 组卷、自适应等）
- [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) — 目标、范围、非目标、局限
- [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md) — 数据加载、选题与评卷、JD RAG 组卷（已实现）
- [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) — 题库 JSON 字段与白名单

## 截图

可在本地跑通前后端后自行截取单页流程，用于简历附件或 README 展示。
