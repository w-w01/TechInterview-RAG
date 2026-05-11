"""API 请求与响应的 Pydantic 模型定义。"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    study_topics: List[str] = Field(
        default_factory=list,
        description="后续学习与 Tutor 建议方向（中文短句）。",
    )
    reference_evidence: List[ReferenceSnippet] = Field(
        ...,
        description="真题为单条 canonical；AI 题可为多条种子参考片段。",
    )


# --- AI Tutor（学习计划与对话） ---


class TutorLearningPlanRequest(BaseModel):
    jd_text: str = Field(..., min_length=40)
    weak_topic: str = ""
    plan_days: int = Field(
        5,
        ge=1,
        le=14,
        description="用户希望多少天内完成本计划；模型输出的 days 长度须与此一致。",
    )


class TutorPlanTask(BaseModel):
    task: str
    estimated_minutes: int = Field(..., ge=5, le=240)


class TutorPlanDay(BaseModel):
    day: int = Field(..., ge=1)
    focus: str
    tasks: List[TutorPlanTask]


class TutorLearningPlanResponse(BaseModel):
    plan_title: str
    jd_priority_guess_markdown: str = Field(
        ...,
        description="基于 JD 的侧重点与考查重心推断（Markdown）。",
    )
    days: List[TutorPlanDay]
    tips: List[str]


class TutorChatTurn(BaseModel):
    role: str = Field(..., description="user 或 assistant")
    content: str


class TutorChatRequest(BaseModel):
    jd_text: str = Field("", description="可为空；空则提示词中标注未提供 JD。")
    weak_topic: str = ""
    locale_mode: str = Field(
        "auto",
        description="答复语言模式：auto / zh / en / mixed。",
    )
    use_knowledge_rag: bool = Field(
        True,
        description="是否启用知识库检索问答链路。",
    )
    top_k: int = Field(
        6,
        ge=1,
        le=20,
        description="知识库检索召回条数。",
    )
    corpus_id: str = Field(
        "",
        description="可选；限定知识库子库（如 advanced_java），空表示全库。",
    )
    history: List[TutorChatTurn] = Field(
        default_factory=list,
        description="不含本轮用户消息的既往对话。",
    )
    user_message: str = Field(..., min_length=1)

    @field_validator("locale_mode", mode="before")
    @classmethod
    def normalize_locale_mode(cls, v: Any) -> str:
        s = str(v or "").strip().lower() or "auto"
        if s not in ("auto", "zh", "en", "mixed"):
            raise ValueError("locale_mode 只能是 auto / zh / en / mixed")
        return s


class TutorCitation(BaseModel):
    """Tutor 知识库引用信息。"""

    source: str
    title: str
    corpus_id: str
    doc_id: str
    lang: str = ""


class TutorChatResponse(BaseModel):
    reply_markdown: str
    suggested_followups: List[str] = Field(default_factory=list)
    citations: List[TutorCitation] = Field(default_factory=list)
    query_type: Optional[str] = None
    rewritten_query: Optional[str] = None
    retrieval_queries: List[str] = Field(default_factory=list)
    retrieved_chunks: int = 0
    rewrite_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class KnowledgeSearchRequest(BaseModel):
    """知识库检索调试请求。"""

    query: str = Field(..., min_length=1)
    top_k: int = Field(6, ge=1, le=20)
    corpus_id: str = Field(
        "",
        description="可选；与 Tutor 一致，限定子库。",
    )


class KnowledgeSearchHit(BaseModel):
    """知识库检索命中项。"""

    score: Optional[float] = None
    source: str
    title: str
    corpus_id: str
    doc_id: str
    lang: str = ""
    snippet: str


class KnowledgeSearchResponse(BaseModel):
    """知识库检索调试响应。"""

    query: str
    hit_count: int
    hits: List[KnowledgeSearchHit] = Field(default_factory=list)


class GeneratePaperFromJdRequest(BaseModel):
    """根据 JD 纯文本：向量检索候选 → LLM 规划 topic → LLM 从候选中选真题并规划 AI 槽位。"""

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
    jd_plan_mode: str = Field(
        "planner_selector",
        description="JD 组卷策略标识：planner_selector 为 LLM 规划 topic + LLM 选题。",
    )
    planner_notes: List[str] = Field(
        default_factory=list,
        description="Planner 对 topic 排序的简短说明。",
    )
    selector_notes: str = Field(
        "",
        description="Selector 组卷思路说明。",
    )
    selector_candidate_count: int = Field(
        0,
        description="送入 Selector 的候选真题条数。",
    )
    program_fixes: List[str] = Field(
        default_factory=list,
        description="程序对 Selector 输出做的校验与修正说明。",
    )


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
    knowledge_rag_ready: bool = Field(
        ...,
        description="Tutor 知识库 RAG 索引是否已构建。",
    )
    knowledge_rag_chunks: int = Field(
        0,
        description="知识库 RAG 的分块数量。",
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
    topic_priority_source: str = Field(
        "",
        description="last_paper_meta | seed_frequency_weakness_stub，见 topic_priority_explanation。",
    )
    topic_priority_explanation: str = Field(
        "",
        description="人类可读：topic_priority 来自上一张卷 meta 还是题库 stub，避免与 JD Planner 混淆。",
    )
    topic_baseline: dict[str, Any] = Field(default_factory=dict)
    recommended_difficulty_by_topic: dict[str, str] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)


# --- 知识库文档摄入（n8n 等；不落向量、不分块） ---


class KnowledgeDocumentSource(BaseModel):
    """文档来源元数据。"""

    type: str = Field(..., description="例如 github")
    url: str
    license_note: str = ""


class KnowledgeDocumentExtra(BaseModel):
    """流水线附加字段（均可选，便于不同上游）。"""

    original_filename: Optional[str] = None
    original_path: Optional[str] = None
    github_sha: Optional[str] = None
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    cleaning_version: Optional[str] = None


class KnowledgeDocumentIngestRequest(BaseModel):
    """POST /knowledge/documents 请求体（与 n8n 约定 JSON 对齐）。"""

    record_type: str = Field("document", description="须为 document")
    doc_id: str
    title: str
    body: str
    body_format: str = Field("markdown", description="当前仅支持 markdown")
    lang: str = "en"
    source: KnowledgeDocumentSource
    corpus_id: str
    topic_slugs: List[str] = Field(default_factory=list)
    extra: KnowledgeDocumentExtra = Field(default_factory=KnowledgeDocumentExtra)

    @field_validator("corpus_id", "doc_id", mode="before")
    @classmethod
    def strip_path_segments(cls, v: Any) -> Any:
        """去除首尾空白，与落盘路径段一致。"""
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def validate_record_and_format(self) -> "KnowledgeDocumentIngestRequest":
        if str(self.record_type).strip() != "document":
            raise ValueError("record_type 必须为 document")
        if str(self.body_format).strip().lower() != "markdown":
            raise ValueError("body_format 当前仅支持 markdown")
        return self


class KnowledgeDocumentIngestResponse(BaseModel):
    """摄入成功后的简要回执。"""

    corpus_id: str
    doc_id: str
    saved_path: str = Field(..., description="相对 backend 目录的 POSIX 路径")
    overwritten: bool = False
