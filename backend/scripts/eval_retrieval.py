#!/usr/bin/env python3
"""检索回归评测：对比 vector / hybrid / hybrid+rerank。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.data_loader import load_interview_seed
from app.embedding_index import seed_embedding_index
from app.knowledge_documents import knowledge_documents_root
from app.knowledge_rag import KnowledgeRAGService
from app.retrieval_fusion import hybrid_enabled, rerank_enabled
from openai import AsyncOpenAI

_EVAL_DIR = _BACKEND / "data" / "eval"
_RUNS_DIR = _EVAL_DIR / "runs"


def _recall_at_k(retrieved_ids: List[str], expected: Set[str], k: int) -> float:
    if not expected:
        return 0.0
    top = set(retrieved_ids[:k])
    return len(top & expected) / len(expected)


def _mrr(retrieved_ids: List[str], expected: Set[str]) -> float:
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in expected:
            return 1.0 / i
    return 0.0


async def _eval_jd(
    client: AsyncOpenAI,
    items: List[Dict[str, Any]],
    golden_path: Path,
    *,
    mode: str,
) -> Dict[str, Any]:
    os.environ["HYBRID_ENABLED"] = "false" if mode == "vector" else "true"
    os.environ["RERANK_ENABLED"] = "true" if mode == "hybrid_rerank" else "false"

    lines = [
        json.loads(ln)
        for ln in golden_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    recalls: List[float] = []
    mrrs: List[float] = []
    t0 = time.perf_counter()

    for row in lines:
        jd = str(row.get("jd_excerpt") or "").strip()
        expected = set(str(x) for x in (row.get("expected_question_ids") or []))
        diffs = row.get("difficulties") or ["intermediate"]
        if not jd or not expected:
            continue
        qvec = await seed_embedding_index.embed_query(client, jd)
        ranked, _, _ = seed_embedding_index.search_jd_candidates(
            qvec, jd, items, list(diffs), initial_k=30
        )
        ids = [str(it.get("id", "")) for it in ranked]
        recalls.append(_recall_at_k(ids, expected, 10))
        mrrs.append(_mrr(ids, expected))

    elapsed = time.perf_counter() - t0
    return {
        "mode": mode,
        "cases": len(recalls),
        "recall_at_10": sum(recalls) / max(1, len(recalls)),
        "mrr": sum(mrrs) / max(1, len(mrrs)),
        "elapsed_sec": round(elapsed, 3),
    }


async def _eval_tutor(
    client: AsyncOpenAI,
    svc: KnowledgeRAGService,
    golden_path: Path,
    *,
    mode: str,
) -> Dict[str, Any]:
    os.environ["HYBRID_ENABLED"] = "false" if mode == "vector" else "true"
    os.environ["RERANK_ENABLED"] = "true" if mode == "hybrid_rerank" else "false"

    lines = [
        json.loads(ln)
        for ln in golden_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    recalls: List[float] = []
    mrrs: List[float] = []
    t0 = time.perf_counter()

    for row in lines:
        query = str(row.get("query") or "").strip()
        expected_docs = set(str(x) for x in (row.get("expected_doc_ids") or []))
        corpus_id = str(row.get("corpus_id") or "").strip() or None
        if not query or not expected_docs:
            continue
        scored = await svc.retrieve_scored(query, top_k=6, corpus_id=corpus_id)
        got = []
        for r in scored:
            md = r.document.metadata or {}
            got.append(f"{md.get('corpus_id')}/{md.get('doc_id')}")
        recalls.append(_recall_at_k(got, expected_docs, 6))
        mrrs.append(_mrr(got, expected_docs))

    elapsed = time.perf_counter() - t0
    return {
        "mode": mode,
        "cases": len(recalls),
        "recall_at_6": sum(recalls) / max(1, len(recalls)),
        "mrr": sum(mrrs) / max(1, len(mrrs)),
        "elapsed_sec": round(elapsed, 3),
    }


async def _main_async(args: argparse.Namespace) -> int:
    load_dotenv(_BACKEND / ".env")
    client = AsyncOpenAI()
    items = load_interview_seed()
    await seed_embedding_index.build(items, client)

    svc = KnowledgeRAGService(docs_root=knowledge_documents_root())
    await svc.build()

    modes = ["vector", "hybrid", "hybrid_rerank"]
    results: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hybrid_enabled_default": hybrid_enabled(),
        "rerank_enabled_default": rerank_enabled(),
        "jd": [],
        "tutor": [],
    }

    jd_golden = _EVAL_DIR / "jd_golden.jsonl"
    tutor_golden = _EVAL_DIR / "tutor_golden.jsonl"

    if args.suite in ("jd", "all") and jd_golden.is_file():
        for m in modes:
            results["jd"].append(await _eval_jd(client, items, jd_golden, mode=m))

    if args.suite in ("tutor", "all") and tutor_golden.is_file():
        for m in modes:
            results["tutor"].append(await _eval_tutor(client, svc, tutor_golden, mode=m))

    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = _RUNS_DIR / f"{stamp}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"已写入: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检索回归评测")
    parser.add_argument("--suite", choices=("jd", "tutor", "all"), default="all")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
