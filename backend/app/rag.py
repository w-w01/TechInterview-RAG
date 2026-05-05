"""本地种子题库：按标签与难度随机选题（不做向量检索）。"""

import random
from typing import Any, Dict, List, Optional


def _item_topic_slugs(item: Dict[str, Any]) -> set:
    """从条目读取规范化后的 topic slug 集合。"""
    raw = item.get("topics")
    if isinstance(raw, list) and raw:
        return {str(x).strip().lower() for x in raw if str(x).strip()}
    return set()


class QuestionBank:
    """加载种子并提供按主题过滤的随机抽题。"""

    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    @property
    def ready(self) -> bool:
        """题库非空即视为就绪（无向量索引）。"""
        return len(self._items) > 0

    @property
    def item_count(self) -> int:
        return len(self._items)

    def load_items(self, items: List[Dict[str, Any]]) -> None:
        self._items = list(items)

    def pick_question(
        self, selected_topics: List[str], difficulty: str
    ) -> Optional[Dict[str, Any]]:
        """选题池：题目 topics 与用户所选 slug 至少有一个交集（OR），且难度匹配。"""
        want = {str(t).strip().lower() for t in selected_topics if str(t).strip()}
        if not want:
            return None
        pool = [
            it
            for it in self._items
            if _item_topic_slugs(it) & want
            and str(it.get("difficulty", "")).strip() == difficulty.strip()
        ]
        if not pool:
            return None
        return random.choice(pool)


# 兼容旧名：main 等模块仍引用 rag = QuestionBank()
RAGService = QuestionBank
