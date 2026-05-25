# InterviewMate RAG

面向简历演示的**本地题库面试练习 MVP**：FastAPI + Next.js，出题支持 **真题（种子随机）** 与 **AI 生成题（结构化池少样本）**；评卷均为 **LLM rubric**。真题评卷锚定 **`question_id`**；AI 题锚定 **`generation_id`** 快照 + 抽样种子参考片段。**练习会话**：`POST /sessions`，出题可带 `session_id`；会话与试卷记录存本地 **SQLite**（题库仍为 JSON 种子）。

**当前已实现**：`/generate-question`、`/generate-question-llm`、`/generate-paper-from-jd`（JD **Hybrid 检索（向量+BM25）+ BGE Rerank 候选** + **LLM Planner** + **LLM Selector**）、`/evaluate-answer`（含 **`study_topics`**）、`/sessions`、**AI Tutor**（学习计划、`tutor/chat`、`tutor/chat/stream` SSE）。知识库路径：**query 改写** → **Hybrid + Rerank** → **LangChain FAISS + stuff 链**（`backend/data/knowledge/documents`）。两路检索共用 [`backend/app/retrieval_fusion.py`](backend/app/retrieval_fusion.py)。**启动时**对种子与知识库分别建索引（OpenAI Embedding；知识库 FAISS 可落盘）。**评卷**仍锚定 **本题 canonical / AI 快照**，不把检索片段写入评卷 prompt。检索栈细节见 [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md)「检索栈 v2」。

**限流**：本仓库为**个人本地演示**，服务端**不实现** API 限流；若对外暴露请自行在网关或托管平台配置。

**路线图**：[docs/ROADMAP.md](docs/ROADMAP.md)（含阶段 5 知识库 RAG 与**检索栈 v2**）。

## 项目叙事（可写进简历）

- **端到端**：前后端分离单页流程；真题 / AI 题 / **JD Hybrid 组卷**；评卷为 LLM rubric，**不**把检索邻居并入评卷。
- **选题**：topic 随机；结构化池 + LLM 新题；**JD** 为 Hybrid+Rerank 候选 + **双阶段 LLM**（规划 topic、从候选选题并定 AI 方向）。
- **工程拆分**：`retrieval_fusion`、`embedding_index`、`knowledge_rag`、`rag`、`prompts`、`session_store` / `generation_store`、`main`。
- **已落地 / 可扩展**：统一知识库（摄入 `POST /knowledge/documents`、调试 `POST /knowledge/search`、Tutor 引用式检索）与 **Tutor SSE**；**仍可扩展**：成体系 ETL、学习计划内嵌阅读材料、评卷后推荐阅读接口等。评卷主链路仍锚定 canonical / 快照，知识库不进入评卷 prompt。
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

- **后端**：FastAPI、Pydantic、OpenAI API（Chat / Embedding）、numpy、LangChain、FAISS、**rank-bm25**、**sentence-transformers**（本地 BGE Reranker）、本地 JSON 题库。
- **前端**：Next.js（App Router）、React、TypeScript、Tailwind CSS、shadcn/ui；学习页 Tutor 助手气泡使用 **react-markdown**（GFM + `rehype-sanitize`）渲染 Markdown。

## 仓库结构

```
backend/          FastAPI、data/、scripts/（ETL、Doc2Query、健康度、检索评测）
frontend/         Next.js 单页
docs/             ROADMAP、MVP、RAG_DESIGN、DATA_SCHEMA
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

**本地知识摄入 API（供 n8n Cloud 等联调）**

1. 按上文安装依赖并启动 FastAPI（默认监听 `127.0.0.1:8000`）。
2. 浏览器打开交互文档：<http://127.0.0.1:8000/docs>，可调试 `POST /knowledge/documents` 与 `GET /knowledge/documents/{corpus_id}/{doc_id}`。
3. 将本机服务暴露给公网（开发期）：安装 [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) 后执行：

```powershell
cloudflared tunnel --url http://localhost:8000
```

终端会打印形如 `https://xxxx.trycloudflare.com` 的 HTTPS 地址；后端已配置 CORS，允许 `https://*.trycloudflare.com`（正则匹配 Quick Tunnel 子域）、`http://localhost:5678`（n8n 默认本地 UI），以及原前端地址。若 n8n 或其它工具的 `Origin` 仍被拒绝，可在 `backend/.env` 中设置 `APP_ENV=development` 或 `DEV_CORS_ALLOW_ALL=true`（此时允许任意 Origin，详见 `.env.example`）。

4. 在 n8n 中将 **HTTP Request** 等节点的 base URL 设为上述 `https://xxxx.trycloudflare.com`（即 `api_base_url`），路径例如 `POST /knowledge/documents`。文档写入目录：`backend/data/knowledge/documents/{corpus_id}/{doc_id}.json`；默认同路径已存在时返回 **409**，需加查询参数 `overwrite=true` 才覆盖。`corpus_id` 即子目录名，用于按知识库筛选；仓库 **Backend-Engineers-Guide** 的已摄入文档在 **`backend_engineers_guide`**，其它知识库请使用新的 `corpus_id`（同一 API 与目录规则）。

5. **知识库向量索引（FAISS）持久化**：首次或语料变更后会嵌入并写入 `backend/data/knowledge/faiss_index/`（`index.faiss`、`index.pkl`、`manifest.json`）。`manifest` 与语料指纹、嵌入模型、分块参数、`retrieval_stack_version` 等一致时**启动直接加载**。语料变更、Doc2Query 更新或 `MANIFEST_VERSION` 变更后需重建：设 `KNOWLEDGE_FAISS_REBUILD=true` 后重启。Hybrid / Rerank 开关见 `.env.example`（`HYBRID_ENABLED`、`RERANK_MODEL` 等）。

6. **检索调优（可选离线脚本）**（在 `backend` 目录、已配置 `.env` 后）：

```powershell
# 为知识库 JSON 生成 synthetic_queries（会写回源文件，随后需重建 FAISS）
python scripts\generate_doc2query.py
# 知识库体检：重复 / topic 覆盖 / 一致性报告（只读，不改语料）
python scripts\knowledge_health_check.py
# 检索回归：对比 vector / hybrid / hybrid+rerank（需先补全 data/eval/*.jsonl 中的 expected_*）
python scripts\eval_retrieval.py --suite all
```

- 健康检查：<http://127.0.0.1:8000/health>（`rag_index_ready`、`embedding_index_ready`、`knowledge_rag_*`、`hybrid_enabled`、`seed_bm25_ready`、`knowledge_bm25_ready`、`rerank_ready` 等。）
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

浏览器打开：<http://localhost:3000>（默认跳转 `/zh`；英文 UI 为 `/en`）。

**InterviewMate 前端路由（双语，浅色品牌 UI）**

| 路径 | 说明 |
|------|------|
| `/zh` 或 `/en` | Landing 首页 |
| `/[locale]/session` | 模拟面试：卡片 Deck、仅前进、后台并行评卷、总结礼花 |
| `/[locale]/learn` | 学习计划 + Tutor（SSE 透传 `locale_mode`） |
| `/[locale]/session?demo=1` | 预填演示 JD |

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
- **检索**：默认 **Hybrid（向量+BM25，α≈0.4）初筛** → **BGE Rerank** → Planner/Selector；`auto_adapt=true` 时跨三难度合并去重。开发态可返回 `meta.jd_retrieval_debug`（见 `JD_DEBUG_RETRIEVAL`）。

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

{
  "jd_text": "",
  "weak_topic": "",
  "locale_mode": "auto",
  "use_knowledge_rag": true,
  "top_k": 6,
  "corpus_id": "",
  "history": [],
  "user_message": "什么是 CAS？"
}
```

说明：
- `locale_mode`：`auto / zh / en / mixed`，默认 `auto`。
- `corpus_id`：可选，限定子库（如 `advanced_java`）；空字符串表示全库检索。
- 分块嵌入文本含 `Title`、正文及可选 **`synthetic_queries`（Doc2Query）**；**不按 `topic_slugs` 过滤**。
- 检索为 **Hybrid + Rerank**（与 JD 组卷共用 `retrieval_fusion`）；单次检索，不做失败后二次跨语言重搜。
- 响应含 `query_type`、`rewritten_query`、`retrieval_queries`、`citations` 等；SSE `retrieval_hits` 含 `score` / `fusion_score` / `rerank_score`（分数越大越相关）。

**Tutor 对话 — SSE 流式（与 `tutor/chat` 请求体相同，学习页默认使用）**

```http
POST http://127.0.0.1:8000/sessions/{session_id}/tutor/chat/stream
Content-Type: application/json
```

响应：`text/event-stream`，每帧为 `data: <JSON>\n\n`，`JSON.type` 取值：`meta`（**仅 RAG 路径**：`citations`、改写字段、**`retrieval_hits`**（含 `score` / `fusion_score` / `rerank_score`、`retrieval_query` 等））、`delta`、`done`、`error`。学习页可展开「本轮检索详情」。

知识库检索调试：

```http
POST http://127.0.0.1:8000/knowledge/search
Content-Type: application/json

{"query": "redis 主从复制断点续传机制", "top_k": 6, "corpus_id": "advanced_java"}
```

前端首页顶栏可切换 **答题** / **学习**（学习计划可选天数）；**个人后台**不在本 MVP 中展示或开发。

## 文档

- [docs/ROADMAP.md](docs/ROADMAP.md) — 分阶段目标（JD 组卷、自适应等）
- [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) — 目标、范围、非目标、局限
- [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md) — 题库与评卷、**检索栈 v2（Hybrid+Rerank）**、知识库 Tutor、SSE、多语言；P2 延后项见文内
- [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) — 题库 JSON 字段与白名单

## 截图

可在本地跑通前后端后自行截取单页流程，用于简历附件或 README 展示。
