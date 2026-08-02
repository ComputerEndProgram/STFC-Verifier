from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AdminSession:
    token: str
    user_id: int
    access_token: str
    refresh_token: str | None
    csrf_token: str
    user: dict
    expires_at: datetime
    updated_at: datetime

    @property
    def expired(self) -> bool:
        return _utcnow() >= self.expires_at

    def touch(self) -> None:
        self.updated_at = _utcnow()


class SessionStore:
    """Server-side web sessions stored alongside the bot's SQLite database."""

    def __init__(self, db_path: str, ttl_days: int = 30) -> None:
        self.db_path = db_path
        self.ttl = timedelta(days=ttl_days)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    csrf_token TEXT NOT NULL,
                    user_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "DELETE FROM admin_sessions WHERE updated_at < ?",
                ((_utcnow() - self.ttl).isoformat(),),
            )
            conn.commit()

    def create(
        self,
        *,
        user: dict,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
    ) -> AdminSession:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        expires_at = (
            _utcnow() + timedelta(seconds=expires_in)
            if expires_in
            else _utcnow() + self.ttl
        )
        now = _utcnow()
        session = AdminSession(
            token=token,
            user_id=int(user["id"]),
            access_token=access_token,
            refresh_token=refresh_token,
            csrf_token=csrf,
            user=user,
            expires_at=expires_at,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO admin_sessions
                    (token, user_id, access_token, refresh_token, csrf_token, user_json, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    session.user_id,
                    access_token,
                    refresh_token,
                    csrf,
                    json.dumps(user),
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.commit()
        return session

    def get(self, token: str) -> AdminSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM admin_sessions WHERE token = ?", (token,)
            ).fetchone()
        if row is None:
            return None
        return AdminSession(
            token=row["token"],
            user_id=row["user_id"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            csrf_token=row["csrf_token"],
            user=json.loads(row["user_json"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update(
        self, session: AdminSession, *, access_token: str, expires_in: int | None
    ) -> None:
        session.access_token = access_token
        session.expires_at = (
            _utcnow() + timedelta(seconds=expires_in)
            if expires_in
            else session.expires_at
        )
        session.touch()
        with self._connect() as conn:
            conn.execute(
                "UPDATE admin_sessions SET access_token = ?, expires_at = ?, updated_at = ? WHERE token = ?",
                (
                    session.access_token,
                    session.expires_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.token,
                ),
            )
            conn.commit()

    def delete(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            conn.commit()
