# InterviewMate RAG

轻量级 **RAG 技术面试练习** 本地演示：选题与难度、生成题目与期望要点、提交答案后获得 **0–10 分** 与结构化反馈（亮点、缺失、改进回答、评卷引用证据）。

## 技术栈

- **后端**：FastAPI、Pydantic、OpenAI API（Embedding + Chat）、FAISS、本地 JSON 种子。
- **前端**：Next.js（App Router）、React、TypeScript、Tailwind CSS、shadcn/ui。

## 仓库结构

```
backend/          FastAPI 应用与 data/interview_qa_seed.json
frontend/         Next.js 单页演示
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

> 注意：首次启动会对全部种子条目调用 Embedding 建索引，需要外网与有效 Key。

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

**评估答案**

```http
POST http://127.0.0.1:8000/evaluate-answer
Content-Type: application/json

{
  "question": "Java 中 interface 与 abstract class 的主要区别是什么？",
  "student_answer": "interface 只能有抽象方法……",
  "topic": "Java",
  "difficulty": "beginner"
}
```

## 文档

- [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) — 目标、范围、非目标、局限
- [docs/RAG_DESIGN.md](docs/RAG_DESIGN.md) — 数据加载、检索、评卷、引用与未来改进

## 截图

可在本地跑通前后端后自行截取单页流程，用于简历附件或 README 展示。
