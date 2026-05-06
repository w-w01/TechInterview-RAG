"""练习会话存储（SQLite 持久化，单机演示）。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class PracticeSession:
    session_id: str
    created_at: str
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    seen_seed_ids: List[str] = field(default_factory=list)
    weakness_counts: Dict[str, int] = field(default_factory=dict)
    papers: List[Dict[str, Any]] = field(default_factory=list)


_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "session_store.sqlite3"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
              paper_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              source TEXT NOT NULL,
              difficulty TEXT NOT NULL,
              question_count INTEGER NOT NULL,
              meta_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              paper_id TEXT,
              source TEXT NOT NULL,
              question_id TEXT,
              generation_id TEXT,
              question_text TEXT,
              topics_json TEXT NOT NULL,
              difficulty TEXT NOT NULL,
              score INTEGER,
              weak_topics_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS weaknesses (
              session_id TEXT NOT NULL,
              topic TEXT NOT NULL,
              cnt INTEGER NOT NULL,
              PRIMARY KEY(session_id, topic)
            )
            """
        )


_init_db()


def create_session() -> PracticeSession:
    sid = str(uuid.uuid4())
    ts = _utc_now()
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions(session_id, created_at) VALUES (?, ?)", (sid, ts)
        )
    return PracticeSession(session_id=sid, created_at=ts)


def create_paper(
    session_id: str,
    *,
    source: str,
    difficulty: str,
    question_count: int,
    meta: Dict[str, Any],
) -> str:
    """创建显式试卷实体并返回 paper_id。"""
    pid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            """
            INSERT INTO papers(paper_id, session_id, source, difficulty, question_count, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                session_id,
                source,
                difficulty,
                int(question_count),
                json.dumps(meta, ensure_ascii=False),
                _utc_now(),
            ),
        )
    return pid


def _load_attempts(c: sqlite3.Connection, session_id: str) -> List[Dict[str, Any]]:
    rows = c.execute(
        """
        SELECT paper_id, source, question_id, generation_id, question_text, topics_json,
               difficulty, score, weak_topics_json, created_at
        FROM attempts
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "paper_id": r["paper_id"],
                "source": r["source"],
                "question_id": r["question_id"],
                "generation_id": r["generation_id"],
                "question_text": r["question_text"],
                "topics": json.loads(r["topics_json"] or "[]"),
                "difficulty": r["difficulty"],
                "score": r["score"],
                "weak_topics": json.loads(r["weak_topics_json"] or "[]"),
                "created_at": r["created_at"],
            }
        )
    return out


def _load_weakness(c: sqlite3.Connection, session_id: str) -> Dict[str, int]:
    rows = c.execute(
        "SELECT topic, cnt FROM weaknesses WHERE session_id = ? ORDER BY cnt DESC",
        (session_id,),
    ).fetchall()
    return {str(r["topic"]): int(r["cnt"]) for r in rows}


def _load_papers(c: sqlite3.Connection, session_id: str) -> List[Dict[str, Any]]:
    rows = c.execute(
        """
        SELECT paper_id, source, difficulty, question_count, meta_json, created_at
        FROM papers
        WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "paper_id": r["paper_id"],
                "source": r["source"],
                "difficulty": r["difficulty"],
                "question_count": int(r["question_count"]),
                "meta": json.loads(r["meta_json"] or "{}"),
                "created_at": r["created_at"],
            }
        )
    return out


def get_session(session_id: str) -> Optional[PracticeSession]:
    sid = str(session_id).strip()
    if not sid:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT session_id, created_at FROM sessions WHERE session_id = ?", (sid,)
        ).fetchone()
        if row is None:
            return None
        attempts = _load_attempts(c, sid)
        seen = [
            str(x["question_id"])
            for x in attempts
            if str(x.get("question_id") or "").strip()
        ]
        seen_unique = list(dict.fromkeys(seen))
        return PracticeSession(
            session_id=row["session_id"],
            created_at=row["created_at"],
            attempts=attempts,
            seen_seed_ids=seen_unique,
            weakness_counts=_load_weakness(c, sid),
            papers=_load_papers(c, sid),
        )


def append_attempt(session_id: str, attempt: Dict[str, Any]) -> None:
    sid = str(session_id).strip()
    if not sid:
        return
    with _conn() as c:
        exists = c.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (sid,)
        ).fetchone()
        if exists is None:
            return
        c.execute(
            """
            INSERT INTO attempts(
              session_id, paper_id, source, question_id, generation_id, question_text,
              topics_json, difficulty, score, weak_topics_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                attempt.get("paper_id"),
                str(attempt.get("source") or ""),
                attempt.get("question_id"),
                attempt.get("generation_id"),
                attempt.get("question_text"),
                json.dumps(attempt.get("topics") or [], ensure_ascii=False),
                str(attempt.get("difficulty") or ""),
                attempt.get("score"),
                json.dumps(attempt.get("weak_topics") or [], ensure_ascii=False),
                _utc_now(),
            ),
        )


def record_weak_topics(session_id: str, weak_topics: List[str]) -> None:
    sid = str(session_id).strip()
    norm = [str(x).strip().lower() for x in weak_topics if str(x).strip()]
    if not sid or not norm:
        return
    with _conn() as c:
        for t in norm:
            c.execute(
                """
                INSERT INTO weaknesses(session_id, topic, cnt)
                VALUES (?, ?, 1)
                ON CONFLICT(session_id, topic) DO UPDATE SET cnt = cnt + 1
                """,
                (sid, t),
            )


def update_attempt_result(
    session_id: str,
    *,
    question_id: Optional[str],
    generation_id: Optional[str],
    score: int,
    weak_topics: List[str],
) -> None:
    sid = str(session_id).strip()
    if not sid:
        return
    qid = (question_id or "").strip()
    gid = (generation_id or "").strip()
    with _conn() as c:
        if qid:
            row = c.execute(
                """
                SELECT id FROM attempts
                WHERE session_id = ? AND question_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (sid, qid),
            ).fetchone()
        elif gid:
            row = c.execute(
                """
                SELECT id FROM attempts
                WHERE session_id = ? AND generation_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (sid, gid),
            ).fetchone()
        else:
            row = None
        if row is None:
            return
        c.execute(
            "UPDATE attempts SET score = ?, weak_topics_json = ? WHERE id = ?",
            (int(score), json.dumps(list(weak_topics), ensure_ascii=False), int(row["id"])),
        )


def get_recent_paper_ids(session_id: str, limit: int = 3) -> List[str]:
    """返回最近 N 张试卷的 paper_id（按创建时间倒序）。"""
    sid = str(session_id).strip()
    if not sid:
        return []
    with _conn() as c:
        rows = c.execute(
            """
            SELECT paper_id
            FROM papers
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (sid, int(limit)),
        ).fetchall()
    return [str(r["paper_id"]) for r in rows if str(r["paper_id"]).strip()]


def get_topic_baseline(session_id: str, window_papers: int = 3) -> Dict[str, Dict[str, Any]]:
    """
    按最近 N 张试卷，聚合每个 topic 的表现基线。
    返回 {topic: {avg_score, sample_count, high_count, low_count, difficulty_counts}}
    """
    sid = str(session_id).strip()
    if not sid:
        return {}
    paper_ids = get_recent_paper_ids(sid, window_papers)
    if not paper_ids:
        return {}
    placeholders = ",".join("?" for _ in paper_ids)
    params: List[Any] = [sid, *paper_ids]
    with _conn() as c:
        rows = c.execute(
            f"""
            SELECT topics_json, difficulty, score
            FROM attempts
            WHERE session_id = ?
              AND paper_id IN ({placeholders})
              AND score IS NOT NULL
            """,
            params,
        ).fetchall()
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        topics = json.loads(r["topics_json"] or "[]")
        score = float(r["score"])
        diff = str(r["difficulty"] or "").strip()
        for t in topics:
            topic = str(t).strip().lower()
            if not topic:
                continue
            rec = agg.setdefault(
                topic,
                {
                    "score_sum": 0.0,
                    "sample_count": 0,
                    "high_count": 0,
                    "low_count": 0,
                    "difficulty_counts": {"beginner": 0, "intermediate": 0, "advanced": 0},
                },
            )
            rec["score_sum"] += score
            rec["sample_count"] += 1
            if score >= 7.5:
                rec["high_count"] += 1
            if score < 4.5:
                rec["low_count"] += 1
            if diff in rec["difficulty_counts"]:
                rec["difficulty_counts"][diff] += 1
    out: Dict[str, Dict[str, Any]] = {}
    for topic, rec in agg.items():
        count = max(1, int(rec["sample_count"]))
        out[topic] = {
            "avg_score": round(float(rec["score_sum"]) / count, 4),
            "sample_count": int(rec["sample_count"]),
            "high_count": int(rec["high_count"]),
            "low_count": int(rec["low_count"]),
            "difficulty_counts": dict(rec["difficulty_counts"]),
        }
    return out
