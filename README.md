# InterviewMate RAG

面向简历演示的**本地题库面试练习 MVP**：FastAPI + Next.js，出题来自小规模结构化 JSON 题库；评卷时仅用 **`question_id` 锚定的本题** 参考答案与要点写入 prompt，由大模型按 **LLM rubric** 输出 **0–10 分** 与结构化反馈（亮点、缺失、改进回答、本题引用证据）。

**当前已实现**：按标签 OR + 难度 **纯随机** 抽题（`/generate-question`）；**评卷不做向量检索**，不向评卷 prompt 合并邻居条目。

**规划中的 JD MVP**（文档已与方案对齐，**代码落地前接口不可用**）：用户 **粘贴 JD 纯文本**，后端对题库条目做 **Embedding**，用 JD 向量在指定难度子集中 **相似度排序组卷**（`POST /generate-paper-from-jd`）；**评卷仍仅为本题 + LLM rubric**，不把 JD 或检索邻居写入评卷。详见 [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md)。

## 项目叙事（可写进简历）

- **端到端**：前后端分离单页流程；**评卷路径**不调用向量检索，上下文 **仅本题**，可解释性固定。
- **选题**：已实现 topic 随机池；规划 JD-conditioned **检索组卷**（与随机池并存）。
- **工程拆分**：`schemas`（Pydantic）、`rag`（题库与选题）、`prompts`（rubric + JSON 输出）、`main`（路由与校验）；JD 组卷实现后将增加题库向量索引构建与 JD 查询嵌入（仍在后端内聚）。
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

- **后端**：FastAPI、Pydantic、OpenAI API（Chat Completions 用于评卷；**规划**中对种子批量 Embedding 用于 JD 组卷）、本地 JSON 题库。
- **前端**：Next.js（App Router）、React、TypeScript、Tailwind CSS、shadcn/ui。

## 仓库结构

```
backend/          FastAPI、data/（种子与白名单、Kaggle 源 JSON）、scripts/etl_kaggle_to_seed.py
frontend/         Next.js 单页
docs/             MVP、题库与评卷设计、DATA_SCHEMA
```

## 环境准备

1. **Python 3.11+**（建议）
2. **Node.js 20+** 与 npm
3. **OpenAI API Key**（必填：**评卷** Chat；**JD 组卷功能实现后**还将在启动时对全库条目调用 Embedding）

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

- 健康检查：<http://127.0.0.1:8000/health>（`rag_index_ready`：题库已加载且非空。**规划**中增加 `embedding_index_ready`：JD 组卷用向量索引是否已构建。）
- Topic 列表：<http://127.0.0.1:8000/topics>

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

**生成题目（已实现：topic 随机池）**

```http
POST http://127.0.0.1:8000/generate-question
Content-Type: application/json

{"topics": ["data_structures"], "difficulty": "beginner"}
```

多选示例：`{"topics": ["devops", "system_design"], "difficulty": "intermediate"}`（池内为「标签任一为 devops 或 system_design」且难度匹配的题）。合法 slug 以 **`GET /topics`** 为准。

响应含 **`question_id`**、`topics`（本题全部标签）；评卷时带回 **`question_id`**，且 **`topics` 须与本题标签有交集**（一般用出题时的筛选标签）。

**根据 JD 组卷（规划中，尚未实现）**

```http
POST http://127.0.0.1:8000/generate-paper-from-jd
Content-Type: application/json

{
  "jd_text": "粘贴的职位描述纯文本……",
  "difficulty": "intermediate",
  "count": 5
}
```

- **输入**：`jd_text` 为用户粘贴的 JD；服务端将校验长度并对过长文本截断（具体上限以实现为准）。
- **输出**：`questions` 数组，元素字段与 **`/generate-question` 单次响应** 对齐，便于前端选题后沿用 **`/evaluate-answer`**。
- **难度**：与现有 `beginner` / `intermediate` / `advanced` 一致；仅在对应难度的种子子集中做向量相似度排序并取 Top‑N（去重）。

**评估答案**

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

响应中的 **`reference_evidence`** 仅为 **本题** 对应片段（无近邻扩充）；**JD 组卷不改变评卷逻辑**。

## 文档

- [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) — 目标、范围、非目标、局限
- [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md) — 数据加载、随机选题、JD RAG 组卷（规划）、`question_id` 锚定评卷与引用
- [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) — 题库 JSON 字段与白名单

## 截图

可在本地跑通前后端后自行截取单页流程，用于简历附件或 README 展示。
