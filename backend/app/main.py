"""InterviewMate RAG FastAPI 入口：健康检查、出题、评卷。"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from .data_loader import load_interview_seed
from .prompts import EVALUATION_SYSTEM_PROMPT, build_evaluation_user_prompt
from .rag import RAGService
from .schemas import (
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
    GenerateQuestionRequest,
    GenerateQuestionResponse,
    HealthResponse,
    ReferenceSnippet,
)

# 从 backend/.env 加载环境变量
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_TOPICS = {"Java", "SQL", "REST API", "System Design", "AI / RAG Basics"}
ALLOWED_DIFFICULTY = {"beginner", "intermediate", "advanced"}

rag = RAGService()
_openai_client: AsyncOpenAI | None = None
_seed_items: List[Dict[str, Any]] = []


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI()
    return _openai_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _seed_items
    _seed_items = load_interview_seed()
    rag.load_items(_seed_items)
    await rag.build_index()
    yield


app = FastAPI(title="InterviewMate RAG", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _snippet_from_item(it: Dict[str, Any]) -> ReferenceSnippet:
    body = f"Q: {it.get('question', '')}\n\nReference: {it.get('answer', '')}"
    src = str(it.get("source") or "manually curated seed data")
    return ReferenceSnippet(source=src, content=body[:4000])


def _item_by_id(question_id: str) -> Optional[Dict[str, Any]]:
    """按种子 id 查找条目。"""
    for it in _seed_items:
        if str(it.get("id", "")) == str(question_id):
            return it
    return None


def _extend_key_points_union(target: List[str], item: Dict[str, Any]) -> None:
    kp = item.get("key_points") or []
    if isinstance(kp, list):
        target.extend(str(x) for x in kp)
    elif kp:
        target.append(str(kp))


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        rag_index_ready=rag.ready,
        seed_items=len(_seed_items),
        message="InterviewMate RAG backend",
    )


@app.post("/generate-question", response_model=GenerateQuestionResponse)
async def generate_question(body: GenerateQuestionRequest) -> GenerateQuestionResponse:
    if body.topic not in ALLOWED_TOPICS:
        raise HTTPException(
            status_code=400,
            detail=f"topic 必须是以下之一: {', '.join(sorted(ALLOWED_TOPICS))}",
        )
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )
    picked = rag.pick_question(body.topic, body.difficulty)
    if picked is None:
        raise HTTPException(
            status_code=404,
            detail="该主题与难度组合下暂无题库条目，请更换条件。",
        )
    kps = picked.get("key_points") or []
    if not isinstance(kps, list):
        kps = [str(kps)]
    kps = [str(x) for x in kps]

    # 出题阶段仅随机抽题，不做向量检索；参考片段字段保持空列表以兼容 API 形态
    return GenerateQuestionResponse(
        question_id=str(picked.get("id", "")),
        question=str(picked.get("question", "")),
        topic=body.topic,
        difficulty=body.difficulty,
        expected_key_points=kps,
        reference_snippets=[],
    )


def _parse_eval_json(content: str) -> Dict[str, Any]:
    return json.loads(content)


@app.post("/evaluate-answer", response_model=EvaluateAnswerResponse)
async def evaluate_answer(body: EvaluateAnswerRequest) -> EvaluateAnswerResponse:
    if body.topic not in ALLOWED_TOPICS:
        raise HTTPException(
            status_code=400,
            detail=f"topic 必须是以下之一: {', '.join(sorted(ALLOWED_TOPICS))}",
        )
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )

    canonical = _item_by_id(body.question_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="未知的 question_id，不在当前题库中。")
    if str(canonical.get("topic", "")).strip() != body.topic.strip():
        raise HTTPException(status_code=400, detail="question_id 与 topic 不一致。")
    if str(canonical.get("difficulty", "")).strip() != body.difficulty.strip():
        raise HTTPException(status_code=400, detail="question_id 与 difficulty 不一致。")
    if str(canonical.get("question", "")).strip() != body.question.strip():
        raise HTTPException(status_code=400, detail="question 与题库中该 id 对应题干不一致。")

    query_text = f"{body.question}\n\n考生作答:\n{body.student_answer}"
    retrieved = await rag.retrieve(query_text=query_text, topic=body.topic, top_k=8)

    # 当前题优先；其余为向量近邻，最多共 5 条用于展示与拼 prompt
    ordered: List[Dict[str, Any]] = [canonical]
    seen = {str(canonical.get("id", ""))}
    for it in retrieved:
        iid = str(it.get("id", ""))
        if iid in seen:
            continue
        seen.add(iid)
        ordered.append(it)
        if len(ordered) >= 5:
            break

    ref_lines = [_snippet_from_item(it).content for it in ordered]
    key_points_union: List[str] = []
    for it in ordered:
        _extend_key_points_union(key_points_union, it)
    evidence = [_snippet_from_item(it) for it in ordered]

    reference_block = "\n\n---\n\n".join(ref_lines)
    key_points_block = "\n".join(f"- {p}" for p in key_points_union[:30])

    user_prompt = build_evaluation_user_prompt(
        topic=body.topic,
        difficulty=body.difficulty,
        question=body.question,
        student_answer=body.student_answer,
        reference_block=reference_block,
        key_points_block=key_points_block or "(无单独要点，请从参考材料提炼)",
    )

    model = "gpt-4o-mini"
    completion = await _get_openai().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        data = _parse_eval_json(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"模型返回非合法 JSON: {e}") from e

    try:
        score = int(data["score"])
        strengths = list(data["strengths"])
        missing = list(data["missing_points"])
        improved = str(data["improved_answer"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"模型 JSON 字段不完整: {e}") from e

    if score < 0 or score > 10:
        raise HTTPException(status_code=502, detail="score 必须在 0-10")

    return EvaluateAnswerResponse(
        score=score,
        strengths=[str(x) for x in strengths],
        missing_points=[str(x) for x in missing],
        improved_answer=improved,
        reference_evidence=evidence,
    )
