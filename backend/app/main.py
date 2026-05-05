"""InterviewMate FastAPI 入口：健康检查、随机出题、本题锚定评卷。"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from .data_loader import load_interview_seed
from .prompts import EVALUATION_SYSTEM_PROMPT, build_evaluation_user_prompt
from .rag import RAGService, _item_topic_slugs
from .schemas import (
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
    GenerateQuestionRequest,
    GenerateQuestionResponse,
    HealthResponse,
    ReferenceSnippet,
    TopicEntry,
    TopicsListResponse,
)
from .topic_config import load_topic_allowlist, validate_seed_against_allowlist

# 从 backend/.env 加载环境变量
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_DIFFICULTY = {"beginner", "intermediate", "advanced"}

_topic_entries: List[Dict[str, str]] = load_topic_allowlist()
ALLOWED_SLUGS: Set[str] = {e["slug"] for e in _topic_entries}

rag = RAGService()
_openai_client: Optional[AsyncOpenAI] = None
_seed_items: List[Dict[str, Any]] = []


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI()
    return _openai_client


def _normalize_request_topics(raw: List[str]) -> List[str]:
    """去重、校验白名单、保持用户顺序。"""
    out: List[str] = []
    for t in raw:
        s = str(t).strip().lower()
        if s not in ALLOWED_SLUGS:
            raise HTTPException(
                status_code=400,
                detail=f"未知 topic slug: {s}。合法值见 GET /topics。",
            )
        if s not in out:
            out.append(s)
    if not out:
        raise HTTPException(status_code=400, detail="topics 不能为空")
    return out


def _topics_sorted_from_item(item: Dict[str, Any]) -> List[str]:
    return sorted(_item_topic_slugs(item))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _seed_items
    _seed_items = load_interview_seed()
    validate_seed_against_allowlist(_seed_items, ALLOWED_SLUGS)
    rag.load_items(_seed_items)
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


@app.get("/topics", response_model=TopicsListResponse)
async def list_topics() -> TopicsListResponse:
    """返回当前白名单 slug 与展示名，供前端渲染筛选。"""
    entries = [
        TopicEntry(slug=e["slug"], label=e["label"]) for e in _topic_entries
    ]
    return TopicsListResponse(topics=entries)


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
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )
    filtered = _normalize_request_topics(body.topics)
    picked = rag.pick_question(filtered, body.difficulty)
    if picked is None:
        raise HTTPException(
            status_code=404,
            detail="当前所选标签与难度下暂无题库条目，请更换条件。",
        )
    kps = picked.get("key_points") or []
    if not isinstance(kps, list):
        kps = [str(kps)]
    kps = [str(x) for x in kps]

    return GenerateQuestionResponse(
        question_id=str(picked.get("id", "")),
        question=str(picked.get("question", "")),
        topics=_topics_sorted_from_item(picked),
        difficulty=body.difficulty,
        expected_key_points=kps,
        reference_snippets=[],
    )


def _parse_eval_json(content: str) -> Dict[str, Any]:
    return json.loads(content)


@app.post("/evaluate-answer", response_model=EvaluateAnswerResponse)
async def evaluate_answer(body: EvaluateAnswerRequest) -> EvaluateAnswerResponse:
    req_topics = _normalize_request_topics(body.topics)
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )

    canonical = _item_by_id(body.question_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="未知的 question_id，不在当前题库中。")
    canon_ts = _item_topic_slugs(canonical)
    if not (canon_ts & set(req_topics)):
        raise HTTPException(
            status_code=400,
            detail="请求中的 topics 与本题标签无交集，请使用出题时相同的筛选标签。",
        )
    if str(canonical.get("difficulty", "")).strip() != body.difficulty.strip():
        raise HTTPException(status_code=400, detail="question_id 与 difficulty 不一致。")
    if str(canonical.get("question", "")).strip() != body.question.strip():
        raise HTTPException(status_code=400, detail="question 与题库中该 id 对应题干不一致。")

    # 评卷仅依据本题题库条目，不做向量检索或合并邻居条目。
    ordered: List[Dict[str, Any]] = [canonical]

    ref_lines = [_snippet_from_item(it).content for it in ordered]
    key_points_union: List[str] = []
    for it in ordered:
        _extend_key_points_union(key_points_union, it)
    evidence = [_snippet_from_item(it) for it in ordered]

    reference_block = "\n\n---\n\n".join(ref_lines)
    key_points_block = "\n".join(f"- {p}" for p in key_points_union[:30])

    user_prompt = build_evaluation_user_prompt(
        topics=sorted(req_topics),
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
        raise HTTPException(status_code=502, detail="score 必须在 0–10")

    return EvaluateAnswerResponse(
        score=score,
        strengths=[str(x) for x in strengths],
        missing_points=[str(x) for x in missing],
        improved_answer=improved,
        reference_evidence=evidence,
    )
