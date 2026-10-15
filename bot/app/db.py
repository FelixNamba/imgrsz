"""SQLite storage: users, ledger (balance moves), jobs, events."""
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    source TEXT,
    balance INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,          -- +bonus / -charge, in р.
    reason TEXT NOT NULL,             -- welcome_bonus | job
    job_id INTEGER,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    image_info TEXT,
    request TEXT,
    plan TEXT,
    iterations INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,             -- draft | done | failed | refused
    price INTEGER,
    llm_tokens INTEGER NOT NULL DEFAULT 0,
    provider_cost_usd REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at INTEGER NOT NULL,
    finished_at INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    name TEXT NOT NULL,
    props TEXT,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    chat_id INTEGER PRIMARY KEY,
    username TEXT,
    added_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_name_ts ON events(name, ts);
CREATE INDEX IF NOT EXISTS idx_ledger_ts ON ledger(ts);
"""


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    # users / balance
    def ensure_user(self, tg_id: int, username: str | None, source: str | None, bonus: int) -> bool:
        """Create user with welcome bonus. Returns True if user is new."""
        now = int(time.time())
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO users(tg_id, username, source, balance, created_at) VALUES (?,?,?,?,?)",
                (tg_id, username, source, bonus, now),
            )
            if cur.rowcount:
                self.conn.execute(
                    "INSERT INTO ledger(tg_id, amount, reason, ts) VALUES (?,?,?,?)",
                    (tg_id, bonus, "welcome_bonus", now),
                )
                return True
            return False

    def balance(self, tg_id: int) -> int:
        row = self.one("SELECT balance FROM users WHERE tg_id=?", (tg_id,))
        return row["balance"] if row else 0

    def charge(self, tg_id: int, amount: int, job_id: int) -> int:
        """Atomically debit; returns new balance. Raises ValueError if insufficient."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                bal = self.conn.execute("SELECT balance FROM users WHERE tg_id=?", (tg_id,)).fetchone()["balance"]
                if bal < amount:
                    raise ValueError("insufficient balance")
                self.conn.execute("UPDATE users SET balance=balance-? WHERE tg_id=?", (amount, tg_id))
                self.conn.execute(
                    "INSERT INTO ledger(tg_id, amount, reason, job_id, ts) VALUES (?,?,?,?,?)",
                    (tg_id, -amount, "job", job_id, int(time.time())),
                )
                self.conn.execute("COMMIT")
                return bal - amount
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def drop_user(self, who: str) -> int | None:
        """Admin test helper: forget a user (by @username or tg_id) so the next /start is a new user
        with a fresh welcome bonus. Jobs and events stay for analytics. Returns the dropped tg_id."""
        who = who.strip().lstrip("@")
        row = self.one("SELECT tg_id FROM users WHERE tg_id=?", (int(who),)) if who.isdigit() else \
            self.one("SELECT tg_id FROM users WHERE lower(username)=?", (who.lower(),))
        if not row:
            return None
        with self.lock:
            self.conn.execute("DELETE FROM ledger WHERE tg_id=?", (row["tg_id"],))
            self.conn.execute("DELETE FROM users WHERE tg_id=?", (row["tg_id"],))
        return row["tg_id"]

    # jobs
    def create_job(self, tg_id: int, file_id: str, image_info: dict) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO jobs(tg_id, file_id, image_info, status, created_at) VALUES (?,?,?,?,?)",
                (tg_id, file_id, json.dumps(image_info, ensure_ascii=False), "draft", int(time.time())),
            )
            return cur.lastrowid

    def get_job(self, job_id: int):
        return self.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    def update_job(self, job_id: int, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        self.q(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def claim_job(self, job_id: int, tg_id: int) -> bool:
        """draft -> running, once (protects against double-tap on Confirm)."""
        with self.lock:
            cur = self.conn.execute(
                "UPDATE jobs SET status='running' WHERE id=? AND tg_id=? AND status='draft'", (job_id, tg_id)
            )
            return cur.rowcount == 1

    def add_job_cost(self, job_id: int, llm_tokens: int = 0, provider_cost_usd: float = 0.0):
        self.q(
            "UPDATE jobs SET llm_tokens=llm_tokens+?, provider_cost_usd=provider_cost_usd+? WHERE id=?",
            (llm_tokens, provider_cost_usd, job_id),
        )

    # admins (receive copies of results via the admin bot)
    def add_admin(self, chat_id: int, username: str):
        self.q("INSERT OR REPLACE INTO admins(chat_id, username, added_at) VALUES (?,?,?)", (chat_id, username, int(time.time())))

    def admin_chats(self) -> list[int]:
        return [r["chat_id"] for r in self.q("SELECT chat_id FROM admins")]

    # events
    def event(self, tg_id: int | None, name: str, **props):
        self.q(
            "INSERT INTO events(tg_id, name, props, ts) VALUES (?,?,?,?)",
            (tg_id, name, json.dumps(props, ensure_ascii=False) if props else None, int(time.time())),
        )
