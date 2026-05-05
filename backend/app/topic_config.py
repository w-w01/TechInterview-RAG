"""外置 topic 白名单加载与种子校验。"""

import json
from pathlib import Path
from typing import Any, Dict, List, Set


def _allowlist_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "topic_allowlist.json"


def load_topic_allowlist() -> List[Dict[str, str]]:
    """读取 topic_allowlist.json，返回 topics 数组（slug + label）。"""
    path = _allowlist_path()
    if not path.is_file():
        raise FileNotFoundError(f"未找到 topic 白名单: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("topics") or []
    if not isinstance(entries, list):
        raise ValueError("topic_allowlist.json 中 topics 须为数组")
    out: List[Dict[str, str]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        slug = str(e.get("slug", "")).strip()
        label = str(e.get("label", slug)).strip()
        if slug:
            out.append({"slug": slug, "label": label})
    if not out:
        raise ValueError("topic 白名单为空")
    return out


def allowed_slug_set(entries: List[Dict[str, str]]) -> Set[str]:
    return {e["slug"] for e in entries}


def validate_topics_field(topics: Any, allowed: Set[str], item_id: str) -> None:
    """校验单条记录的 topics 字段（slug 小写且须在白名单）。"""
    if not isinstance(topics, list) or len(topics) == 0:
        raise ValueError(f"条目 {item_id} 必须包含非空 topics 数组")
    seen: Set[str] = set()
    for t in topics:
        s = str(t).strip().lower()
        if not s:
            continue
        if s not in allowed:
            raise ValueError(f"条目 {item_id} 含未知 topic slug: {s}（请核对 topic_allowlist.json）")
        seen.add(s)
    if not seen:
        raise ValueError(f"条目 {item_id} 的 topics 无效")


def validate_seed_against_allowlist(
    items: List[Dict[str, Any]], allowed: Set[str]
) -> None:
    """启动时校验全部种子。"""
    for it in items:
        iid = str(it.get("id", ""))
        validate_topics_field(it.get("topics"), allowed, iid or "?")
