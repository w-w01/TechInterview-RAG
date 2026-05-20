"""题库条目 Embedding 与 JD 文本向量检索（狭义 RAG 组卷）。"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from openai import AsyncOpenAI

from .rag import _item_topic_slugs
from .retrieval_fusion import (
    BM25CorpusIndex,
    FusionHit,
    apply_rerank_to_hits,
    fuse_vector_bm25,
    hybrid_alpha,
    hybrid_enabled,
    jd_rerank_top_n,
    retrieve_initial_k,
    rerank_enabled,
    vector_search_subset,
)

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


def doc_text_for_rerank(item: Dict[str, Any]) -> str:
    """Rerank 用较短文本：题干 + 要点预览。"""
    kp = item.get("key_points") or []
    kp_str = "; ".join(str(p) for p in kp[:6]) if isinstance(kp, list) else str(kp)
    return (
        f"Question: {item.get('question', '')}\n"
        f"Key points: {kp_str}"
    )


class SeedEmbeddingIndex:
    """全量种子 embedding 矩阵；支持 Hybrid + Rerank 的 JD 检索。"""

    def __init__(self, embedding_model: str = "text-embedding-3-small") -> None:
        self._model = embedding_model
        self._matrix: Optional[np.ndarray] = None
        self._texts: List[str] = []
        self._bm25 = BM25CorpusIndex()
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready and self._matrix is not None

    @property
    def bm25_ready(self) -> bool:
        return self._bm25.ready

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
        self._texts = texts
        self._bm25.build(texts)
        self._ready = True
        logger.info(
            "种子向量索引构建完成: 条目数=%s, 维度=%s, bm25=%s",
            len(items),
            mat.shape[1],
            self._bm25.ready,
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

    def _hybrid_hits_for_difficulty(
        self,
        query_vec: np.ndarray,
        query_text: str,
        items: List[Dict[str, Any]],
        difficulty: str,
        initial_k: int,
        alpha: float,
    ) -> List[FusionHit]:
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
        vec_hits = vector_search_subset(query_vec, self._matrix, idxs, initial_k)
        bm25_hits = self._bm25.search(
            query_text, allowed_indices=idxs, top_k=initial_k
        )
        return fuse_vector_bm25(vec_hits, bm25_hits, alpha=alpha, top_k=initial_k)

    def search_jd_candidates(
        self,
        query_vec: np.ndarray,
        query_text: str,
        items: List[Dict[str, Any]],
        difficulties: List[str],
        *,
        initial_k: Optional[int] = None,
        rerank_top_n: Optional[int] = None,
        query_expansion: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[FusionHit], str]:
        """
        JD 组卷检索：按难度 Hybrid 初筛 → 跨难度按 id 去重 → Rerank。
        返回 (题目列表, 融合命中详情, retrieval_mode)。
        """
        init_k = initial_k if initial_k is not None else retrieve_initial_k()
        r_top = rerank_top_n if rerank_top_n is not None else jd_rerank_top_n()
        # query_expansion 预留 P2 Query2Doc，当前未使用
        _ = query_expansion
        search_text = query_text
        use_hybrid = hybrid_enabled() and self._bm25.ready
        mode = "vector"

        all_hits: List[FusionHit] = []
        if use_hybrid:
            mode = "hybrid"
            alpha = hybrid_alpha()
            for diff in difficulties:
                all_hits.extend(
                    self._hybrid_hits_for_difficulty(
                        query_vec, search_text, items, diff, init_k, alpha
                    )
                )
            # 按 question id 去重，保留更高 fusion 分
            best_by_id: Dict[str, FusionHit] = {}
            for h in all_hits:
                it = items[h.index]
                iid = str(it.get("id", "")).strip()
                if not iid:
                    continue
                prev = best_by_id.get(iid)
                if prev is None or h.fusion_score > prev.fusion_score:
                    best_by_id[iid] = h
            merged = sorted(best_by_id.values(), key=lambda x: x.fusion_score, reverse=True)
            all_hits = merged[:init_k]
        else:
            seen: set = set()
            for diff in difficulties:
                for it in self.search_by_difficulty(query_vec, items, diff, init_k):
                    iid = str(it.get("id", "")).strip()
                    if iid and iid not in seen:
                        seen.add(iid)
                        idx = next(
                            (i for i, x in enumerate(items) if str(x.get("id")) == iid),
                            -1,
                        )
                        if idx >= 0:
                            all_hits.append(FusionHit(index=idx, fusion_score=0.0))

        if rerank_enabled() and all_hits:
            passages = [doc_text_for_rerank(items[h.index]) for h in all_hits]
            all_hits = apply_rerank_to_hits(search_text, all_hits, passages, top_n=r_top)
            mode = f"{mode}+rerank" if use_hybrid else "vector+rerank"

        ranked_items: List[Dict[str, Any]] = []
        seen_out: set = set()
        for h in all_hits:
            it = items[h.index]
            iid = str(it.get("id", "")).strip()
            if not iid or iid in seen_out:
                continue
            seen_out.add(iid)
            ranked_items.append(it)

        return ranked_items, all_hits, mode


seed_embedding_index = SeedEmbeddingIndex()
