"""
Nimbus Store — SQLite-backed task history and persistent queue.
"""

import sqlite3
import threading
import time
import os
from enum import Enum
from typing import Optional
from dataclasses import dataclass, asdict


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: Optional[int]
    prompt: str
    project: Optional[str]
    agent: Optional[str]
    status: TaskStatus
    result: Optional[str]
    cost_usd: float
    duration_ms: int
    session_id: Optional[str]
    created_at: float
    finished_at: Optional[float]
    telegram_msg_id: Optional[int]

    def to_dict(self):
        d = asdict(self)
        d["status"] = self.status.value
        return d


class NimbusStore:
    def __init__(self, db_path: str = "~/.nimbus/nimbus.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT NOT NULL,
                project TEXT,
                agent TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                result TEXT,
                cost_usd REAL DEFAULT 0.0,
                duration_ms INTEGER DEFAULT 0,
                session_id TEXT,
                created_at REAL NOT NULL,
                finished_at REAL,
                telegram_msg_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
        """)
        self.conn.commit()

    def create_task(self, prompt: str, project: str = None,
                    agent: str = None, telegram_msg_id: int = None) -> Task:
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO tasks (prompt, project, agent, status, created_at, telegram_msg_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (prompt, project, agent, TaskStatus.QUEUED.value, now, telegram_msg_id)
            )
            self.conn.commit()
        return Task(
            id=cur.lastrowid, prompt=prompt, project=project, agent=agent,
            status=TaskStatus.QUEUED, result=None, cost_usd=0.0,
            duration_ms=0, session_id=None, created_at=now,
            finished_at=None, telegram_msg_id=telegram_msg_id
        )

    def update_task(self, task_id: int, **kwargs):
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k == "status" and isinstance(v, TaskStatus):
                v = v.value
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(task_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals
            )
            self.conn.commit()

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def get_running_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at",
            (TaskStatus.RUNNING.value,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_queued_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at",
            (TaskStatus.QUEUED.value,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_recent_tasks(self, limit: int = 10) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_today_stats(self) -> dict:
        today = time.strftime("%Y-%m-%d")
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as queued,
                COALESCE(SUM(cost_usd), 0) as total_cost,
                COALESCE(SUM(duration_ms), 0) as total_duration
            FROM tasks
            WHERE date(created_at, 'unixepoch', 'localtime') = ?
        """, (today,)).fetchone()
        return dict(row)

    def next_queued(self) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at LIMIT 1",
            (TaskStatus.QUEUED.value,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def _row_to_task(self, row) -> Task:
        return Task(
            id=row["id"], prompt=row["prompt"], project=row["project"],
            agent=row["agent"], status=TaskStatus(row["status"]),
            result=row["result"], cost_usd=row["cost_usd"],
            duration_ms=row["duration_ms"], session_id=row["session_id"],
            created_at=row["created_at"], finished_at=row["finished_at"],
            telegram_msg_id=row["telegram_msg_id"]
        )

    def close(self):
        self.conn.close()
