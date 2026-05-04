"""从本地 JSON 加载面试题库种子数据。"""

import json
from pathlib import Path
from typing import Any, Dict, List


def _data_path() -> Path:
    # backend/app/data_loader.py -> backend/data/
    return Path(__file__).resolve().parent.parent / "data" / "interview_qa_seed.json"


def load_interview_seed() -> List[Dict[str, Any]]:
    """读取并解析 interview_qa_seed.json，返回字典列表。"""
    path = _data_path()
    if not path.is_file():
        raise FileNotFoundError(f"未找到种子文件: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("种子文件顶层必须是 JSON 数组")
    return data
