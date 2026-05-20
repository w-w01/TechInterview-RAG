#!/usr/bin/env python3
"""知识库健康度检查：重复、完整性、一致性（只读报告，不改语料）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

_BACKEND = Path(__file__).resolve().parent.parent
_DOCS_ROOT = _BACKEND / "data" / "knowledge" / "documents"
_ALLOWLIST = _BACKEND / "data" / "topic_allowlist.json"
_REPORTS = _BACKEND / "data" / "knowledge" / "reports"

CONSISTENCY_SYSTEM = """你是技术文档审校助手。给定同一技术主题下的多段正文摘录，找出彼此矛盾或不一致的陈述。

输出 JSON：
{
  "topic": "主题名",
  "conflicts": [{"summary": "矛盾简述", "sources": ["corpus/doc_id", ...]}],
  "notes": "其他说明"
}
若无明显矛盾，conflicts 为空数组。"""


def _load_docs() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not _DOCS_ROOT.is_dir():
        return rows
    for p in sorted(_DOCS_ROOT.rglob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        body = str(data.get("body") or "").strip()
        if not body:
            continue
        corpus_id = str(data.get("corpus_id") or p.parent.name).strip()
        doc_id = str(data.get("doc_id") or p.stem).strip()
        rows.append(
            {
                "path": str(p.relative_to(_BACKEND)),
                "corpus_id": corpus_id,
                "doc_id": doc_id,
                "title": str(data.get("title") or doc_id).strip(),
                "body": body,
                "topic_slugs": data.get("topic_slugs") or [],
            }
        )
    return rows


def _dup_report(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_hash: Dict[str, List[str]] = defaultdict(list)
    for d in docs:
        h = hashlib.sha256(d["body"].encode("utf-8")).hexdigest()[:16]
        by_hash[h].append(f"{d['corpus_id']}/{d['doc_id']}")
    out = []
    for h, ids in by_hash.items():
        if len(ids) > 1:
            out.append({"hash": h, "doc_ids": ids})
    return out


def _completeness_report(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    covered: set[str] = set()
    for d in docs:
        for t in d.get("topic_slugs") or []:
            covered.add(str(t).strip().lower())
    expected: List[str] = []
    if _ALLOWLIST.is_file():
        data = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))
        expected = [str(x.get("slug", "")).strip() for x in data if x.get("slug")]
    missing = [s for s in expected if s and s not in covered]
    return {
        "topic_slugs_in_docs": sorted(covered),
        "allowlist_total": len(expected),
        "missing_from_docs": missing[:50],
        "missing_count": len(missing),
    }


def _consistency_llm(client: OpenAI, groups: List[List[Dict[str, Any]]], model: str) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for group in groups[:20]:
        if len(group) < 2:
            continue
        title = group[0]["title"]
        excerpts = []
        for g in group[:5]:
            excerpts.append(
                f"[{g['corpus_id']}/{g['doc_id']}] {g['body'][:1200]}"
            )
        user = f"主题：{title}\n\n" + "\n\n---\n\n".join(excerpts)
        try:
            resp = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": CONSISTENCY_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
            raw = resp.choices[0].message.content or "{}"
            reports.append(json.loads(raw))
        except Exception as e:
            reports.append({"topic": title, "error": str(e)})
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库健康度检查（只读报告）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 一致性检查")
    parser.add_argument("--model", default=os.getenv("HEALTH_CHECK_MODEL", "gpt-4o-mini"))
    args = parser.parse_args()

    docs = _load_docs()
    by_title: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for d in docs:
        by_title[d["title"].lower()].append(d)

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(docs),
        "duplicate_bodies": _dup_report(docs),
        "completeness": _completeness_report(docs),
        "consistency": [],
    }

    if not args.skip_llm and docs:
        load_dotenv(_BACKEND / ".env")
        client = OpenAI()
        multi = [g for g in by_title.values() if len(g) >= 2]
        report["consistency"] = _consistency_llm(client, multi, args.model)

    _REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = _REPORTS / f"health_{stamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入: {out_path}")
    print(
        f"文档数={report['document_count']} "
        f"重复组={len(report['duplicate_bodies'])} "
        f"缺失 topic={report['completeness'].get('missing_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
