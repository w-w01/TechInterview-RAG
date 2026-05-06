"""题库条目 Embedding 与 JD 文本向量检索（狭义 RAG 组卷）。"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from openai import AsyncOpenAI

from .rag import _item_topic_slugs

logger = logging.getLogger(__name__)


def doc_text_for_embedding(item: Dict[str, Any]) -> str:
    """将单条种子拼成与检索/向量化一致的文档文本。"""
    kp = item.get("key_points") or []
    kp_str = "\n".join(f"- {p}" for p in kp) if isinstance(kp, list) else str(kp)
    topics_line = ", ".join(sorted(_item_topic_slugs(item))) or "(none)"
    return (
        f"Topics: {topics_line}\n"
        f"Difficulty: {item.get('difficulty', '')}\n"
        f"Question: {item.get('question', '')}\n"
        f"Reference answer: {item.get('answer', '')}\n"
        f"Key points:\n{kp_str}"
    )


class SeedEmbeddingIndex:
    """全量种子 embedding 矩阵；按难度子集与 JD 查询向量做余弦 Top-K。"""

    def __init__(self, embedding_model: str = "text-embedding-3-small") -> None:
        self._model = embedding_model
        self._matrix: Optional[np.ndarray] = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready and self._matrix is not None

    async def build(self, items: List[Dict[str, Any]], client: AsyncOpenAI) -> None:
        """对全部种子批量嵌入并 L2 归一化；行号与 items 下标一致。"""
        if not items:
            raise ValueError("种子为空，无法构建向量索引")
        texts = [doc_text_for_embedding(it) for it in items]
        batch_size = 64
        all_vecs: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            resp = await client.embeddings.create(model=self._model, input=chunk)
            by_index = {d.index: d.embedding for d in resp.data}
            for j in range(len(chunk)):
                all_vecs.append(by_index[j])
        mat = np.array(all_vecs, dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        mat = mat / norms
        self._matrix = mat
        self._ready = True
        logger.info(
            "种子向量索引构建完成: 条目数=%s, 维度=%s",
            len(items),
            mat.shape[1],
        )

    async def embed_query(self, client: AsyncOpenAI, text: str) -> np.ndarray:
        """单条查询文本嵌入并归一化，形状 (1, D)。"""
        resp = await client.embeddings.create(model=self._model, input=[text])
        v = np.array(resp.data[0].embedding, dtype=np.float32).reshape(1, -1)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return v / n

    def search_by_difficulty(
        self,
        query_vec: np.ndarray,
        items: List[Dict[str, Any]],
        difficulty: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """在指定难度子集内按内积（余弦）降序取 Top-K，按 id 去重。"""
        if self._matrix is None:
            return []
        want_diff = difficulty.strip()
        idxs = [
            i
            for i, it in enumerate(items)
            if str(it.get("difficulty", "")).strip() == want_diff
        ]
        if not idxs:
            return []
        sub = self._matrix[idxs]
        scores = (sub @ query_vec.T).flatten()
        order = np.argsort(-scores)
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for j in order:
            if len(out) >= top_k:
                break
            row = int(j)
            it = items[idxs[row]]
            iid = str(it.get("id", ""))
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out.append(it)
        return out


seed_embedding_index = SeedEmbeddingIndex()
