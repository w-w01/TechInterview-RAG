"""InterviewMate FastAPI 入口：健康检查、练习会话、随机/AI 出题、JD 向量组卷、本题锚定评卷。"""

import json
import logging
import os
import random
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from .data_loader import load_interview_seed
from .embedding_index import seed_embedding_index
from .generation_store import GenerationSnapshot, get_snapshot, put_snapshot
from .prompts import (
    EVALUATION_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    build_evaluation_user_prompt,
    build_generation_user_prompt,
)
from .rag import RAGService, _item_topic_slugs
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
    NextPaperPlanResponse,
    PracticeAttemptEntry,
    PracticePaperEntry,
    ReferenceSnippet,
    SessionDetailResponse,
    TopicEntry,
    TopicsListResponse,
)
from .session_store import (
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


def _pick_topic_items_with_random_difficulty(
    *,
    topic: str,
    ranked: List[Dict[str, Any]],
    target_diff: str,
    desired_count: int,
    used_ids: Set[str],
    answered_seed_ids: Set[str],
) -> List[Dict[str, Any]]:
    """
    在某 topic 下按随机难度分布选题：
    - 70% 目标难度
    - 20% 邻近较低
    - 10% 邻近较高
    并跳过已答过与已使用题。
    """
    out: List[Dict[str, Any]] = []
    if desired_count <= 0:
        return out
    td = _clamp_difficulty(target_diff)
    lower = _bump_difficulty(td, -1)
    upper = _bump_difficulty(td, +1)
    topic_pool = [
        it
        for it in ranked
        if topic in _topics_sorted_from_item(it)
        and str(it.get("id", "")).strip() not in answered_seed_ids
        and str(it.get("id", "")).strip() not in used_ids
    ]
    random.shuffle(topic_pool)
    for _ in range(desired_count):
        roll = random.random()
        want = td if roll < 0.7 else (lower if roll < 0.9 else upper)
        hit = next(
            (
                it
                for it in topic_pool
                if str(it.get("difficulty", "")).strip() == want
                and str(it.get("id", "")).strip() not in used_ids
            ),
            None,
        )
        if hit is None:
            hit = next(
                (
                    it
                    for it in topic_pool
                    if str(it.get("id", "")).strip() not in used_ids
                ),
                None,
            )
        if hit is None:
            break
        out.append(hit)
        used_ids.add(str(hit.get("id", "")).strip())
    return out


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
    if sess.papers:
        last_meta = sess.papers[-1].get("meta") or {}
        topic_priority = [str(x) for x in (last_meta.get("topic_priority") or [])]
    if not topic_priority:
        ranked_stub = _seed_items[:120] if _seed_items else []
        topic_priority = _topic_priority_from_ranked(ranked_stub, weakness)
    rec_map, reasons = _recommended_difficulty_by_topic(topic_baseline)
    if not reasons:
        reasons.append("暂无连续偏离，维持主难度并保留随机性")
    return NextPaperPlanResponse(
        session_id=sid,
        baseline_window=baseline_window,
        topic_priority=topic_priority,
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


@app.post("/generate-paper-from-jd", response_model=GeneratePaperFromJdResponse)
async def generate_paper_from_jd(
    body: GeneratePaperFromJdRequest,
) -> GeneratePaperFromJdResponse:
    """JD 纯文本嵌入后组卷：首卷覆盖多难度，后续按最近3卷topic基线自适应。"""
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
    topic_priority = _topic_priority_from_ranked(ranked, dict(sess.weakness_counts) if sess else {})
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
    # 首卷：覆盖多难度与多topic；后续：按topic基线调节
    used_ids: Set[str] = set()
    seed_picked: List[Dict[str, Any]] = []
    has_history = bool(topic_baseline) and body.auto_adapt
    if not has_history:
        # 覆盖型策略：难度轮询 + topic优先轮询
        if not topic_priority:
            topic_priority = sorted({t for it in seed_candidates for t in _topics_sorted_from_item(it)})
        diff_cycle: List[str] = []
        for i in range(seed_count):
            diff_cycle.append(_DIFF_ORDER[i % len(_DIFF_ORDER)] if body.auto_adapt else body.difficulty)
        topic_idx = 0
        for d in diff_cycle:
            desired_topic = topic_priority[topic_idx % len(topic_priority)] if topic_priority else ""
            topic_idx += 1
            hit = next(
                (
                    it
                    for it in seed_candidates
                    if str(it.get("id", "")).strip() not in used_ids
                    and str(it.get("difficulty", "")).strip() == d
                    and (not desired_topic or desired_topic in _topics_sorted_from_item(it))
                ),
                None,
            )
            if hit is None:
                hit = next(
                    (
                        it
                        for it in seed_candidates
                        if str(it.get("id", "")).strip() not in used_ids
                        and str(it.get("difficulty", "")).strip() == d
                    ),
                    None,
                )
            if hit is None:
                hit = next(
                    (
                        it
                        for it in seed_candidates
                        if str(it.get("id", "")).strip() not in used_ids
                    ),
                    None,
                )
            if hit is None:
                break
            used_ids.add(str(hit.get("id", "")).strip())
            seed_picked.append(hit)
    else:
        # 自适应策略：按 topic_priority 分配，并按推荐难度+随机性抽取
        if not topic_priority:
            topic_priority = sorted(topic_baseline.keys())
        if not topic_priority:
            topic_priority = sorted({t for it in seed_candidates for t in _topics_sorted_from_item(it)})
        if not topic_priority:
            seed_picked = seed_candidates[:seed_count]
        else:
            per_topic = max(1, seed_count // len(topic_priority))
            for tp in topic_priority:
                target = recommended_by_topic.get(tp, body.difficulty)
                picked = _pick_topic_items_with_random_difficulty(
                    topic=tp,
                    ranked=seed_candidates,
                    target_diff=target,
                    desired_count=per_topic,
                    used_ids=used_ids,
                    answered_seed_ids=answered_seed_ids,
                )
                seed_picked.extend(picked)
                if len(seed_picked) >= seed_count:
                    break
            if len(seed_picked) < seed_count:
                for it in seed_candidates:
                    iid = str(it.get("id", "")).strip()
                    if not iid or iid in used_ids:
                        continue
                    used_ids.add(iid)
                    seed_picked.append(it)
                    if len(seed_picked) >= seed_count:
                        break
    seed_picked = seed_picked[:seed_count]

    questions: List[PaperQuestion] = []
    attempts_to_append: List[Dict[str, Any]] = []
    for it in seed_picked:
        q = _item_to_generate_question_response(it, body.difficulty)
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

    # AI 题以「补弱优先」采样：若有薄弱点，优先从命中薄弱关键词的种子中抽样。
    weak_ranked = [it for it in ranked if _weak_score_for_item(it, weak_topics) > 0]
    ai_sample_pool = weak_ranked if weak_ranked else ranked
    for _ in range(ai_count):
        built = False
        for _retry in range(3):
            samples = rag.sample_pool_items(ai_sample_pool, 3)
            if not samples:
                samples = rag.sample_pool_items(ranked, 3)
            sample_topics: List[str] = []
            for it in samples:
                for slug in _topics_sorted_from_item(it):
                    if slug not in sample_topics:
                        sample_topics.append(slug)
            try:
                paper_q, attempt = await _generate_llm_question_from_samples(
                    topics=sample_topics,
                    difficulty=body.difficulty,
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
            q = _item_to_generate_question_response(fallback, body.difficulty)
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

    paper_id: Optional[str] = None
    if body.session_id and sess is not None:
        sid = str(body.session_id).strip()
        paper_meta = {
            "seed_count": len([x for x in mixed if x.source == "seed"]),
            "ai_count": len([x for x in mixed if x.source == "llm"]),
            "ai_ratio": round(
                len([x for x in mixed if x.source == "llm"]) / max(1, len(mixed)), 4
            ),
            "ai_ratio_boosted": final_boosted,
            "ai_ratio_reason": final_reason,
            "seen_ratio_in_candidates": round(seen_ratio, 4),
            "unseen_candidate_count": unseen_count,
            "weak_topics_used": list(weak_topics),
            "topic_priority": list(topic_priority),
            "baseline_window": baseline_window,
            "topic_level_plan": dict(recommended_by_topic),
            "adjustment_reasons": list(adjustment_reasons),
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

    final_seed_count = len([x for x in mixed if x.source == "seed"])
    final_ai_count = len([x for x in mixed if x.source == "llm"])
    base_ai_count = max(1, body.count // JD_BASE_AI_RATIO_EVERY)
    final_boosted = final_ai_count > base_ai_count
    final_reason = ai_reason if final_boosted else "normal_base_ratio"
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
        ),
    )


def _parse_eval_json(content: str) -> Dict[str, Any]:
    return json.loads(content)


def _extract_eval_payload(data: Dict[str, Any]) -> Tuple[int, List[str], List[str], str, List[str]]:
    """从评卷 JSON 提取字段并做基本规范化。"""
    try:
        score = int(data["score"])
        strengths = [str(x) for x in list(data["strengths"])]
        missing = [str(x) for x in list(data["missing_points"])]
        improved = str(data["improved_answer"])
        weak_raw = data.get("weak_topics", [])
        weak_topics = [str(x).strip().lower() for x in list(weak_raw) if str(x).strip()]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"模型 JSON 字段不完整: {e}") from e
    if score < 0 or score > 10:
        raise HTTPException(status_code=502, detail="score 必须在 0–10")
    if not improved.strip():
        raise HTTPException(status_code=502, detail="improved_answer 不能为空")
    return score, strengths, missing, improved, weak_topics


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
    score, strengths, missing, improved, weak_topics = _extract_eval_payload(data)
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
    score, strengths, missing, improved, weak_topics = _extract_eval_payload(data)
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
        reference_evidence=evidence,
    )
