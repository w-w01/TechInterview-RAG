"""API 请求与响应的 Pydantic 模型定义。"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator


class ReferenceSnippet(BaseModel):
    """引用片段，用于问题生成与评估展示。"""

    source: str
    content: str


class TopicEntry(BaseModel):
    """外置白名单中的单条 topic（slug + 展示名）。"""

    slug: str
    label: str


class TopicsListResponse(BaseModel):
    topics: List[TopicEntry]


class GenerateQuestionRequest(BaseModel):
    """选题：topics 为 slug 列表，与题库条目标签求交集（OR）后按难度抽题。"""

    topics: List[str] = Field(..., min_length=1)
    difficulty: str = Field(..., description="beginner / intermediate / advanced")
    session_id: Optional[str] = Field(
        None,
        description="可选；若提供则在本会话中记录本次出题。",
    )


class GenerateQuestionResponse(BaseModel):
    question_id: str
    question: str
    topics: List[str] = Field(..., description="本题在题库中的全部 topic slug")
    difficulty: str
    expected_key_points: List[str]
    reference_snippets: List[ReferenceSnippet]


class GenerateLlmQuestionRequest(BaseModel):
    """AI 出题：结构化池内随机抽样至多 reference_max 条作少样本参考；池空则零样本。"""

    topics: List[str] = Field(..., min_length=1)
    difficulty: str = Field(..., description="beginner / intermediate / advanced")
    reference_max: int = Field(
        5,
        ge=0,
        le=12,
        description="少样本参考条数上限；0 表示不要求参考条数（仍受池大小限制）。",
    )
    session_id: Optional[str] = Field(
        None,
        description="可选；若提供则在本会话中记录本次出题。",
    )


class GenerateLlmQuestionResponse(BaseModel):
    generation_id: str
    question: str
    topics: List[str] = Field(..., description="出题请求中的筛选标签（排序后）")
    difficulty: str
    expected_key_points: List[str]
    reference_snippets: List[ReferenceSnippet] = Field(
        ...,
        description="本次抽样用作少样本上下文的种子片段。",
    )
    source_seed_ids: List[str] = Field(
        ...,
        description="本次抽样的种子 id 列表；池空时为空数组。",
    )


class EvaluateAnswerRequest(BaseModel):
    """评卷：真题带 question_id；AI 题带 generation_id，二者互斥。"""

    question: str
    student_answer: str
    topics: List[str] = Field(..., min_length=1)
    difficulty: str
    question_id: Optional[str] = Field(
        None,
        description="种子 id；与 /generate-question 返回一致。",
    )
    generation_id: Optional[str] = Field(
        None,
        description="AI 出题返回的 id；与 /generate-question-llm 一致。",
    )
    session_id: Optional[str] = Field(
        None,
        description="可选；用于将评卷识别出的薄弱知识点写回会话画像。",
    )

    @model_validator(mode="before")
    @classmethod
    def exactly_one_question_ref(cls, data: Any) -> Any:
        if isinstance(data, dict):
            q = (data.get("question_id") or "").strip()
            g = (data.get("generation_id") or "").strip()
            if bool(q) == bool(g):
                raise ValueError("必须且只能提供 question_id 或 generation_id 之一")
            data = {
                **data,
                "question_id": q or None,
                "generation_id": g or None,
            }
        return data


class EvaluateAnswerResponse(BaseModel):
    score: int = Field(..., ge=0, le=10)
    strengths: List[str]
    missing_points: List[str]
    improved_answer: str
    weak_topics: List[str] = Field(
        default_factory=list,
        description="评卷识别出的薄弱知识点，用于后续补弱出题。",
    )
    reference_evidence: List[ReferenceSnippet] = Field(
        ...,
        description="真题为单条 canonical；AI 题可为多条种子参考片段。",
    )


class GeneratePaperFromJdRequest(BaseModel):
    """根据 JD 纯文本在指定难度下量检索 Top-K 种子组卷（真题列表）。"""

    jd_text: str = Field(..., min_length=40, description="职位描述纯文本，过短则 400")
    difficulty: str = Field(..., description="beginner / intermediate / advanced")
    count: int = Field(5, ge=1, le=20, description="试卷题目数量上限")
    auto_adapt: bool = Field(
        True,
        description="是否按最近3卷表现做规则自适应；false 时按基础规则组卷。",
    )
    session_id: Optional[str] = Field(
        None,
        description="可选；当前组卷不写入会话，预留字段。",
    )


class GeneratePaperFromJdResponse(BaseModel):
    paper_id: Optional[str] = None
    questions: List["PaperQuestion"]
    meta: "PaperBuildMeta"


class PaperBuildMeta(BaseModel):
    """组卷解释元数据，便于前端展示与策略调试。"""

    seed_count: int
    ai_count: int
    ai_ratio: float
    ai_ratio_boosted: bool
    ai_ratio_reason: str = Field(
        ...,
        description="normal_base_ratio / high_seen_ratio / seed_shortage",
    )
    seen_ratio_in_candidates: float
    unseen_candidate_count: int
    weak_topics_used: List[str] = Field(default_factory=list)
    topic_priority: List[str] = Field(default_factory=list)
    baseline_window: int = 3
    topic_level_plan: dict[str, str] = Field(default_factory=dict)
    adjustment_reasons: List[str] = Field(default_factory=list)


class PaperQuestion(BaseModel):
    """JD 组卷返回条目：真题或 AI 题。"""

    source: str = Field(..., description="seed 或 llm")
    question_id: Optional[str] = None
    generation_id: Optional[str] = None
    question: str
    topics: List[str]
    difficulty: str
    expected_key_points: List[str]
    reference_snippets: List[ReferenceSnippet] = Field(default_factory=list)
    source_seed_ids: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    rag_index_ready: bool = Field(
        ...,
        description="题库已成功加载且条目非空。",
    )
    embedding_index_ready: bool = Field(
        ...,
        description="JD 组卷用种子向量索引是否已构建。",
    )
    seed_items: int
    message: Optional[str] = None


class CreateSessionResponse(BaseModel):
    """新建练习会话。"""

    session_id: str
    created_at: str


class PracticeAttemptEntry(BaseModel):
    """会话内一次出题记录。"""

    paper_id: Optional[str] = None
    source: str = Field(..., description="seed 或 llm")
    question_id: Optional[str] = None
    generation_id: Optional[str] = None
    topics: List[str]
    difficulty: str
    score: Optional[int] = None
    weak_topics: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class PracticePaperEntry(BaseModel):
    """会话内一张试卷的聚合记录。"""

    paper_id: str
    source: str
    difficulty: str
    question_count: int
    created_at: str
    meta: dict[str, Any] = Field(default_factory=dict)


class SessionDetailResponse(BaseModel):
    """查询会话（演示用）。"""

    session_id: str
    created_at: str
    papers: List[PracticePaperEntry] = Field(default_factory=list)
    attempts: List[PracticeAttemptEntry]
    seen_seed_ids: List[str] = Field(default_factory=list)
    weakness_counts: dict[str, int] = Field(default_factory=dict)


class NextPaperPlanResponse(BaseModel):
    """下一张卷的规则计划解释。"""

    session_id: str
    baseline_window: int
    topic_priority: List[str] = Field(default_factory=list)
    topic_baseline: dict[str, Any] = Field(default_factory=dict)
    recommended_difficulty_by_topic: dict[str, str] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
