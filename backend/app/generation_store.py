"""AI 出题快照：评卷时校验题干并还原参考种子片段。"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class GenerationSnapshot:
    """与 generation_id 绑定的不可变出题结果。"""

    generation_id: str
    question: str
    expected_key_points: List[str]
    source_seed_ids: List[str]
    topics: List[str]
    difficulty: str


_snapshots: Dict[str, GenerationSnapshot] = {}


def put_snapshot(snap: GenerationSnapshot) -> None:
    _snapshots[snap.generation_id] = snap


def get_snapshot(generation_id: str) -> Optional[GenerationSnapshot]:
    return _snapshots.get(generation_id)
