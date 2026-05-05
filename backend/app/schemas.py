"""API 请求与响应的 Pydantic 模型定义。"""

from typing import List, Optional

from pydantic import BaseModel, Field


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


class GenerateQuestionResponse(BaseModel):
    question_id: str
    question: str
    topics: List[str] = Field(..., description="本题在题库中的全部 topic slug")
    difficulty: str
    expected_key_points: List[str]
    reference_snippets: List[ReferenceSnippet]


class EvaluateAnswerRequest(BaseModel):
    """评卷须带 question_id；topics 为本次练习筛选条件，须与题目标签有交集。"""

    question_id: str = Field(..., description="与种子条目中 id 一致，通常来自 /generate-question")
    question: str
    student_answer: str
    topics: List[str] = Field(..., min_length=1)
    difficulty: str


class EvaluateAnswerResponse(BaseModel):
    score: int = Field(..., ge=0, le=10)
    strengths: List[str]
    missing_points: List[str]
    improved_answer: str
    reference_evidence: List[ReferenceSnippet] = Field(
        ...,
        description="本题题库条目对应的引用片段（无向量检索扩充）。",
    )


class HealthResponse(BaseModel):
    status: str
    rag_index_ready: bool = Field(
        ...,
        description="题库已成功加载且条目非空（本版本无向量索引）。",
    )
    seed_items: int
    message: Optional[str] = None
