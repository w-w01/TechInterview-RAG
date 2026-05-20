"""Hybrid 检索（向量 + BM25）与本地 BGE Rerank 共享模块。"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_+#./-]+")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float, *, min_v: float = 0.0, max_v: float = 1.0) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = float(str(raw).strip())
        return max(min_v, min(max_v, v))
    except ValueError:
        return default


def _env_int(name: str, default: int, *, min_v: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return max(min_v, int(str(raw).strip()))
    except ValueError:
        return default


def hybrid_enabled() -> bool:
    return _env_bool("HYBRID_ENABLED", True)


def rerank_enabled() -> bool:
    return _env_bool("RERANK_ENABLED", True)


def hybrid_alpha() -> float:
    return _env_float("HYBRID_ALPHA", 0.4)


def retrieve_initial_k() -> int:
    return _env_int("RETRIEVE_INITIAL_K", 30, min_v=5)


def jd_rerank_top_n() -> int:
    return _env_int("JD_RERANK_TOP_N", 15, min_v=5)


def rerank_model_name() -> str:
    return os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base").strip() or "BAAI/bge-reranker-base"


def tokenize_for_bm25(text: str) -> List[str]:
    """英文词元 + 数字/技术 token + 中文二字 gram，不依赖 jieba。"""
    s = str(text or "").strip().lower()
    if not s:
        return []
    tokens: List[str] = []
    tokens.extend(_ASCII_WORD_RE.findall(s))
    cjk = _CJK_RE.findall(s)
    joined = "".join(cjk)
    for i in range(len(joined) - 1):
        tokens.append(joined[i : i + 2])
    if len(joined) == 1:
        tokens.append(joined)
    return tokens


def _minmax_norm(scores: Dict[int, float]) -> Dict[int, float]:
    if not scores:
        return {}
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


@dataclass
class FusionHit:
    """融合检索命中项。"""

    index: int
    fusion_score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rerank_score: Optional[float] = None


class BM25CorpusIndex:
    """内存 BM25 索引，行号与语料列表下标对齐。"""

    def __init__(self) -> None:
        self._bm25 = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready and self._bm25 is not None

    def build(self, texts: Sequence[str]) -> None:
        from rank_bm25 import BM25Okapi

        tokenized = [tokenize_for_bm25(t) for t in texts]
        tokenized = [t if t else ["_"] for t in tokenized]
        self._bm25 = BM25Okapi(tokenized)
        self._ready = True

    def search(
        self,
        query: str,
        *,
        allowed_indices: Optional[Sequence[int]] = None,
        top_k: int = 30,
    ) -> List[Tuple[int, float]]:
        if not self.ready or self._bm25 is None:
            return []
        q_tokens = tokenize_for_bm25(query)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        if allowed_indices is not None:
            allowed = set(int(i) for i in allowed_indices)
            ranked = [(i, float(scores[i])) for i in allowed if 0 <= i < len(scores)]
        else:
            ranked = [(i, float(scores[i])) for i in range(len(scores))]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[: max(1, top_k)]


def fuse_vector_bm25(
    vector_hits: List[Tuple[int, float]],
    bm25_hits: List[Tuple[int, float]],
    *,
    alpha: float,
    top_k: int,
) -> List[FusionHit]:
    """融合向量分（越大越好）与 BM25 分（越大越好）。"""
    vec_map = {i: s for i, s in vector_hits}
    bm_map = {i: s for i, s in bm25_hits}
    all_idx = set(vec_map) | set(bm_map)
    if not all_idx:
        return []
    vec_n = _minmax_norm(vec_map)
    bm_n = _minmax_norm(bm_map)
    a = max(0.0, min(1.0, alpha))
    fused: List[FusionHit] = []
    for idx in all_idx:
        vs = vec_n.get(idx, 0.0)
        bs = bm_n.get(idx, 0.0)
        fusion = (1.0 - a) * vs + a * bs
        fused.append(
            FusionHit(
                index=idx,
                fusion_score=fusion,
                vector_score=vec_map.get(idx, 0.0),
                bm25_score=bm_map.get(idx, 0.0),
            )
        )
    fused.sort(key=lambda h: h.fusion_score, reverse=True)
    return fused[: max(1, top_k)]


class RerankService:
    """BGE CrossEncoder 懒加载；失败时降级为不 rerank。"""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._load_failed = False

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        with self._lock:
            if self._model is not None:
                return True
            if self._load_failed:
                return False
            try:
                from sentence_transformers import CrossEncoder

                name = rerank_model_name()
                logger.info("正在加载 Rerank 模型: %s", name)
                self._model = CrossEncoder(name, max_length=512)
                logger.info("Rerank 模型加载完成")
                return True
            except Exception as e:
                self._load_failed = True
                logger.warning("Rerank 模型加载失败，将降级为仅 Hybrid: %s", e)
                return False

    def rerank(
        self,
        query: str,
        passages: Sequence[str],
        *,
        top_n: int,
    ) -> List[Tuple[int, float]]:
        """返回 (passage 下标, rerank 分)，分数越大越相关。"""
        if not passages or top_n <= 0:
            return []
        if not rerank_enabled():
            return [(i, 0.0) for i in range(min(top_n, len(passages)))]
        if not self._ensure_model():
            return [(i, 0.0) for i in range(min(top_n, len(passages)))]
        pairs = [[query, p] for p in passages]
        try:
            scores = self._model.predict(pairs)
            ranked = sorted(
                [(i, float(s)) for i, s in enumerate(scores)],
                key=lambda x: x[1],
                reverse=True,
            )
            return ranked[:top_n]
        except Exception as e:
            logger.warning("Rerank 推理失败，降级为融合序: %s", e)
            return [(i, 0.0) for i in range(min(top_n, len(passages)))]


_rerank_service = RerankService()


def get_rerank_service() -> RerankService:
    return _rerank_service


def apply_rerank_to_hits(
    query: str,
    hits: List[FusionHit],
    passages: Sequence[str],
    *,
    top_n: int,
) -> List[FusionHit]:
    """对 FusionHit 列表按 rerank 重排并写入 rerank_score。"""
    if not hits:
        return []
    idxs = [h.index for h in hits]
    texts = [passages[i] for i in idxs if 0 <= i < len(passages)]
    if len(texts) != len(idxs):
        return hits[:top_n]
    ranked = get_rerank_service().rerank(query, texts, top_n=top_n)
    by_local = {h.index: h for h in hits}
    out: List[FusionHit] = []
    for local_i, score in ranked:
        orig_idx = idxs[local_i]
        base = by_local.get(orig_idx)
        if base is None:
            continue
        out.append(
            FusionHit(
                index=base.index,
                fusion_score=base.fusion_score,
                vector_score=base.vector_score,
                bm25_score=base.bm25_score,
                rerank_score=score,
            )
        )
    return out


def vector_search_subset(
    query_vec: np.ndarray,
    matrix: np.ndarray,
    indices: List[int],
    top_k: int,
) -> List[Tuple[int, float]]:
    """在 matrix 的 indices 子集上做余弦检索，返回 (全局下标, 分数)。"""
    if matrix is None or not indices:
        return []
    sub = matrix[indices]
    scores = (sub @ query_vec.T).flatten()
    order = np.argsort(-scores)
    out: List[Tuple[int, float]] = []
    for j in order:
        if len(out) >= top_k:
            break
        gi = indices[int(j)]
        out.append((gi, float(scores[int(j)])))
    return out
