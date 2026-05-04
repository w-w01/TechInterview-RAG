"""本地种子 + OpenAI Embedding + FAISS 检索逻辑。"""

import logging
import random
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _doc_text(item: Dict[str, Any]) -> str:
    """将单条题库条目拼成用于向量化的文本。"""
    kp = item.get("key_points") or []
    kp_str = "\n".join(f"- {p}" for p in kp) if isinstance(kp, list) else str(kp)
    return (
        f"Topic: {item.get('topic', '')}\n"
        f"Difficulty: {item.get('difficulty', '')}\n"
        f"Question: {item.get('question', '')}\n"
        f"Reference answer: {item.get('answer', '')}\n"
        f"Key points:\n{kp_str}"
    )


class RAGService:
    """加载种子、构建 FAISS 索引，并提供按主题过滤的相似度检索。"""

    def __init__(self, embedding_model: str = "text-embedding-3-small") -> None:
        self._client: Optional[AsyncOpenAI] = None
        self._embedding_model = embedding_model
        self._items: List[Dict[str, Any]] = []
        self._index: Optional[faiss.IndexFlatIP] = None
        self._vectors: Optional[np.ndarray] = None
        self._dim: int = 0

    @property
    def ready(self) -> bool:
        return self._index is not None and len(self._items) > 0

    @property
    def item_count(self) -> int:
        return len(self._items)

    def _get_client(self) -> AsyncOpenAI:
        """延迟创建客户端，避免仅 import 模块时缺少环境变量即报错。"""
        if self._client is None:
            self._client = AsyncOpenAI()
        return self._client

    def load_items(self, items: List[Dict[str, Any]]) -> None:
        self._items = list(items)

    async def build_index(self) -> None:
        """对所有种子条目计算 embedding 并构建 FAISS 内积索引（向量已 L2 归一化）。"""
        if not self._items:
            raise ValueError("种子数据为空，无法构建索引")
        texts = [_doc_text(it) for it in self._items]
        embeddings = await self._embed_batch(texts)
        mat = np.array(embeddings, dtype="float32")
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        mat = mat / norms
        self._dim = mat.shape[1]
        index = faiss.IndexFlatIP(self._dim)
        index.add(mat)
        self._index = index
        self._vectors = mat
        logger.info("FAISS 索引构建完成，条目数=%s，维度=%s", len(self._items), self._dim)

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """分批调用 OpenAI Embeddings，避免单次请求过大。"""
        batch_size = 64
        all_vecs: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            resp = await self._get_client().embeddings.create(
                model=self._embedding_model,
                input=chunk,
            )
            # API 保证与 input 顺序一致
            by_index = {d.index: d.embedding for d in resp.data}
            for j in range(len(chunk)):
                all_vecs.append(by_index[j])
        return all_vecs

    async def embed_query(self, text: str) -> np.ndarray:
        resp = await self._get_client().embeddings.create(
            model=self._embedding_model,
            input=[text],
        )
        v = np.array(resp.data[0].embedding, dtype="float32").reshape(1, -1)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return v / n

    def pick_question(self, topic: str, difficulty: str) -> Optional[Dict[str, Any]]:
        """按主题与难度从种子中随机抽取一题（MVP 直接检索）。"""
        pool = [
            it
            for it in self._items
            if str(it.get("topic", "")).strip() == topic.strip()
            and str(it.get("difficulty", "")).strip() == difficulty.strip()
        ]
        if not pool:
            return None
        return random.choice(pool)

    async def retrieve(
        self,
        *,
        query_text: str,
        topic: str,
        top_k: int = 5,
        oversample: int = 24,
    ) -> List[Dict[str, Any]]:
        """对 query_text 做向量检索，优先保留同主题条目，不足则补齐。"""
        if not self.ready or self._index is None:
            raise RuntimeError("RAG 索引未就绪")
        q = await self.embed_query(query_text)
        k_search = min(oversample, len(self._items))
        scores, indices = self._index.search(q, k_search)
        idx_list = indices[0].tolist()
        score_list = scores[0].tolist()
        ranked: List[Tuple[float, Dict[str, Any]]] = []
        for idx, sc in zip(idx_list, score_list):
            if 0 <= idx < len(self._items):
                ranked.append((float(sc), self._items[idx]))
        same_topic = [(s, it) for s, it in ranked if str(it.get("topic", "")).strip() == topic.strip()]
        other = [(s, it) for s, it in ranked if str(it.get("topic", "")).strip() != topic.strip()]
        merged: List[Dict[str, Any]] = []
        seen_ids = set()
        for _, it in same_topic + other:
            iid = str(it.get("id", ""))
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            merged.append(it)
            if len(merged) >= top_k:
                break
        return merged
