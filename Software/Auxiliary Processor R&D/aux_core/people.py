from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PersonMatch:
    person_id: str
    name: str
    score: float


class PersonStore:
    """Bounded local store for enrolled identities and explicit memories.

    Raw face images are intentionally not retained.  The database stores only a
    normalized face embedding, the person's chosen name, timestamps, and a small
    set of explicit text memories.
    """

    def __init__(self, cfg: dict[str, Any], root: Path) -> None:
        self.cfg = dict(cfg or {})
        p = Path(self.cfg.get("database_path", "runtime/people.sqlite3"))
        self.path = p if p.is_absolute() else (Path(root) / p).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_people = max(1, int(self.cfg.get("max_people", 50)))
        self.max_memories = max(1, int(self.cfg.get("max_memories_per_person", 12)))
        self.max_memory_chars = max(32, int(self.cfg.get("max_memory_chars", 400)))
        self.max_topic_chars = max(80, int(self.cfg.get("max_topic_chars", 360)))
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=5.0)
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @contextmanager
    def _db(self):
        con = self._connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._lock, self._db() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS people (
                    person_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS people_name_ci ON people(lower(name));
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memories_person_created ON memories(person_id, created_at DESC);
                """
            )
            # v0.3.5 migration: one intentionally lossy rolling topic note per
            # person. It is separate from explicit memories and is overwritten
            # after each successful conversation turn.
            cols = {str(row[1]) for row in con.execute("PRAGMA table_info(people)").fetchall()}
            if "last_topic" not in cols:
                con.execute("ALTER TABLE people ADD COLUMN last_topic TEXT")
            if "last_topic_at" not in cols:
                con.execute("ALTER TABLE people ADD COLUMN last_topic_at REAL")

    @staticmethod
    def _blob(vec: np.ndarray) -> tuple[bytes, int]:
        arr = np.asarray(vec, dtype=np.float32).reshape(-1)
        n = float(np.linalg.norm(arr))
        if n <= 1e-8 or not np.isfinite(n):
            raise ValueError("invalid_face_embedding")
        arr = arr / n
        return arr.tobytes(), int(arr.size)

    @staticmethod
    def _vec(blob: bytes, dim: int) -> np.ndarray:
        arr = np.frombuffer(blob, dtype=np.float32, count=int(dim)).copy()
        n = float(np.linalg.norm(arr))
        return arr if n <= 1e-8 else arr / n

    def register(self, name: str, embedding: np.ndarray) -> dict[str, Any]:
        name = " ".join(str(name).strip().split())
        if not name or len(name) > 80:
            raise ValueError("invalid_person_name")
        blob, dim = self._blob(embedding)
        now = time.time()
        with self._lock, self._db() as con:
            row = con.execute("SELECT person_id FROM people WHERE lower(name)=lower(?)", (name,)).fetchone()
            if row:
                person_id = str(row[0])
                con.execute(
                    "UPDATE people SET name=?, embedding=?, embedding_dim=?, last_seen=?, seen_count=seen_count+1 WHERE person_id=?",
                    (name, blob, dim, now, person_id),
                )
            else:
                person_id = str(uuid.uuid4())
                con.execute(
                    "INSERT INTO people(person_id,name,embedding,embedding_dim,created_at,last_seen,seen_count) VALUES(?,?,?,?,?,?,1)",
                    (person_id, name, blob, dim, now, now),
                )
            self._enforce_people_cap(con, exclude=person_id)
        return self.get(person_id) or {"person_id": person_id, "name": name}

    def _enforce_people_cap(self, con, *, exclude: str | None = None) -> None:
        count = int(con.execute("SELECT COUNT(*) FROM people").fetchone()[0])
        excess = max(0, count - self.max_people)
        if not excess:
            return
        if exclude:
            rows = con.execute(
                "SELECT person_id FROM people WHERE person_id<>? ORDER BY last_seen ASC, created_at ASC LIMIT ?",
                (exclude, excess),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT person_id FROM people ORDER BY last_seen ASC, created_at ASC LIMIT ?",
                (excess,),
            ).fetchall()
        for (pid,) in rows:
            con.execute("DELETE FROM people WHERE person_id=?", (pid,))

    def match(self, embedding: np.ndarray, threshold: float) -> PersonMatch | None:
        probe = np.asarray(embedding, dtype=np.float32).reshape(-1)
        n = float(np.linalg.norm(probe))
        if n <= 1e-8:
            return None
        probe = probe / n
        best: PersonMatch | None = None
        with self._lock, self._db() as con:
            rows = con.execute("SELECT person_id,name,embedding,embedding_dim FROM people").fetchall()
        for pid, name, blob, dim in rows:
            if int(dim) != int(probe.size):
                continue
            score = float(np.dot(probe, self._vec(blob, dim)))
            if best is None or score > best.score:
                best = PersonMatch(str(pid), str(name), score)
        return best if best is not None and best.score >= float(threshold) else None

    def touch(self, person_id: str) -> None:
        with self._lock, self._db() as con:
            con.execute(
                "UPDATE people SET last_seen=?, seen_count=seen_count+1 WHERE person_id=?",
                (time.time(), str(person_id)),
            )

    def remember(self, person_id: str, text: str) -> dict[str, Any]:
        text = " ".join(str(text).strip().split())[: self.max_memory_chars]
        if not text:
            raise ValueError("empty_memory")
        now = time.time()
        with self._lock, self._db() as con:
            if not con.execute("SELECT 1 FROM people WHERE person_id=?", (person_id,)).fetchone():
                raise KeyError(person_id)
            con.execute("INSERT INTO memories(person_id,text,created_at) VALUES(?,?,?)", (person_id, text, now))
            rows = con.execute(
                "SELECT memory_id FROM memories WHERE person_id=? ORDER BY created_at DESC, memory_id DESC",
                (person_id,),
            ).fetchall()
            for (mid,) in rows[self.max_memories :]:
                con.execute("DELETE FROM memories WHERE memory_id=?", (mid,))
        return {"person_id": person_id, "text": text, "created_at": now}

    def memories(self, person_id: str) -> list[dict[str, Any]]:
        with self._lock, self._db() as con:
            rows = con.execute(
                "SELECT memory_id,text,created_at FROM memories WHERE person_id=? ORDER BY created_at ASC, memory_id ASC",
                (person_id,),
            ).fetchall()
        return [{"memory_id": int(mid), "text": str(text), "created_at": float(ts)} for mid, text, ts in rows]

    def set_last_topic(self, person_id: str, text: str) -> dict[str, Any]:
        """Replace the person's single rolling, approximate conversation topic.

        This is deliberately not a transcript and does not consume an explicit
        memory slot. It exists only to provide light continuity after transient
        conversation history is cleared.
        """
        text = " ".join(str(text).strip().split())[: self.max_topic_chars]
        if not text:
            raise ValueError("empty_topic")
        now = time.time()
        with self._lock, self._db() as con:
            cur = con.execute(
                "UPDATE people SET last_topic=?, last_topic_at=? WHERE person_id=?",
                (text, now, str(person_id)),
            )
            if not cur.rowcount:
                raise KeyError(person_id)
        return {"person_id": str(person_id), "text": text, "updated_at": now}

    def last_topic(self, person_id: str) -> dict[str, Any] | None:
        with self._lock, self._db() as con:
            row = con.execute(
                "SELECT last_topic,last_topic_at FROM people WHERE person_id=?",
                (str(person_id),),
            ).fetchone()
        if not row or not row[0]:
            return None
        return {"text": str(row[0]), "updated_at": float(row[1] or 0.0)}

    def get(self, person_id: str) -> dict[str, Any] | None:
        with self._lock, self._db() as con:
            row = con.execute(
                "SELECT person_id,name,created_at,last_seen,seen_count,last_topic,last_topic_at FROM people WHERE person_id=?",
                (str(person_id),),
            ).fetchone()
        if not row:
            return None
        return {
            "person_id": str(row[0]),
            "name": str(row[1]),
            "created_at": float(row[2]),
            "last_seen": float(row[3]),
            "seen_count": int(row[4]),
            "last_topic": str(row[5]) if row[5] else None,
            "last_topic_at": float(row[6]) if row[6] is not None else None,
        }

    def delete(self, person_id: str) -> bool:
        with self._lock, self._db() as con:
            cur = con.execute("DELETE FROM people WHERE person_id=?", (str(person_id),))
            return bool(cur.rowcount)

    def list_people(self) -> list[dict[str, Any]]:
        with self._lock, self._db() as con:
            rows = con.execute(
                "SELECT person_id,name,created_at,last_seen,seen_count FROM people ORDER BY last_seen DESC"
            ).fetchall()
        return [
            {"person_id": str(pid), "name": str(name), "created_at": float(created), "last_seen": float(seen), "seen_count": int(count)}
            for pid, name, created, seen, count in rows
        ]

    def counts(self) -> dict[str, int]:
        with self._lock, self._db() as con:
            people = int(con.execute("SELECT COUNT(*) FROM people").fetchone()[0])
            memories = int(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        return {"people": people, "memories": memories}
