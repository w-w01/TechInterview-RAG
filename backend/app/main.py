"""InterviewMate FastAPI 入口：健康检查、练习会话、随机/AI 出题、JD 向量组卷、本题锚定评卷。"""

import json
import logging
import os
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from .data_loader import load_interview_seed
from .knowledge_documents import (
    document_json_path,
    load_document_json,
    relative_document_path,
    save_document_json,
)
from .knowledge_rag import KnowledgeRAGService
from .embedding_index import seed_embedding_index
from .generation_store import GenerationSnapshot, get_snapshot, put_snapshot
from .prompts import (
    EVALUATION_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    JD_PLANNER_SYSTEM_PROMPT,
    JD_SELECTOR_SYSTEM_PROMPT,
    TUTOR_CHAT_SYSTEM,
    TUTOR_LEARNING_PLAN_SYSTEM,
    build_evaluation_user_prompt,
    build_generation_user_prompt,
    build_jd_planner_user_prompt,
    build_jd_selector_user_prompt,
    build_tutor_chat_user,
    build_tutor_learning_plan_user,
)
from .rag import RAGService, _item_topic_slugs
from .query_rewrite import rewrite_query_with_llm
from .schemas import (
    CreateSessionResponse,
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
    GenerateLlmQuestionRequest,
    GenerateLlmQuestionResponse,
    GeneratePaperFromJdRequest,
    GeneratePaperFromJdResponse,
    PaperBuildMeta,
    PaperQuestion,
    GenerateQuestionRequest,
    GenerateQuestionResponse,
    HealthResponse,
    KnowledgeDocumentIngestRequest,
    KnowledgeDocumentIngestResponse,
    NextPaperPlanResponse,
    PracticeAttemptEntry,
    PracticePaperEntry,
    ReferenceSnippet,
    SessionDetailResponse,
    TopicEntry,
    TopicsListResponse,
    TutorChatRequest,
    TutorChatResponse,
    TutorCitation,
    TutorLearningPlanRequest,
    TutorLearningPlanResponse,
    TutorPlanDay,
    TutorPlanTask,
)
from .session_store import (
    PracticeSession,
    append_attempt,
    create_paper,
    create_session,
    get_session,
    get_topic_baseline,
    record_weak_topics,
    update_attempt_result,
)
from .topic_config import load_topic_allowlist, validate_seed_against_allowlist

# 从 backend/.env 加载环境变量
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_DIFFICULTY = {"beginner", "intermediate", "advanced"}


def _env_int(name: str, default: int, *, min_v: int = 0) -> int:
    """读取整型环境变量，非法值回落默认值。"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = int(str(raw).strip())
        return max(min_v, v)
    except ValueError:
        logger.warning("环境变量 %s=%r 非法，回退默认值 %s", name, raw, default)
        return default


def _env_float(name: str, default: float, *, min_v: float = 0.0, max_v: float = 1.0) -> float:
    """读取浮点环境变量，非法值回落默认值。"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = float(str(raw).strip())
        return max(min_v, min(max_v, v))
    except ValueError:
        logger.warning("环境变量 %s=%r 非法，回退默认值 %s", name, raw, default)
        return default


# JD 混卷策略参数（可配置；默认偏“真题优先”）。
JD_BASE_AI_RATIO_EVERY = _env_int("JD_BASE_AI_RATIO_EVERY", 5, min_v=1)  # 每 N 题约 1 题 AI
JD_UNSEEN_SUFFICIENT_MULTIPLIER = _env_int("JD_UNSEEN_SUFFICIENT_MULTIPLIER", 2, min_v=1)
JD_SEEN_RATIO_MID = _env_float("JD_SEEN_RATIO_MID", 0.5, min_v=0.0, max_v=1.0)
JD_SEEN_RATIO_HIGH = _env_float("JD_SEEN_RATIO_HIGH", 0.8, min_v=0.0, max_v=1.0)
JD_SHORTFALL_EXTRA_DIV = _env_int("JD_SHORTFALL_EXTRA_DIV", 2, min_v=1)
JD_CANDIDATE_PER_TOPIC = _env_int("JD_CANDIDATE_PER_TOPIC", 12, min_v=4)
JD_SELECTOR_MAX_ITEMS = _env_int("JD_SELECTOR_MAX_ITEMS", 96, min_v=20)
QUERY_REWRITE_MODEL = os.getenv("QUERY_REWRITE_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

_topic_entries: List[Dict[str, str]] = load_topic_allowlist()
ALLOWED_SLUGS: Set[str] = {e["slug"] for e in _topic_entries}

rag = RAGService()
knowledge_rag = KnowledgeRAGService(
    docs_root=Path(__file__).resolve().parent.parent / "data" / "knowledge" / "documents"
)
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


def _validate_session_id_optional(session_id: Optional[str]) -> None:
    """若提供 session_id，须为已登记会话。"""
    if session_id is None or str(session_id).strip() == "":
        return
    sid = str(session_id).strip()
    if get_session(sid) is None:
        raise HTTPException(status_code=400, detail="无效的 session_id，请先 POST /sessions 创建。")


def _snippet_for_seed_item(it: Dict[str, Any]) -> ReferenceSnippet:
    """带种子 id 的引用片段，便于 AI 题展示来源。"""
    body = _snippet_from_item(it)
    iid = str(it.get("id", "")).strip()
    src = f"seed:{iid}" if iid else body.source
    return ReferenceSnippet(source=src, content=body.content)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _seed_items
    _seed_items = load_interview_seed()
    validate_seed_against_allowlist(_seed_items, ALLOWED_SLUGS)
    rag.load_items(_seed_items)
    await seed_embedding_index.build(_seed_items, _get_openai())
    await knowledge_rag.build()
    yield


app = FastAPI(title="InterviewMate RAG", version="0.1.0", lifespan=lifespan)


def _cors_middleware_params() -> Dict[str, Any]:
    """
    开发联调 CORS：
    - 默认：前端、n8n 本地 UI、Cloudflare Quick Tunnel 子域（正则）。
    - DEV_CORS_ALLOW_ALL=true：允许任意 Origin（此时关闭 credentials，符合浏览器规范）。
    """
    dev_all = (
        os.getenv("DEV_CORS_ALLOW_ALL", "").strip().lower() in ("1", "true", "yes")
        or os.getenv("APP_ENV", "").strip().lower() == "development"
    )
    if dev_all:
        return {
            "allow_origins": ["*"],
            "allow_credentials": False,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    params: Dict[str, Any] = {
        "allow_origins": [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5678",
            "http://127.0.0.1:5678",
        ],
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "allow_origin_regex": r"https?://[\w-]+\.trycloudflare\.com",
    }
    return params


app.add_middleware(CORSMiddleware, **_cors_middleware_params())


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


def _item_to_generate_question_response(
    item: Dict[str, Any], difficulty: str
) -> GenerateQuestionResponse:
    """种子 dict 转为与单题出题一致的响应体。"""
    kps = item.get("key_points") or []
    if not isinstance(kps, list):
        kps = [str(kps)]
    kps = [str(x) for x in kps]
    return GenerateQuestionResponse(
        question_id=str(item.get("id", "")),
        question=str(item.get("question", "")),
        topics=_topics_sorted_from_item(item),
        difficulty=difficulty,
        expected_key_points=kps,
        reference_snippets=[],
    )


def _weak_score_for_item(item: Dict[str, Any], weak_topics: List[str]) -> int:
    """按薄弱点关键词与题目文本重叠打分，用于补弱排序。"""
    if not weak_topics:
        return 0
    text = (
        f"{item.get('question', '')}\n{item.get('answer', '')}\n"
        f"{' '.join(str(x) for x in (item.get('key_points') or []))}"
    ).lower()
    score = 0
    for t in weak_topics:
        w = str(t).strip().lower()
        if w and w in text:
            score += 1
    return score


def _normalize_question_key(text: str) -> str:
    """用于题干去重的规范化 key。"""
    return " ".join(str(text).strip().lower().split())


_DIFF_ORDER = ["beginner", "intermediate", "advanced"]


def _clamp_difficulty(diff: str) -> str:
    d = str(diff).strip().lower()
    return d if d in _DIFF_ORDER else "intermediate"


def _bump_difficulty(diff: str, delta: int) -> str:
    cur = _clamp_difficulty(diff)
    idx = _DIFF_ORDER.index(cur)
    nxt = max(0, min(len(_DIFF_ORDER) - 1, idx + int(delta)))
    return _DIFF_ORDER[nxt]


def _topic_priority_from_ranked(
    ranked: List[Dict[str, Any]], weakness_counts: Dict[str, int]
) -> List[str]:
    """从 JD 检索候选与弱点计数构造 topic 优先级（高到低）。"""
    freq: Counter = Counter()
    for it in ranked:
        for t in _topics_sorted_from_item(it):
            freq[t] += 1
    for t, c in weakness_counts.items():
        tt = str(t).strip().lower()
        if tt:
            freq[tt] += int(c) * 2
    if not freq:
        return []
    return [k for k, _ in freq.most_common()]


def _jd_primary_topic_cap(paper_or_seed_count: int) -> int:
    """
    JD 组卷：最高优先级 topic 在整卷（或真题槽位数）中的上限。
    例如 5 题时约 2～3 题，避免全卷挤在同一知识点。
    """
    n = int(paper_or_seed_count)
    if n <= 0:
        return 0
    if n <= 2:
        return n
    return min(3, max(2, (n + 1) // 2))


def _count_picked_with_topic(picked: List[Dict[str, Any]], topic: str) -> int:
    if not str(topic).strip():
        return 0
    return sum(1 for it in picked if topic in _topics_sorted_from_item(it))


def _jd_count_primary_in_paper_questions(
    paper_questions: List[PaperQuestion], primary: str
) -> int:
    if not str(primary).strip():
        return 0
    n = 0
    for q in paper_questions:
        topics = q.topics or []
        if primary in topics:
            n += 1
    return n


def _recommended_difficulty_by_topic(
    topic_baseline: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, str], List[str]]:
    """
    基于最近3卷 baseline 给出每个topic推荐难度。
    仅在多次偏离时调整：high_count>=2 才升，low_count>=2 才降。
    """
    rec: Dict[str, str] = {}
    reasons: List[str] = []
    for topic, b in topic_baseline.items():
        counts = b.get("difficulty_counts") or {}
        dom = "intermediate"
        if counts:
            dom = max(_DIFF_ORDER, key=lambda d: int(counts.get(d, 0)))
        high_c = int(b.get("high_count", 0))
        low_c = int(b.get("low_count", 0))
        if high_c >= 2 and low_c == 0:
            rec[topic] = _bump_difficulty(dom, +1)
            reasons.append(f"{topic}:连续高分，上调难度")
        elif low_c >= 2 and high_c == 0:
            rec[topic] = _bump_difficulty(dom, -1)
            reasons.append(f"{topic}:连续低分，下调难度")
        else:
            rec[topic] = dom
    return rec, reasons


def _compute_ai_mix_count(
    total_count: int, ranked_seed: List[Dict[str, Any]], seen_seed_ids: List[str]
) -> int:
    """
    计算 JD 试卷中的 AI 题数量（真题优先，真题不足时才抬升 AI 比例）。
    - 基线：每 `JD_BASE_AI_RATIO_EVERY` 题约 1 题 AI。
    - 若候选中“未做过真题”充足，则保持基线，不额外抬升。
    - 仅在高重复/真题短缺时提高 AI 比例。
    """
    if total_count <= 0:
        return 0
    base = max(1, total_count // JD_BASE_AI_RATIO_EVERY)
    if not ranked_seed:
        return total_count
    seen = set(seen_seed_ids)
    seen_hits = sum(1 for it in ranked_seed if str(it.get("id", "")) in seen)
    seen_ratio = seen_hits / max(1, len(ranked_seed))
    unseen_count = max(0, len(ranked_seed) - seen_hits)

    # 若候选中可用新真题充足，不提升 AI 比例（避免“强制多出 AI 题”）。
    if unseen_count >= total_count * JD_UNSEEN_SUFFICIENT_MULTIPLIER:
        return min(total_count - 1 if total_count > 1 else 1, base)

    extra = 0
    # 真题明显耗尽时再提升 AI 比例：
    # 1) 高重复（seen_ratio 高）；
    # 2) 或可用新真题不足以覆盖本轮题量。
    if unseen_count < total_count:
        shortfall = total_count - unseen_count
        extra += max(1, shortfall // JD_SHORTFALL_EXTRA_DIV)
    if seen_ratio >= JD_SEEN_RATIO_HIGH:
        extra = max(2, total_count // 3)
    elif seen_ratio >= JD_SEEN_RATIO_MID:
        extra = max(extra, max(1, total_count // 5))
    ai_count = min(total_count - 1 if total_count > 1 else 1, base + extra)
    return max(0, ai_count)


def _compute_ai_mix_decision(
    total_count: int, ranked_seed: List[Dict[str, Any]], seen_seed_ids: List[str]
) -> Tuple[int, str, float, int]:
    """返回 AI 题数量与解释信息。"""
    if total_count <= 0:
        return 0, "normal_base_ratio", 0.0, 0
    if not ranked_seed:
        return total_count, "seed_shortage", 1.0, 0
    seen = set(seen_seed_ids)
    seen_hits = sum(1 for it in ranked_seed if str(it.get("id", "")) in seen)
    seen_ratio = seen_hits / max(1, len(ranked_seed))
    unseen_count = max(0, len(ranked_seed) - seen_hits)
    ai_count = _compute_ai_mix_count(total_count, ranked_seed, seen_seed_ids)
    base = max(1, total_count // JD_BASE_AI_RATIO_EVERY)
    reason = "normal_base_ratio"
    if ai_count > base:
        if unseen_count < total_count:
            reason = "seed_shortage"
        elif seen_ratio >= JD_SEEN_RATIO_MID:
            reason = "high_seen_ratio"
    return ai_count, reason, float(seen_ratio), unseen_count


async def _generate_llm_question_from_samples(
    *,
    topics: List[str],
    difficulty: str,
    samples: List[Dict[str, Any]],
    forbidden_question_keys: Set[str],
) -> Tuple[PaperQuestion, Dict[str, Any]]:
    """复用 AI 出题能力，返回 JD 混卷用的单道 AI 题与用于会话记录的 attempt。"""
    user_prompt = build_generation_user_prompt(
        topics=topics, difficulty=difficulty, reference_items=samples
    )
    completion = await _get_openai().chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.65,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        data = _parse_generation_json(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"出题模型返回非合法 JSON: {e}") from e
    try:
        qtext = str(data["question"]).strip()
        kps = [str(x).strip() for x in list(data["expected_key_points"]) if str(x).strip()]
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"出题 JSON 字段不完整: {e}") from e
    if not qtext or not kps:
        raise HTTPException(status_code=502, detail="AI 出题结果缺少题干或要点")
    if _normalize_question_key(qtext) in forbidden_question_keys:
        raise RuntimeError("duplicate_llm_question")
    gen_id = str(uuid.uuid4())
    seed_ids = [str(it.get("id", "")) for it in samples if str(it.get("id", "")).strip()]
    topic_slugs_sorted = sorted({str(t).strip().lower() for t in topics})
    put_snapshot(
        GenerationSnapshot(
            generation_id=gen_id,
            question=qtext,
            expected_key_points=kps,
            source_seed_ids=seed_ids,
            topics=topic_slugs_sorted,
            difficulty=difficulty.strip(),
        )
    )
    paper_q = PaperQuestion(
        source="llm",
        question_id=None,
        generation_id=gen_id,
        question=qtext,
        topics=topic_slugs_sorted,
        difficulty=difficulty,
        expected_key_points=kps,
        reference_snippets=[_snippet_for_seed_item(it) for it in samples],
        source_seed_ids=seed_ids,
    )
    attempt = {
        "source": "llm",
        "question_id": None,
        "generation_id": gen_id,
        "question_text": qtext,
        "topics": list(topic_slugs_sorted),
        "difficulty": difficulty,
    }
    return paper_q, attempt


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
        embedding_index_ready=seed_embedding_index.ready,
        seed_items=len(_seed_items),
        message="InterviewMate RAG backend",
    )


@app.post(
    "/knowledge/documents",
    response_model=KnowledgeDocumentIngestResponse,
    status_code=201,
)
async def ingest_knowledge_document(
    body: KnowledgeDocumentIngestRequest,
    overwrite: bool = Query(
        False,
        description="为 true 时允许覆盖已存在的同路径 JSON；默认 false 冲突返回 409。",
    ),
) -> KnowledgeDocumentIngestResponse:
    """接收规范化文档 JSON 并落盘；不做分块、嵌入与检索。"""
    try:
        path = document_json_path(body.corpus_id, body.doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    existed = path.is_file()
    payload: Dict[str, Any] = body.model_dump(mode="json")
    try:
        save_document_json(
            body.corpus_id, body.doc_id, payload, overwrite=overwrite
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail="同 corpus_id 与 doc_id 的文档已存在；附加查询参数 overwrite=true 可覆盖。",
        ) from None
    return KnowledgeDocumentIngestResponse(
        corpus_id=body.corpus_id,
        doc_id=body.doc_id,
        saved_path=relative_document_path(body.corpus_id, body.doc_id),
        overwritten=bool(existed and overwrite),
    )


@app.get("/knowledge/documents/{corpus_id}/{doc_id}")
async def get_knowledge_document(corpus_id: str, doc_id: str) -> Dict[str, Any]:
    """读取已保存的文档 JSON，用于联调校验。"""
    try:
        return load_document_json(corpus_id, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文档不存在。") from None
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"已存文件不是合法 JSON: {e}",
        ) from e


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_practice_session() -> CreateSessionResponse:
    """创建练习会话；后续出题可携带 session_id 记录尝试。"""
    s = create_session()
    return CreateSessionResponse(session_id=s.session_id, created_at=s.created_at)


@app.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_practice_session(session_id: str) -> SessionDetailResponse:
    """查询会话及出题历史（本地演示）。"""
    s = get_session(session_id.strip())
    if s is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    attempts = [PracticeAttemptEntry(**a) for a in s.attempts]
    papers = [PracticePaperEntry(**p) for p in s.papers]
    return SessionDetailResponse(
        session_id=s.session_id,
        created_at=s.created_at,
        papers=papers,
        attempts=attempts,
        seen_seed_ids=list(s.seen_seed_ids),
        weakness_counts=dict(s.weakness_counts),
    )


@app.get("/sessions/{session_id}/next-paper-plan", response_model=NextPaperPlanResponse)
async def get_next_paper_plan(session_id: str) -> NextPaperPlanResponse:
    """返回基于最近3卷的下一卷规则计划（用于解释与调试）。"""
    sid = str(session_id).strip()
    sess = get_session(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    baseline_window = 3
    topic_baseline = get_topic_baseline(sid, baseline_window)
    weakness = dict(sess.weakness_counts)
    topic_priority: List[str] = []
    topic_priority_source = ""
    topic_priority_explanation = ""
    if sess.papers:
        last_meta = sess.papers[-1].get("meta") or {}
        tp_from_meta = [str(x) for x in (last_meta.get("topic_priority") or [])]
        if tp_from_meta:
            topic_priority = tp_from_meta
            topic_priority_source = "last_paper_meta"
            last_src = str(sess.papers[-1].get("source") or "")
            if last_src == "jd_rag_mix":
                topic_priority_explanation = (
                    "来自本会话最近一张试卷的 meta.topic_priority（JD 组卷，与当次 "
                    "Planner 或程序回退排序一致；本条接口不调用 LLM）。"
                )
            else:
                topic_priority_explanation = (
                    "来自本会话最近一张试卷的 meta.topic_priority（非 jd_rag_mix 时与 "
                    "JD Planner 无必然对应，仅供参考）。"
                )
    if not topic_priority:
        ranked_stub = _seed_items[:120] if _seed_items else []
        topic_priority = _topic_priority_from_ranked(ranked_stub, weakness)
        topic_priority_source = "seed_frequency_weakness_stub"
        topic_priority_explanation = (
            "上一张卷无可用 topic_priority；已用题库前 120 条结合弱点计数近似排序，"
            "与 POST /generate-paper-from-jd 当次 LLM Planner 无直接对应，仅供调试。"
        )
    rec_map, reasons = _recommended_difficulty_by_topic(topic_baseline)
    if not reasons:
        reasons.append("暂无连续偏离，维持主难度并保留随机性")
    return NextPaperPlanResponse(
        session_id=sid,
        baseline_window=baseline_window,
        topic_priority=topic_priority,
        topic_priority_source=topic_priority_source,
        topic_priority_explanation=topic_priority_explanation,
        topic_baseline=topic_baseline,
        recommended_difficulty_by_topic=rec_map,
        reasons=reasons,
    )


@app.post("/generate-question", response_model=GenerateQuestionResponse)
async def generate_question(body: GenerateQuestionRequest) -> GenerateQuestionResponse:
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )
    _validate_session_id_optional(body.session_id)
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

    if body.session_id and str(body.session_id).strip():
        append_attempt(
            str(body.session_id).strip(),
            {
                "source": "seed",
                "question_id": str(picked.get("id", "")),
                "generation_id": None,
                "question_text": str(picked.get("question", "")),
                "topics": list(filtered),
                "difficulty": body.difficulty,
            },
        )

    return GenerateQuestionResponse(
        question_id=str(picked.get("id", "")),
        question=str(picked.get("question", "")),
        topics=_topics_sorted_from_item(picked),
        difficulty=body.difficulty,
        expected_key_points=kps,
        reference_snippets=[],
    )


def _parse_generation_json(content: str) -> Dict[str, Any]:
    return json.loads(content)


@app.post("/generate-question-llm", response_model=GenerateLlmQuestionResponse)
async def generate_question_llm(
    body: GenerateLlmQuestionRequest,
) -> GenerateLlmQuestionResponse:
    """结构化池内抽样少样本，由 LLM 生成新题；池空则零样本生成。"""
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )
    _validate_session_id_optional(body.session_id)
    norm_topics = _normalize_request_topics(body.topics)
    pool = rag.pool_for_topics_and_difficulty(norm_topics, body.difficulty)
    k = body.reference_max if body.reference_max > 0 else 0
    samples = rag.sample_pool_items(pool, k)
    user_prompt = build_generation_user_prompt(
        topics=norm_topics,
        difficulty=body.difficulty,
        reference_items=samples,
    )
    model = "gpt-4o-mini"
    completion = await _get_openai().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.65,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        data = _parse_generation_json(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"出题模型返回非合法 JSON: {e}") from e
    try:
        qtext = str(data["question"]).strip()
        kps = list(data["expected_key_points"])
        kps = [str(x).strip() for x in kps if str(x).strip()]
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"出题 JSON 字段不完整: {e}") from e
    if not qtext:
        raise HTTPException(status_code=502, detail="出题结果题干为空")
    if not kps:
        raise HTTPException(status_code=502, detail="出题结果 expected_key_points 为空")

    gen_id = str(uuid.uuid4())
    seed_ids = [str(it.get("id", "")) for it in samples if str(it.get("id", "")).strip()]
    snippets = [_snippet_for_seed_item(it) for it in samples]
    topic_slugs_sorted = sorted({str(t).strip().lower() for t in norm_topics})
    snap = GenerationSnapshot(
        generation_id=gen_id,
        question=qtext,
        expected_key_points=kps,
        source_seed_ids=seed_ids,
        topics=topic_slugs_sorted,
        difficulty=body.difficulty.strip(),
    )
    put_snapshot(snap)

    if body.session_id and str(body.session_id).strip():
        append_attempt(
            str(body.session_id).strip(),
            {
                "source": "llm",
                "question_id": None,
                "generation_id": gen_id,
                "question_text": qtext,
                "topics": list(norm_topics),
                "difficulty": body.difficulty,
            },
        )

    return GenerateLlmQuestionResponse(
        generation_id=gen_id,
        question=qtext,
        topics=topic_slugs_sorted,
        difficulty=body.difficulty,
        expected_key_points=kps,
        reference_snippets=snippets,
        source_seed_ids=seed_ids,
    )


def _jd_key_points_preview(
    item: Dict[str, Any], max_n: int = 4, max_len: int = 120
) -> List[str]:
    """候选送给 Selector 的要点预览（缩短 token）。"""
    kp = item.get("key_points") or []
    if not isinstance(kp, list):
        kp = [str(kp)] if kp else []
    out: List[str] = []
    for x in kp[:max_n]:
        s = str(x).strip()
        if len(s) > max_len:
            s = s[:max_len] + "…"
        if s:
            out.append(s)
    return out


def _build_jd_selector_candidate_items(
    topic_priority: List[str],
    ranked: List[Dict[str, Any]],
    answered_seed_ids: Set[str],
) -> List[Dict[str, Any]]:
    """按 topic 优先级从 JD 检索序中分层取候选，再全局补足。"""
    per_topic_cap = JD_CANDIDATE_PER_TOPIC
    global_cap = JD_SELECTOR_MAX_ITEMS
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for tp in topic_priority:
        n = 0
        for it in ranked:
            if len(out) >= global_cap:
                return out
            iid = str(it.get("id", "")).strip()
            if not iid or iid in seen or iid in answered_seed_ids:
                continue
            if tp not in _topics_sorted_from_item(it):
                continue
            seen.add(iid)
            out.append(it)
            n += 1
            if n >= per_topic_cap:
                break
    for it in ranked:
        if len(out) >= global_cap:
            break
        iid = str(it.get("id", "")).strip()
        if not iid or iid in seen or iid in answered_seed_ids:
            continue
        seen.add(iid)
        out.append(it)
    return out


def _jd_candidate_rows_for_selector_json(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for it in items:
        rows.append(
            {
                "question_id": str(it.get("id", "")),
                "question": str(it.get("question", ""))[:2000],
                "topics": sorted(_item_topic_slugs(it)),
                "difficulty": str(it.get("difficulty", "")),
                "key_points_preview": _jd_key_points_preview(it),
            }
        )
    return rows


async def _jd_run_topic_planner(jd_text: str) -> Tuple[List[str], List[str]]:
    """Planner：只输出白名单内 topic 优先级。"""
    allowlist_lines = "\n".join(
        f"- {e['slug']}: {e['label']}" for e in _topic_entries
    )
    user_prompt = build_jd_planner_user_prompt(
        jd_text=jd_text, allowlist_lines=allowlist_lines
    )
    last_err: Optional[Exception] = None
    for _ in range(2):
        try:
            completion = await _get_openai().chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": JD_PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.35,
            )
            raw = completion.choices[0].message.content or "{}"
            data = json.loads(raw)
            raw_list = data.get("topic_priority") or []
            out: List[str] = []
            for x in raw_list:
                s = str(x).strip().lower()
                if s in ALLOWED_SLUGS and s not in out:
                    out.append(s)
            notes_raw = data.get("notes") or []
            notes = [str(x).strip() for x in notes_raw if str(x).strip()]
            return out, notes[:6]
        except Exception as e:
            last_err = e
            continue
    raise HTTPException(
        status_code=502, detail=f"JD topic 规划失败: {last_err!s}"
    ) from last_err


def _jd_selector_validation_issues(
    selected_ids: List[str],
    raw_ai_slots_len: int,
    valid_ids: Set[str],
    seed_count: int,
    ai_count: int,
) -> List[str]:
    """Selector 首次输出严格校验，未通过则拼接为重选提示。"""
    issues: List[str] = []
    bad = [i for i in selected_ids if i and i not in valid_ids]
    if bad:
        issues.append(f"下列 id 不在候选 question_id 中，禁止输出：{bad[:20]}")
    seen: Set[str] = set()
    dup: Set[str] = set()
    for i in selected_ids:
        if not i:
            continue
        if i in seen:
            dup.add(i)
        seen.add(i)
    if dup:
        issues.append(f"selected_seed_ids 含重复 id：{sorted(dup)}")
    good = [i for i in selected_ids if i in valid_ids]
    if len(good) != seed_count:
        issues.append(
            f"selected_seed_ids 在候选内有效 id 应为 {seed_count} 个，当前有效 {len(good)} 个（你共输出 {len(selected_ids)} 个）。"
        )
    if raw_ai_slots_len != ai_count:
        issues.append(
            f"ai_slots 数组长度应为 {ai_count}，当前为 {raw_ai_slots_len}（须每项为含 topics、difficulty 的对象）。"
        )
    return issues


async def _jd_run_paper_selector(
    *,
    jd_excerpt: str,
    topic_priority: List[str],
    seed_count: int,
    ai_count: int,
    request_difficulty: str,
    primary_topic_cap: int,
    weak_topics: List[str],
    recommended_by_topic: Dict[str, str],
    candidate_rows: List[Dict[str, Any]],
    repair_hint: Optional[str] = None,
) -> Tuple[List[str], List[Dict[str, Any]], str, int]:
    """Selector：仅允许选择候选中的 question_id，并规划 AI 槽位。返回原始 ai_slots 数组长度供校验。"""
    rec_json = json.dumps(recommended_by_topic, ensure_ascii=False)
    cand_json = json.dumps(candidate_rows, ensure_ascii=False)
    user_prompt = build_jd_selector_user_prompt(
        jd_excerpt=jd_excerpt,
        topic_priority=topic_priority,
        seed_count=seed_count,
        ai_count=ai_count,
        request_difficulty=request_difficulty,
        primary_topic_cap=primary_topic_cap,
        weak_topics=weak_topics,
        recommended_by_topic_json=rec_json,
        candidates_json=cand_json,
    )
    if repair_hint:
        user_prompt += "\n\n【上次输出未通过校验，请按下列要求修正后重新输出完整 JSON】\n" + repair_hint
    last_err: Optional[Exception] = None
    for _ in range(2):
        try:
            completion = await _get_openai().chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": JD_SELECTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.25,
            )
            raw = completion.choices[0].message.content or "{}"
            data = json.loads(raw)
            ids = [str(x).strip() for x in (data.get("selected_seed_ids") or [])]
            slots_raw = data.get("ai_slots")
            if not isinstance(slots_raw, list):
                slots_raw = []
            raw_ai_slots_len = len(slots_raw)
            norm_slots: List[Dict[str, Any]] = []
            for s in slots_raw:
                if not isinstance(s, dict):
                    continue
                t_list = [
                    str(x).strip().lower()
                    for x in (s.get("topics") or [])
                    if str(x).strip().lower() in ALLOWED_SLUGS
                ]
                t_list = list(dict.fromkeys(t_list))[:4]
                d = str(s.get("difficulty") or "").strip().lower()
                if d not in ALLOWED_DIFFICULTY:
                    d = ""
                norm_slots.append({"topics": t_list, "difficulty": d})
            notes = str(data.get("notes") or "").strip()
            return ids, norm_slots, notes, raw_ai_slots_len
        except Exception as e:
            last_err = e
            continue
    raise HTTPException(
        status_code=502, detail=f"JD 选题规划失败: {last_err!s}"
    ) from last_err


def _finalize_seed_picked_from_selector(
    selected_ids: List[str],
    candidate_by_id: Dict[str, Dict[str, Any]],
    seed_count: int,
    seed_candidates_ordered: List[Dict[str, Any]],
    topic_priority: List[str],
    program_fixes: List[str],
) -> List[Dict[str, Any]]:
    """校验 id、去重、单 topic 上限与不足补齐。"""
    valid_set = set(candidate_by_id.keys())
    filtered: List[str] = []
    seen: Set[str] = set()
    for i in selected_ids:
        if i in valid_set and i not in seen:
            filtered.append(i)
            seen.add(i)
        elif i and i not in valid_set:
            program_fixes.append(f"忽略无效真题 id：{i}")

    primary_tp = topic_priority[0] if topic_priority else ""
    cap = _jd_primary_topic_cap(seed_count)

    def count_primary(ids: List[str]) -> int:
        return sum(
            1
            for x in ids
            if x in candidate_by_id
            and primary_tp in _topics_sorted_from_item(candidate_by_id[x])
        )

    passed: List[str] = []
    for i in filtered:
        if len(passed) >= seed_count:
            break
        it = candidate_by_id.get(i)
        if not it:
            continue
        if primary_tp and primary_tp in _topics_sorted_from_item(it):
            if count_primary(passed) >= cap:
                program_fixes.append(
                    f"跳过真题 {i}（已达最高优 topic 真题上限 {cap}）"
                )
                continue
        passed.append(i)

    for it in seed_candidates_ordered:
        if len(passed) >= seed_count:
            break
        iid = str(it.get("id", "")).strip()
        if not iid or iid in passed or iid not in valid_set:
            continue
        if primary_tp and primary_tp in _topics_sorted_from_item(it):
            if count_primary(passed) >= cap:
                continue
        passed.append(iid)
        program_fixes.append(f"程序补齐真题 id {iid}")

    return [candidate_by_id[i] for i in passed[:seed_count] if i in candidate_by_id]


def _normalize_ai_slots_list(
    raw_slots: List[Dict[str, Any]],
    ai_count: int,
    topic_priority: List[str],
    body_difficulty: str,
    program_fixes: List[str],
) -> List[Dict[str, Any]]:
    """将 Selector 的 ai_slots 规范到固定条数与合法 topics/difficulty。"""
    slots = list(raw_slots)
    tp_fallback = topic_priority[0] if topic_priority else next(iter(ALLOWED_SLUGS))
    while len(slots) < ai_count:
        idx = len(slots)
        rot = topic_priority[idx % len(topic_priority)] if topic_priority else tp_fallback
        slots.append({"topics": [rot], "difficulty": body_difficulty})
        program_fixes.append("程序补齐 AI 槽位")
    if len(slots) > ai_count:
        program_fixes.append(f"截断 AI 槽位 {len(slots)}→{ai_count}")
        slots = slots[:ai_count]
    out: List[Dict[str, Any]] = []
    for s in slots:
        topics = [t for t in (s.get("topics") or []) if t in ALLOWED_SLUGS]
        topics = list(dict.fromkeys(topics))
        if not topics:
            topics = [tp_fallback]
        diff = str(s.get("difficulty") or "").strip().lower()
        if diff not in ALLOWED_DIFFICULTY:
            diff = body_difficulty
        out.append({"topics": topics[:4], "difficulty": diff})
    return out


@app.post("/generate-paper-from-jd", response_model=GeneratePaperFromJdResponse)
async def generate_paper_from_jd(
    body: GeneratePaperFromJdRequest,
) -> GeneratePaperFromJdResponse:
    """JD 组卷：向量检索候选 → LLM Planner(topic 白名单优先级) → LLM Selector(选题+AI 槽) → 程序校验出题。"""
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )
    if not seed_embedding_index.ready:
        raise HTTPException(
            status_code=503,
            detail="向量索引未就绪，请确认启动已成功调用 Embedding。",
        )
    _validate_session_id_optional(body.session_id)
    jd_raw = body.jd_text.strip()
    jd_trunc = jd_raw[:12000]
    qvec = await seed_embedding_index.embed_query(_get_openai(), jd_trunc)
    # 检索候选池（后续按策略再挑选）：仅当 auto_adapt=false 时严格按请求难度，
    # 否则首卷/自适应会跨难度做覆盖或调节。
    target_diffs = (
        [body.difficulty]
        if not body.auto_adapt
        else ["beginner", "intermediate", "advanced"]
    )
    ranked_all: List[Dict[str, Any]] = []
    for d in target_diffs:
        ranked_d = seed_embedding_index.search_by_difficulty(
            qvec, _seed_items, d, max(body.count * 4, body.count + 12)
        )
        ranked_all.extend(ranked_d)
    # 保序去重
    seen_rank: Set[str] = set()
    ranked: List[Dict[str, Any]] = []
    for it in ranked_all:
        iid = str(it.get("id", "")).strip()
        if not iid or iid in seen_rank:
            continue
        seen_rank.add(iid)
        ranked.append(it)
    if not ranked:
        raise HTTPException(
            status_code=404,
            detail="该难度下题库无条目，无法组卷。",
        )
    sess = get_session(str(body.session_id).strip()) if body.session_id else None
    seen_seed_ids = list(sess.seen_seed_ids) if sess else []
    answered_seed_ids: Set[str] = set()
    answered_question_keys: Set[str] = set()
    if sess:
        for at in sess.attempts:
            if at.get("score") is None:
                continue
            qid = str(at.get("question_id") or "").strip()
            if qid:
                answered_seed_ids.add(qid)
            qtxt = str(at.get("question_text") or "").strip()
            if qtxt:
                answered_question_keys.add(_normalize_question_key(qtxt))
    weak_topics = []
    if sess and sess.weakness_counts:
        weak_topics = [
            k
            for k, _ in sorted(
                sess.weakness_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:5]
        ]
    topic_priority_llm, planner_notes = await _jd_run_topic_planner(jd_trunc)
    topic_priority = list(topic_priority_llm)
    if not topic_priority:
        topic_priority = _topic_priority_from_ranked(
            ranked, dict(sess.weakness_counts) if sess else {}
        )
        planner_notes = list(planner_notes) + [
            "Planner 未返回合法 slug，已回退为检索候选频次+弱点加权"
        ]

    if weak_topics:
        ranked.sort(
            key=lambda it: (_weak_score_for_item(it, weak_topics)),
            reverse=True,
        )

    baseline_window = 3
    topic_baseline = (
        get_topic_baseline(str(body.session_id).strip(), baseline_window)
        if body.session_id
        else {}
    )
    recommended_by_topic, adjustment_reasons = _recommended_difficulty_by_topic(topic_baseline)

    ai_count, ai_reason, seen_ratio, unseen_count = _compute_ai_mix_decision(
        body.count, ranked, seen_seed_ids
    )
    seed_count = max(0, body.count - ai_count)

    seed_candidates = [
        it for it in ranked if str(it.get("id", "")).strip() not in answered_seed_ids
    ]
    if len(seed_candidates) < seed_count:
        # 已答过真题不回填，改为提升 AI 数量补位，避免重复题。
        shortage = seed_count - len(seed_candidates)
        seed_count = len(seed_candidates)
        ai_count = min(body.count - seed_count, ai_count + shortage)

    if not topic_priority:
        topic_priority = sorted(
            {t for it in seed_candidates for t in _topics_sorted_from_item(it)}
        )

    program_fixes: List[str] = []
    candidate_items = _build_jd_selector_candidate_items(
        topic_priority, ranked, answered_seed_ids
    )
    seed_cand_ids = {str(it.get("id", "")).strip() for it in seed_candidates}
    candidate_items = [
        it
        for it in candidate_items
        if str(it.get("id", "")).strip() in seed_cand_ids
    ]
    if not candidate_items:
        raise HTTPException(
            status_code=404,
            detail="当前 JD 与去重条件下无可用候选真题，无法组卷。",
        )
    candidate_by_id = {
        str(it.get("id", "")).strip(): it
        for it in candidate_items
        if str(it.get("id", "")).strip()
    }
    cand_rows = _jd_candidate_rows_for_selector_json(candidate_items)
    primary_cap_seeds = _jd_primary_topic_cap(seed_count)
    jd_excerpt = jd_trunc[:3500]
    valid_sel_ids = set(candidate_by_id.keys())
    selected_ids, ai_slots_raw, selector_notes, raw_ai_n = await _jd_run_paper_selector(
        jd_excerpt=jd_excerpt,
        topic_priority=topic_priority,
        seed_count=seed_count,
        ai_count=ai_count,
        request_difficulty=body.difficulty,
        primary_topic_cap=primary_cap_seeds,
        weak_topics=weak_topics,
        recommended_by_topic=recommended_by_topic,
        candidate_rows=cand_rows,
    )
    sel_issues = _jd_selector_validation_issues(
        selected_ids, raw_ai_n, valid_sel_ids, seed_count, ai_count
    )
    if sel_issues:
        sample_ids = sorted(valid_sel_ids)[:48]
        hint = "\n".join(sel_issues)
        hint += (
            f"\n合法 question_id 节选（共 {len(valid_sel_ids)} 个，须从中选取"
            f" {seed_count} 个且不重复）：{json.dumps(sample_ids, ensure_ascii=False)}"
        )
        selected_ids, ai_slots_raw, selector_notes, raw_ai_n = await _jd_run_paper_selector(
            jd_excerpt=jd_excerpt,
            topic_priority=topic_priority,
            seed_count=seed_count,
            ai_count=ai_count,
            request_difficulty=body.difficulty,
            primary_topic_cap=primary_cap_seeds,
            weak_topics=weak_topics,
            recommended_by_topic=recommended_by_topic,
            candidate_rows=cand_rows,
            repair_hint=hint,
        )
        program_fixes.append("Selector 首次输出未过严格校验，已带错误说明重选一次")
    seed_picked = _finalize_seed_picked_from_selector(
        selected_ids,
        candidate_by_id,
        seed_count,
        seed_candidates,
        topic_priority,
        program_fixes,
    )
    ai_slots = _normalize_ai_slots_list(
        ai_slots_raw, ai_count, topic_priority, body.difficulty, program_fixes
    )

    questions: List[PaperQuestion] = []
    attempts_to_append: List[Dict[str, Any]] = []
    for it in seed_picked:
        q = _item_to_generate_question_response(
            it, str(it.get("difficulty", body.difficulty))
        )
        questions.append(
            PaperQuestion(
                source="seed",
                question_id=q.question_id,
                generation_id=None,
                question=q.question,
                topics=q.topics,
                difficulty=q.difficulty,
                expected_key_points=q.expected_key_points,
                reference_snippets=q.reference_snippets,
                source_seed_ids=[],
            )
        )
        attempts_to_append.append(
            {
                "source": "seed",
                "question_id": q.question_id,
                "generation_id": None,
                "question_text": q.question,
                "topics": list(q.topics),
                "difficulty": q.difficulty,
            }
        )
        answered_question_keys.add(_normalize_question_key(q.question))

    # AI 题：按 Selector 给出的 ai_slots（topics + difficulty）抽样少样本后出题。
    weak_ranked = [it for it in ranked if _weak_score_for_item(it, weak_topics) > 0]
    ai_sample_pool = weak_ranked if weak_ranked else ranked
    primary_for_mix = topic_priority[0] if topic_priority else ""
    primary_cap_whole_paper = _jd_primary_topic_cap(body.count)
    for slot in ai_slots:
        slot_topics: List[str] = slot["topics"]
        slot_diff: str = slot["difficulty"]
        built = False
        for _retry in range(3):
            pool_match = rag.pool_for_topics_and_difficulty(slot_topics, slot_diff)
            sample_base: List[Dict[str, Any]] = list(pool_match) if pool_match else []
            if not sample_base:
                want = set(slot_topics)
                sample_base = [
                    it
                    for it in ai_sample_pool
                    if _item_topic_slugs(it) & want
                ]
            if not sample_base:
                sample_base = list(ai_sample_pool)
            if primary_for_mix and _jd_count_primary_in_paper_questions(
                questions, primary_for_mix
            ) >= primary_cap_whole_paper:
                narrow_ai = [
                    it
                    for it in sample_base
                    if primary_for_mix not in _topics_sorted_from_item(it)
                ]
                if narrow_ai:
                    sample_base = narrow_ai
            samples = rag.sample_pool_items(sample_base, 3)
            if not samples:
                samples = rag.sample_pool_items(ranked, 3)
            sample_topics: List[str] = []
            for it in samples:
                for slug in _topics_sorted_from_item(it):
                    if slug not in sample_topics:
                        sample_topics.append(slug)
            gen_topics = list(dict.fromkeys([*slot_topics, *sample_topics]))
            try:
                paper_q, attempt = await _generate_llm_question_from_samples(
                    topics=gen_topics,
                    difficulty=slot_diff,
                    samples=samples,
                    forbidden_question_keys=answered_question_keys,
                )
                questions.append(paper_q)
                attempts_to_append.append(attempt)
                answered_question_keys.add(_normalize_question_key(paper_q.question))
                built = True
                break
            except RuntimeError:
                continue
        if not built:
            # AI 连续重复时，用未答过真题补位；再无可补时直接跳过，保证“不中复题”。
            fallback = next(
                (
                    it
                    for it in ranked
                    if str(it.get("id", "")).strip() not in answered_seed_ids
                    and str(it.get("id", "")).strip()
                    not in {x.question_id for x in questions if x.question_id}
                ),
                None,
            )
            if fallback is None:
                continue
            q = _item_to_generate_question_response(
                fallback, str(fallback.get("difficulty", body.difficulty))
            )
            questions.append(
                PaperQuestion(
                    source="seed",
                    question_id=q.question_id,
                    generation_id=None,
                    question=q.question,
                    topics=q.topics,
                    difficulty=q.difficulty,
                    expected_key_points=q.expected_key_points,
                    reference_snippets=q.reference_snippets,
                    source_seed_ids=[],
                )
            )
            attempts_to_append.append(
                {
                    "source": "seed",
                    "question_id": q.question_id,
                    "generation_id": None,
                    "question_text": q.question,
                    "topics": list(q.topics),
                    "difficulty": q.difficulty,
                }
            )
            answered_question_keys.add(_normalize_question_key(q.question))

    # 交错排列：真题优先，但按约每 5 题插入 1 题 AI；当 ai_count 更高时自动加密插入。
    seed_list = [q for q in questions if q.source == "seed"]
    llm_list = [q for q in questions if q.source == "llm"]
    mixed: List[PaperQuestion] = []
    llm_interval = max(1, 5 if body.count >= 5 else 3)
    s_idx = 0
    l_idx = 0
    while len(mixed) < len(questions):
        if s_idx < len(seed_list):
            mixed.append(seed_list[s_idx])
            s_idx += 1
        if l_idx < len(llm_list) and (len(mixed) % llm_interval == 0 or s_idx >= len(seed_list)):
            mixed.append(llm_list[l_idx])
            l_idx += 1
    mixed = mixed[: body.count]
    final_seed_count = len([x for x in mixed if x.source == "seed"])
    final_ai_count = len([x for x in mixed if x.source == "llm"])
    base_ai_count = max(1, body.count // JD_BASE_AI_RATIO_EVERY)
    final_boosted = final_ai_count > base_ai_count
    final_reason = ai_reason if final_boosted else "normal_base_ratio"

    paper_id: Optional[str] = None
    if body.session_id and sess is not None:
        sid = str(body.session_id).strip()
        paper_meta = {
            "seed_count": final_seed_count,
            "ai_count": final_ai_count,
            "ai_ratio": round(final_ai_count / max(1, len(mixed)), 4),
            "ai_ratio_boosted": final_boosted,
            "ai_ratio_reason": final_reason,
            "seen_ratio_in_candidates": round(seen_ratio, 4),
            "unseen_candidate_count": unseen_count,
            "weak_topics_used": list(weak_topics),
            "topic_priority": list(topic_priority),
            "baseline_window": baseline_window,
            "topic_level_plan": dict(recommended_by_topic),
            "adjustment_reasons": list(adjustment_reasons),
            "jd_plan_mode": "planner_selector",
            "planner_notes": list(planner_notes),
            "selector_notes": selector_notes,
            "selector_candidate_count": len(candidate_items),
            "program_fixes": list(program_fixes),
        }
        paper_id = create_paper(
            sid,
            source="jd_rag_mix",
            difficulty=body.difficulty,
            question_count=len(mixed),
            meta=paper_meta,
        )
        for at in attempts_to_append:
            at["paper_id"] = paper_id
            append_attempt(sid, at)

    return GeneratePaperFromJdResponse(
        paper_id=paper_id,
        questions=mixed,
        meta=PaperBuildMeta(
            seed_count=final_seed_count,
            ai_count=final_ai_count,
            ai_ratio=round(final_ai_count / max(1, len(mixed)), 4),
            ai_ratio_boosted=final_boosted,
            ai_ratio_reason=final_reason,
            seen_ratio_in_candidates=round(seen_ratio, 4),
            unseen_candidate_count=unseen_count,
            weak_topics_used=list(weak_topics),
            topic_priority=list(topic_priority),
            baseline_window=baseline_window,
            topic_level_plan=dict(recommended_by_topic),
            adjustment_reasons=list(adjustment_reasons),
            jd_plan_mode="planner_selector",
            planner_notes=list(planner_notes),
            selector_notes=selector_notes,
            selector_candidate_count=len(candidate_items),
            program_fixes=list(program_fixes),
        ),
    )


def _parse_eval_json(content: str) -> Dict[str, Any]:
    return json.loads(content)


def _extract_eval_payload(
    data: Dict[str, Any],
) -> Tuple[int, List[str], List[str], str, List[str], List[str]]:
    """从评卷 JSON 提取字段并做基本规范化。"""
    try:
        score = int(data["score"])
        strengths = [str(x) for x in list(data["strengths"])]
        missing = [str(x) for x in list(data["missing_points"])]
        improved = str(data["improved_answer"])
        weak_raw = data.get("weak_topics", [])
        weak_topics = [str(x).strip().lower() for x in list(weak_raw) if str(x).strip()]
        study_raw = data.get("study_topics", [])
        study_topics = [str(x).strip() for x in list(study_raw) if str(x).strip()]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"模型 JSON 字段不完整: {e}") from e
    if score < 0 or score > 10:
        raise HTTPException(status_code=502, detail="score 必须在 0–10")
    if not improved.strip():
        raise HTTPException(status_code=502, detail="improved_answer 不能为空")
    return score, strengths, missing, improved, weak_topics, study_topics


def _session_baseline_text(sess: PracticeSession) -> str:
    """会话内薄弱频次与最近作答摘要，供 Tutor 提示词使用。"""
    parts: List[str] = []
    if sess.weakness_counts:
        top = sorted(sess.weakness_counts.items(), key=lambda x: -x[1])[:10]
        parts.append(
            "薄弱频次（topic -> 次数）: "
            + ", ".join(f"{k}:{v}" for k, v in top)
        )
    if sess.attempts:
        last = sess.attempts[-1]
        topics = last.get("topics") or []
        parts.append(
            f"最近一题: 难度 {last.get('difficulty')}, 标签 {','.join(str(t) for t in topics)}, "
            f"得分 {last.get('score')}"
        )
    return "\n".join(parts) if parts else "(尚无练习记录)"


def _last_attempt_summary(sess: PracticeSession) -> str:
    """最近一次题目的题干摘要与薄弱点，可能为空。"""
    if not sess.attempts:
        return "(无)"
    a = sess.attempts[-1]
    qt = str(a.get("question_text") or "").strip()
    if len(qt) > 800:
        qt = qt[:800] + "…"
    wt = a.get("weak_topics") or []
    sc = a.get("score")
    return (
        f"题干摘要:\n{qt or '(无题干存档)'}\n"
        f"得分: {sc}\n薄弱: {', '.join(str(x) for x in wt)}"
    )


def _resolve_weak_topic(sess: PracticeSession, weak_topic: str) -> str:
    w = str(weak_topic or "").strip()
    if w:
        return w
    if sess.weakness_counts:
        return max(sess.weakness_counts.items(), key=lambda x: x[1])[0]
    return "通用技术面试基础"


async def _run_tutor_json_llm(
    *, system: str, user: str, temperature: float = 0.35
) -> Dict[str, Any]:
    """Tutor 类接口：JSON 输出。"""
    model = "gpt-4o-mini"
    completion = await _get_openai().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"模型返回非合法 JSON: {e}") from e


def _extract_learning_plan_payload(
    data: Dict[str, Any],
    *,
    expected_days: int,
) -> TutorLearningPlanResponse:
    try:
        title = str(data["plan_title"])
        guess_md = str(data["jd_priority_guess_markdown"])
        raw_days = list(data["days"])
        tips_raw = data.get("tips", [])
        tips = [str(x).strip() for x in list(tips_raw) if str(x).strip()]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"学习计划 JSON 不完整: {e}") from e
    if not title.strip():
        raise HTTPException(status_code=502, detail="plan_title 不能为空")
    if not guess_md.strip():
        raise HTTPException(status_code=502, detail="jd_priority_guess_markdown 不能为空")
    days_out: List[TutorPlanDay] = []
    for d in raw_days:
        try:
            day_n = int(d["day"])
            focus = str(d["focus"])
            tasks_raw = list(d["tasks"])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(status_code=502, detail=f"学习计划 days 项无效: {e}") from e
        tasks: List[TutorPlanTask] = []
        for t in tasks_raw:
            try:
                task_s = str(t["task"])
                mins = int(t["estimated_minutes"])
            except (KeyError, TypeError, ValueError) as e:
                raise HTTPException(
                    status_code=502, detail=f"学习计划 task 无效: {e}"
                ) from e
            mins = max(5, min(180, mins))
            tasks.append(TutorPlanTask(task=task_s, estimated_minutes=mins))
        days_out.append(TutorPlanDay(day=day_n, focus=focus, tasks=tasks))
    days_out.sort(key=lambda x: x.day)
    if len(days_out) != expected_days:
        raise HTTPException(
            status_code=502,
            detail=f"学习计划天数不符：请求 {expected_days} 天，模型返回 {len(days_out)} 天",
        )
    day_nums = [d.day for d in days_out]
    if sorted(set(day_nums)) != list(range(1, expected_days + 1)):
        raise HTTPException(
            status_code=502,
            detail="days 的 day 须为 1..plan_days 且无重复",
        )
    return TutorLearningPlanResponse(
        plan_title=title,
        jd_priority_guess_markdown=guess_md,
        days=days_out,
        tips=tips,
    )


def _extract_tutor_chat_payload(data: Dict[str, Any]) -> TutorChatResponse:
    try:
        reply = str(data["reply_markdown"])
        sug_raw = data.get("suggested_followups", [])
        sug = [str(x).strip() for x in list(sug_raw) if str(x).strip()]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"Tutor 对话 JSON 不完整: {e}") from e
    if not reply.strip():
        raise HTTPException(status_code=502, detail="reply_markdown 不能为空")
    return TutorChatResponse(reply_markdown=reply, suggested_followups=sug[:5])


async def _run_evaluation_llm(
    *,
    req_topics: List[str],
    difficulty: str,
    question: str,
    student_answer: str,
    reference_block: str,
    key_points_block: str,
) -> Dict[str, Any]:
    """调用评卷模型并解析 JSON。"""
    user_prompt = build_evaluation_user_prompt(
        topics=sorted(req_topics),
        difficulty=difficulty,
        question=question,
        student_answer=student_answer,
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
        return _parse_eval_json(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"模型返回非合法 JSON: {e}") from e


@app.post("/evaluate-answer", response_model=EvaluateAnswerResponse)
async def evaluate_answer(body: EvaluateAnswerRequest) -> EvaluateAnswerResponse:
    req_topics = _normalize_request_topics(body.topics)
    if body.difficulty not in ALLOWED_DIFFICULTY:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty 必须是以下之一: {', '.join(sorted(ALLOWED_DIFFICULTY))}",
        )

    if body.generation_id:
        return await _evaluate_llm_question(body, req_topics)

    return await _evaluate_seed_question(body, req_topics)


async def _evaluate_seed_question(
    body: EvaluateAnswerRequest, req_topics: List[str]
) -> EvaluateAnswerResponse:
    """真题：本题 canonical 评卷。"""
    qid = body.question_id
    assert qid is not None
    canonical = _item_by_id(qid)
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

    ordered: List[Dict[str, Any]] = [canonical]
    ref_lines = [_snippet_from_item(it).content for it in ordered]
    key_points_union: List[str] = []
    for it in ordered:
        _extend_key_points_union(key_points_union, it)
    evidence = [_snippet_from_item(it) for it in ordered]
    reference_block = "\n\n---\n\n".join(ref_lines)
    key_points_block = "\n".join(f"- {p}" for p in key_points_union[:30])

    data = await _run_evaluation_llm(
        req_topics=req_topics,
        difficulty=body.difficulty,
        question=body.question,
        student_answer=body.student_answer,
        reference_block=reference_block,
        key_points_block=key_points_block,
    )
    score, strengths, missing, improved, weak_topics, study_topics = _extract_eval_payload(
        data
    )
    if body.session_id and str(body.session_id).strip():
        sid = str(body.session_id).strip()
        record_weak_topics(sid, weak_topics)
        update_attempt_result(
            sid,
            question_id=body.question_id,
            generation_id=None,
            score=score,
            weak_topics=weak_topics,
        )
    return EvaluateAnswerResponse(
        score=score,
        strengths=strengths,
        missing_points=missing,
        improved_answer=improved,
        weak_topics=weak_topics,
        study_topics=study_topics,
        reference_evidence=evidence,
    )


async def _evaluate_llm_question(
    body: EvaluateAnswerRequest, req_topics: List[str]
) -> EvaluateAnswerResponse:
    """AI 题：按快照题干与出题要点、参考种子片段评卷。"""
    gid = body.generation_id
    assert gid is not None
    snap = get_snapshot(gid)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail="无效的 generation_id，请重新生成题目（服务端重启会清空快照）。",
        )
    if snap.question.strip() != body.question.strip():
        raise HTTPException(status_code=400, detail="question 与出题快照不一致，请勿篡改题干。")
    if snap.difficulty.strip() != body.difficulty.strip():
        raise HTTPException(status_code=400, detail="difficulty 与出题快照不一致。")
    req_set = set(req_topics)
    if not (set(snap.topics) & req_set):
        raise HTTPException(
            status_code=400,
            detail="请求中的 topics 与出题标签无交集，请使用出题时相同的筛选标签。",
        )

    ordered: List[Dict[str, Any]] = []
    for sid in snap.source_seed_ids:
        it = _item_by_id(sid)
        if it is not None:
            ordered.append(it)
    ref_lines = [_snippet_from_item(it).content for it in ordered]
    reference_block = (
        "\n\n---\n\n".join(ref_lines)
        if ref_lines
        else "(无种子参考片段；请依据下列要点与通用技术知识评卷。)"
    )
    key_points_block = "\n".join(f"- {p}" for p in snap.expected_key_points[:30])
    evidence = [_snippet_for_seed_item(it) for it in ordered]

    data = await _run_evaluation_llm(
        req_topics=req_topics,
        difficulty=body.difficulty,
        question=body.question,
        student_answer=body.student_answer,
        reference_block=reference_block,
        key_points_block=key_points_block,
    )
    score, strengths, missing, improved, weak_topics, study_topics = _extract_eval_payload(
        data
    )
    if body.session_id and str(body.session_id).strip():
        sid = str(body.session_id).strip()
        record_weak_topics(sid, weak_topics)
        update_attempt_result(
            sid,
            question_id=None,
            generation_id=body.generation_id,
            score=score,
            weak_topics=weak_topics,
        )
    return EvaluateAnswerResponse(
        score=score,
        strengths=strengths,
        missing_points=missing,
        improved_answer=improved,
        weak_topics=weak_topics,
        study_topics=study_topics,
        reference_evidence=evidence,
    )


@app.post(
    "/sessions/{session_id}/tutor/learning-plan",
    response_model=TutorLearningPlanResponse,
)
async def tutor_learning_plan(
    session_id: str, body: TutorLearningPlanRequest
) -> TutorLearningPlanResponse:
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="未知的 session_id。")
    weak = _resolve_weak_topic(sess, body.weak_topic)
    plan_days = int(body.plan_days)
    user_prompt = build_tutor_learning_plan_user(
        jd_text=body.jd_text.strip(),
        weak_topic=weak,
        session_baseline=_session_baseline_text(sess),
        last_question_meta=_last_attempt_summary(sess),
        plan_days=plan_days,
    )
    raw = await _run_tutor_json_llm(
        system=TUTOR_LEARNING_PLAN_SYSTEM,
        user=user_prompt,
        temperature=0.5,
    )
    return _extract_learning_plan_payload(raw, expected_days=plan_days)


@app.post("/sessions/{session_id}/tutor/chat", response_model=TutorChatResponse)
async def tutor_chat(session_id: str, body: TutorChatRequest) -> TutorChatResponse:
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="未知的 session_id。")
    for turn in body.history:
        r = str(turn.role or "").strip().lower()
        if r not in ("user", "assistant"):
            raise HTTPException(
                status_code=400, detail="history 中 role 只能是 user 或 assistant",
            )
    hist_payload: List[Dict[str, str]] = [
        {"role": str(t.role).strip().lower(), "content": str(t.content)}
        for t in body.history
    ]
    if len(hist_payload) > 24:
        hist_payload = hist_payload[-24:]
    jd_line = (body.jd_text or "").strip() or "(本次未提供 JD)"
    if body.use_knowledge_rag and knowledge_rag.ready:
        rewrite_result = await rewrite_query_with_llm(
            _get_openai(),
            conversation_history=hist_payload,
            current_query=body.user_message.strip(),
            locale_mode=body.locale_mode,
            model=QUERY_REWRITE_MODEL,
        )
        # 多意图优先拆分检索，其他类型按单条改写查询检索。
        retrieval_queries = (
            rewrite_result.sub_queries
            if rewrite_result.query_type == "multi_intent" and rewrite_result.sub_queries
            else [rewrite_result.rewritten_query]
        )
        docs_all = []
        for q in retrieval_queries:
            docs_all.extend(await knowledge_rag.retrieve(q, top_k=body.top_k))
        # 以 metadata + 内容片段去重，控制 stuff 上下文规模。
        dedup_docs = []
        seen_doc_keys: Set[str] = set()
        for d in docs_all:
            md = d.metadata or {}
            k = (
                f"{md.get('corpus_id', '')}:{md.get('doc_id', '')}:"
                f"{md.get('title', '')}:{d.page_content[:80]}"
            )
            if k in seen_doc_keys:
                continue
            seen_doc_keys.add(k)
            dedup_docs.append(d)
            if len(dedup_docs) >= body.top_k:
                break
        answer_markdown, cites_raw = await knowledge_rag.answer_with_stuff(
            query=rewrite_result.rewritten_query,
            docs=dedup_docs,
            answer_language=rewrite_result.language,
        )
        citations = [TutorCitation(**c) for c in cites_raw]
        return TutorChatResponse(
            reply_markdown=answer_markdown,
            suggested_followups=[],
            citations=citations,
            query_type=rewrite_result.query_type,
            rewritten_query=rewrite_result.rewritten_query,
            rewrite_confidence=rewrite_result.confidence,
        )

    user_prompt = build_tutor_chat_user(
        jd_text=jd_line,
        weak_topic=_resolve_weak_topic(sess, body.weak_topic),
        session_baseline=_session_baseline_text(sess),
        chat_history_json=json.dumps(hist_payload, ensure_ascii=False),
        user_message=body.user_message.strip(),
    )
    raw = await _run_tutor_json_llm(system=TUTOR_CHAT_SYSTEM, user=user_prompt)
    return _extract_tutor_chat_payload(raw)
