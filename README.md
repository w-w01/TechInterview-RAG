# InterviewMate RAG

面向简历演示的**本地 RAG 面试练习 MVP**：FastAPI + Next.js，出题来自小规模结构化题库，评卷时用 **Embedding + FAISS** 检索参考条目，并用大模型输出 **0–10 分** 与结构化反馈（亮点、缺失、改进回答、引用证据）。

## 项目叙事（可写进简历）

- **端到端**：前后端分离单页流程；出题随机抽题（不按向量检索选题）；评卷时用 **`question_id` 锚定当前题**，避免「检索到的第一片段不一定是本题」的可解释性问题，再结合向量近邻扩充上下文。
- **工程拆分**：`schemas`（Pydantic）、`rag`（嵌入与 FAISS）、`prompts`（rubric + JSON 输出）、`main`（路由与校验）。
- **刻意不做**：账号体系、生产数据库、部署流水线（见 `docs/MVP_SCOPE.md`）。

## 数据与题库格式

- 默认使用仓库内 **`backend/data/interview_qa_seed.json`**（小规模 curated 条目；字段含 `id`、`topic`、`difficulty`、`question`、`answer`、`key_points`、`tags`、`source`）。
- 若使用 **Kaggle「Software Engineering Interview Questions」类数据集**（常见列为 `question_id`、`q`、`a`、`category`、`difficulty`）：**通常可直接用于本项目**，前提是：
  - **遵守该数据集在 Kaggle 上的 License**（商用与二次分发前务必自行核对条款）。
  - **映射到你的 schema**：例如 `question_id`→`id`，`q`→`question`，`a`→`answer`；`category`→本项目的 `topic`（需对齐枚举：`Java` / `SQL` / `REST API` / `System Design` / `AI / RAG Basics`）；`difficulty`→`beginner` / `intermediate` / `advanced`（若原始标签不同则建一层映射表）。
  - **`key_points`**：若源数据没有该列，可先置空数组 `[]`，或后续用脚本从 `answer` 抽取要点。
- 替换种子文件后重启后端即可重建向量索引（无需改代码，只要 JSON 数组形状一致）。

## 技术栈

- **后端**：FastAPI、Pydantic、OpenAI API（Embedding + Chat）、FAISS、本地 JSON 题库。
- **前端**：Next.js（App Router）、React、TypeScript、Tailwind CSS、shadcn/ui。

## 仓库结构

```
backend/          FastAPI、data/interview_qa_seed.json
frontend/         Next.js 单页
docs/             MVP 范围与 RAG 设计说明
```

## 环境准备

1. **Python 3.11+**（建议）
2. **Node.js 20+** 与 npm
3. **OpenAI API Key**（必填：启动建索引与评卷均会调用 API）

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

健康检查：<http://127.0.0.1:8000/health>

> 注意：首次启动会对全部题库条目调用 Embedding 建 FAISS 索引，需要外网与有效 Key。

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

**生成题目**

```http
POST http://127.0.0.1:8000/generate-question
Content-Type: application/json

{"topic": "Java", "difficulty": "beginner"}
```

响应中的 **`question_id`** 须在评卷时原样带回。

**评估答案**

```http
POST http://127.0.0.1:8000/evaluate-answer
Content-Type: application/json

{
  "question_id": "java_001",
  "question": "Java 中 interface 与 abstract class 的主要区别是什么？",
  "student_answer": "interface 只能有抽象方法……",
  "topic": "Java",
  "difficulty": "beginner"
}
```

## 文档

- [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) — 目标、范围、非目标、局限
- [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md) — 数据加载、检索、`question_id` 锚定、评卷与引用

## 截图

可在本地跑通前后端后自行截取单页流程，用于简历附件或 README 展示。
