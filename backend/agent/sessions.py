"""SDK memory and a deliberately separate, sanitized user-visible transcript."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from backend.agent.config import AgentFault


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS welding_sessions (
                    id TEXT PRIMARY KEY, generation INTEGER NOT NULL DEFAULT 0, active_job TEXT);
                CREATE TABLE IF NOT EXISTS welding_chat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    role TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS welding_chat_session ON welding_chat(session_id, id);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self):
        sid = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO welding_sessions(id) VALUES (?)", (sid,))
        return sid

    def get(self, sid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM welding_sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise AgentFault("session_not_found", "대화를 찾을 수 없습니다. 새 대화를 시작해주세요.", 404)
        return dict(row)

    def append(self, sid, role, text):
        with self.connect() as db:
            db.execute("INSERT INTO welding_chat(session_id, role, text) VALUES (?, ?, ?)", (sid, role, text))

    def history(self, sid):
        session = self.get(sid)
        with self.connect() as db:
            messages = [dict(row) for row in db.execute(
                "SELECT role, text, at FROM welding_chat WHERE session_id=? ORDER BY id", (sid,))]
        return {"session_id": sid, "active_job_id": session["active_job"], "messages": messages}

    def sdk_session(self, sid, job_id):
        from agents import SQLiteSession
        generation = self.get(sid)["generation"]
        job = str(job_id) if job_id else None
        with self.connect() as db:
            db.execute("UPDATE welding_sessions SET active_job=? WHERE id=?", (job, sid))
        # A new scene cannot accidentally inherit old region IDs; same-job follow-ups retain memory.
        return SQLiteSession(f"{sid}:{generation}:{job or 'no-job'}", db_path=str(self.path))

    async def reset(self, sid):
        from agents import SQLiteSession
        self.get(sid)
        with self.connect() as db:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='agent_sessions'").fetchone()
            ids = [r[0] for r in db.execute("SELECT session_id FROM agent_sessions WHERE session_id LIKE ?",
                                           (sid + ":%",))] if exists else []
        for session_id in ids:
            memory = SQLiteSession(session_id, db_path=str(self.path))
            try:
                await memory.clear_session()
            finally:
                memory.close()
        with self.connect() as db:
            db.execute("DELETE FROM welding_chat WHERE session_id=?", (sid,))
            db.execute("UPDATE welding_sessions SET generation=generation+1, active_job=NULL WHERE id=?", (sid,))
