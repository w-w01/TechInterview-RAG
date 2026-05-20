#!/usr/bin/env python3
"""为知识库 JSON 文档生成 synthetic_queries（Doc2Query），写回源文件。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

_BACKEND = Path(__file__).resolve().parent.parent
_DOCS_ROOT = _BACKEND / "data" / "knowledge" / "documents"

DOC2QUERY_SYSTEM = """你是技术面试知识库助手。根据给定文章标题与正文，生成 8 条多样化检索用问题。

要求：
- 覆盖：定义、原理、对比、使用场景、常见坑、排错、面试追问等角度。
- 问题应能被该正文回答，不要编造正文没有的技术点。
- 输出 JSON：{"questions": ["...", ...]}，恰好 8 条字符串，不要 markdown 代码块。
"""


def _client() -> OpenAI:
    load_dotenv(_BACKEND / ".env")
    return OpenAI()


def generate_questions(client: OpenAI, *, title: str, body: str, model: str) -> list[str]:
    user = f"标题：{title}\n\n正文（节选）：\n{body[:6000]}"
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": DOC2QUERY_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    qs = data.get("questions") or data.get("synthetic_queries") or []
    out = [str(q).strip() for q in qs if str(q).strip()]
    return out[:8]


def main() -> int:
    parser = argparse.ArgumentParser(description="Doc2Query：为知识库 JSON 生成 synthetic_queries")
    parser.add_argument("--corpus-id", default="", help="仅处理指定 corpus 子目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写回")
    parser.add_argument("--model", default=os.getenv("DOC2QUERY_MODEL", "gpt-4o-mini"))
    args = parser.parse_args()

    if not _DOCS_ROOT.is_dir():
        print(f"文档目录不存在: {_DOCS_ROOT}", file=sys.stderr)
        return 1

    client = _client()
    pattern = "**/*.json"
    paths = sorted(_DOCS_ROOT.rglob(pattern))
    if args.corpus_id:
        base = _DOCS_ROOT / args.corpus_id.strip()
        paths = sorted(base.rglob("*.json")) if base.is_dir() else []

    updated = 0
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"跳过 {p}: {e}")
            continue
        title = str(data.get("title") or p.stem).strip()
        body = str(data.get("body") or "").strip()
        if not body:
            continue
        try:
            qs = generate_questions(client, title=title, body=body, model=args.model)
        except Exception as e:
            print(f"生成失败 {p}: {e}")
            continue
        if args.dry_run:
            print(f"[dry-run] {p.relative_to(_DOCS_ROOT)} -> {len(qs)} questions")
            continue
        data["synthetic_queries"] = qs
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1
        print(f"已更新 {p.relative_to(_DOCS_ROOT)} ({len(qs)} 条)")

    print(f"完成：写回 {updated} 个文件。请设置 KNOWLEDGE_FAISS_REBUILD=true 后重启以重建索引。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
