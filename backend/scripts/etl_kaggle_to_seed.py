#!/usr/bin/env python3
"""从公开数据集 JSON 生成 interview_qa_seed.json 与 topic_allowlist.json。

数据源：backend/data/kaggle-Software_Engineering_Interview_Questions_Dataset.json
输出：覆盖 backend/data/interview_qa_seed.json、backend/data/topic_allowlist.json

topic slug：将原始 topic 字符串规范化（小写、空格与连字符转为下划线）；
合并已知笔误（如 general program -> general programming）。
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KAGGLE_PATH = DATA / "kaggle-Software_Engineering_Interview_Questions_Dataset.json"
OUT_SEED = DATA / "interview_qa_seed.json"
OUT_ALLOWLIST = DATA / "topic_allowlist.json"

# 原始字符串（小写） -> 规范类目名（用于生成 slug 与展示标签）
TYPO_AND_ALIAS: dict[str, str] = {
    "general program": "general programming",
}

DEFAULT_SOURCE = "Kaggle Software Engineering Interview Questions Dataset"

# slug -> 展示名（覆盖 title() 机械化结果）
SLUG_LABEL_OVERRIDES: dict[str, str] = {
    "database_and_sql": "Database and SQL",
    "devops": "DevOps",
    "languages_and_frameworks": "Languages and Frameworks",
    "general_programming": "General Programming",
    "software_testing": "Software Testing",
    "version_control": "Version Control",
    "web_development": "Web Development",
    "data_structures": "Data Structures",
    "system_design": "System Design",
    "machine_learning": "Machine Learning",
    "distributed_systems": "Distributed Systems",
    "database_systems": "Database Systems",
    "low_level_systems": "Low-Level Systems",
    "data_engineering": "Data Engineering",
    "artificial_intelligence": "Artificial Intelligence",
}


def canon_category(raw: str) -> str:
    """统一类目字符串（小写 + 修正笔误）。"""
    k = raw.strip().lower()
    return TYPO_AND_ALIAS.get(k, k)


def category_to_slug(canon: str) -> str:
    """类目 -> slug：仅字母数字与下划线。"""
    s = canon.replace(" ", "_").replace("-", "_").replace("/", "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def label_from_canon(canon: str) -> str:
    """展示用标签：首字母大写每个单词。"""
    return canon.title()


def main() -> None:
    if not KAGGLE_PATH.is_file():
        raise FileNotFoundError(f"找不到数据集: {KAGGLE_PATH}")

    with KAGGLE_PATH.open(encoding="utf-8") as f:
        blob = json.load(f)

    rows = blob.get("results")
    if not isinstance(rows, list):
        raise ValueError("数据集顶层须包含 results 数组")

    # slug -> 展示标签（每个 slug 首次出现的规范类目）
    slug_to_label: OrderedDict[str, str] = OrderedDict()
    for row in rows:
        topics_in = row.get("topics") or []
        if not isinstance(topics_in, list):
            continue
        for t in topics_in:
            canon = canon_category(str(t))
            if not canon:
                continue
            slug = category_to_slug(canon)
            if not slug:
                continue
            if slug not in slug_to_label:
                slug_to_label[slug] = SLUG_LABEL_OVERRIDES.get(
                    slug, label_from_canon(canon)
                )

    sorted_slugs = sorted(slug_to_label.keys())
    allowlist_obj = {
        "topics": [
            {"slug": s, "label": slug_to_label[s]} for s in sorted_slugs
        ]
    }

    out_items: list[dict] = []
    for row in rows:
        topics_slugs: list[str] = []
        seen: set[str] = set()
        for t in row.get("topics") or []:
            canon = canon_category(str(t))
            if not canon:
                continue
            slug = category_to_slug(canon)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            topics_slugs.append(slug)

        if not topics_slugs:
            raise ValueError(f"条目 {row.get('id')} 缺少有效 topics")

        src = row.get("source")
        if isinstance(src, str) and src.strip():
            source_val = src.strip()
        else:
            source_val = DEFAULT_SOURCE

        kp = row.get("key_points") or []
        if not isinstance(kp, list):
            kp = [str(kp)]

        tags = row.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]

        out_items.append(
            {
                "id": str(row["id"]),
                "topics": topics_slugs,
                "difficulty": str(row["difficulty"]).strip().lower(),
                "question": str(row["question"]),
                "answer": str(row["answer"]),
                "key_points": [str(x) for x in kp],
                "tags": [str(x) for x in tags],
                "source": source_val,
            }
        )

    with OUT_ALLOWLIST.open("w", encoding="utf-8") as f:
        json.dump(allowlist_obj, f, ensure_ascii=False, indent=2)
        f.write("\n")

    with OUT_SEED.open("w", encoding="utf-8") as f:
        json.dump(out_items, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"OK: {len(out_items)} 条题目, {len(sorted_slugs)} 个 topic slug")
    print(f"写入 {OUT_SEED.name} , {OUT_ALLOWLIST.name}")


if __name__ == "__main__":
    main()
