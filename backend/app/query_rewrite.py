"""Tutor Query 改写：预处理 + 语言路由 + 全 LLM 意图识别改写。"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List

from openai import AsyncOpenAI

REWRITE_SYSTEM_PROMPT = """你是查询改写专家。请根据用户当前问题与历史对话，识别查询类型并改写成适合知识库检索的查询。

可识别类型：
1. context_dependent（上下文依赖）
2. comparison（对比）
3. pronoun_ambiguous（模糊指代）
4. multi_intent（多意图）
5. rhetorical（反问）
6. direct（可直接检索）

要求：
- 必须输出 JSON 对象，不要 markdown 代码块。
- 字段：
  - query_type: 上述类型之一
  - rewritten_query: 字符串；multi_intent 时可为空
  - sub_queries: 字符串数组；仅 multi_intent 时建议返回 2-4 个子问题
  - confidence: 0-1 浮点数
- 改写要保留用户原意，不要扩写成无关问题。
- 若当前问题已足够清晰，query_type=direct，rewritten_query 直接返回原问题（可微调表达）。
"""


def _normalize_text(text: str) -> str:
    """做最小预处理，避免规则层承载语义判断。"""
    s = str(text or "").strip()
    s = re.sub(r"\s+", " ", s)
    # 中文全角问号/叹号统一，便于后续模型理解与日志比对
    s = s.replace("？", "?").replace("！", "!")
    return s


def detect_query_language(text: str, locale_mode: str) -> str:
    """检测查询语言，仅用于检索与回答语言路由。"""
    if locale_mode in ("zh", "en", "mixed"):
        return locale_mode
    s = str(text or "")
    if not s.strip():
        return "en"
    zh_cnt = len(re.findall(r"[\u4e00-\u9fff]", s))
    en_cnt = len(re.findall(r"[A-Za-z]", s))
    total = max(1, len(s))
    zh_ratio = zh_cnt / total
    en_ratio = en_cnt / total
    if zh_ratio >= 0.2 and en_ratio >= 0.2:
        return "mixed"
    if zh_ratio >= 0.2:
        return "zh"
    return "en"


@dataclass
class QueryRewriteResult:
    """改写输出标准结构。"""

    query_type: str
    rewritten_query: str
    sub_queries: List[str] = field(default_factory=list)
    confidence: float = 0.0
    language: str = "en"


async def rewrite_query_with_llm(
    client: AsyncOpenAI,
    *,
    conversation_history: List[Dict[str, str]],
    current_query: str,
    locale_mode: str = "auto",
    model: str = "gpt-4o-mini",
) -> QueryRewriteResult:
    """调用 LLM 做意图识别与改写。"""
    normalized_query = _normalize_text(current_query)
    history = []
    for turn in conversation_history[-12:]:
        role = str(turn.get("role", "")).strip().lower()
        if role not in ("user", "assistant"):
            continue
        content = _normalize_text(str(turn.get("content", "")))
        if not content:
            continue
        history.append({"role": role, "content": content})
    prompt = (
        "## 对话历史\n"
        f"{json.dumps(history, ensure_ascii=False)}\n\n"
        "## 当前问题\n"
        f"{normalized_query}\n\n"
        "## 输出\n"
        "请返回 JSON。"
    )
    completion = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw = completion.choices[0].message.content or "{}"
    data = json.loads(raw)
    query_type = str(data.get("query_type") or "direct").strip().lower()
    if query_type not in {
        "context_dependent",
        "comparison",
        "pronoun_ambiguous",
        "multi_intent",
        "rhetorical",
        "direct",
    }:
        query_type = "direct"
    rewritten_query = _normalize_text(str(data.get("rewritten_query") or ""))
    sub_queries_raw = data.get("sub_queries") or []
    sub_queries = [_normalize_text(str(x)) for x in sub_queries_raw if _normalize_text(str(x))]
    confidence_raw = data.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if query_type == "multi_intent" and not sub_queries:
        sub_queries = [normalized_query]
    if not rewritten_query:
        rewritten_query = normalized_query
    return QueryRewriteResult(
        query_type=query_type,
        rewritten_query=rewritten_query,
        sub_queries=sub_queries,
        confidence=confidence,
        language=detect_query_language(normalized_query, locale_mode),
    )
