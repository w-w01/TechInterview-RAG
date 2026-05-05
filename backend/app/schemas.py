"""API 请求与响应的 Pydantic 模型定义。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ReferenceSnippet(BaseModel):
    """引用片段，用于问题生成与评估展示。"""

    source: str
    content: str


class GenerateQuestionRequest(BaseModel):
    topic: str = Field(..., description="主题：Java / SQL / REST API / System Design / AI / RAG Basics")
    difficulty: str = Field(..., description="难度：beginner / intermediate / advanced")


class GenerateQuestionResponse(BaseModel):
    question_id: str
    question: str
    topic: str
    difficulty: str
    expected_key_points: List[str]
    reference_snippets: List[ReferenceSnippet]


class EvaluateAnswerRequest(BaseModel):
    """评卷须携带出题接口返回的 question_id，用于锚定题库条目与引用证据。"""

    question_id: str = Field(..., description="与种子条目中 id 一致，通常来自 /generate-question")
    question: str
    student_answer: str
    topic: str
    difficulty: str


class EvaluateAnswerResponse(BaseModel):
    score: int = Field(..., ge=0, le=10)
    strengths: List[str]
    missing_points: List[str]
    improved_answer: str
    reference_evidence: List[ReferenceSnippet]


class HealthResponse(BaseModel):
    status: str
    rag_index_ready: bool
    seed_items: int
    message: Optional[str] = None
