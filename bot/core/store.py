import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from bot.config.guild_config import GuildConfig


@dataclass
class PlayerData:
    player_id: str
    username: str
    level: int
    server: int
    alliance_tag: str = None
    rank: str = None


def _support_ticket_text(support_channel_id: Optional[int]) -> str:
    if support_channel_id:
        return f"Open a support ticket in <#{support_channel_id}>."
    return "Open a support ticket using the support process configured by your admins."


class ProfileStore:
    """SQLite store supporting all profile schemas (union of features)."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._guild_config_cache: dict[int, GuildConfig] = {}
        self._cache_mtime: float = 0.0
        self._init_db()

    def _db_mtime(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except FileNotFoundError:
            return 0.0

    def _bust_stale_cache(self) -> None:
        """Drop the guild-config cache when the DB file changed on disk.

        The admin web UI runs as a separate process and writes guild configs
        straight to this same SQLite file. Because configs are resolved from
        an in-process cache here, external writes would otherwise go unnoticed
        until the bot restarts. Comparing the file mtime is cheap and lets the
        cache self-invalidate without IPC.
        """
        mtime = self._db_mtime()
        if mtime != self._cache_mtime:
            self._guild_config_cache.clear()
            self._cache_mtime = mtime

    def _init_db(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id INTEGER PRIMARY KEY,
                    bot_profile TEXT NOT NULL DEFAULT 'stfc_verifier',
                    verify_channel_id INTEGER,
                    log_channel_id INTEGER,
                    support_channel_id INTEGER,
                    verified_role_id INTEGER,
                    unverified_role_id INTEGER,
                    member_role_id INTEGER,
                    commodore_role_id INTEGER,
                    admiral_role_id INTEGER,
                    admin_role_id INTEGER,
                    ops71_plus_role_id INTEGER,
                    minimum_ops_level INTEGER,
                    stfc_server_number INTEGER,
                    update_check_hours INTEGER DEFAULT 24,
                    require_screenshot INTEGER DEFAULT 1,
                    manage_alliance_roles INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stfc_players (
                    user_id INTEGER PRIMARY KEY,
                    stfc_link TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    username TEXT,
                    level INTEGER,
                    server INTEGER,
                    alliance_tag TEXT,
                    verification_status TEXT DEFAULT 'verified',
                    verified_at TIMESTAMP,
                    rank TEXT,
                    alliance_role_id INTEGER,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS verification_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    admin_id INTEGER,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES stfc_players(user_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wizard_sessions (
                    user_id INTEGER PRIMARY KEY,
                    guild_id INTEGER,
                    step INTEGER DEFAULT 1,
                    stfc_link TEXT,
                    screenshot_data TEXT,
                    player_data_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)

            cursor = conn.execute("PRAGMA table_info(stfc_players)")
            columns = {row[1] for row in cursor.fetchall()}

            for col in ("verification_status", "verified_at", "rank", "alliance_role_id"):
                if col not in columns:
                    conn.execute(f"ALTER TABLE stfc_players ADD COLUMN {col} TEXT"
                                 if col in ("verification_status", "verified_at", "rank")
                                 else f"ALTER TABLE stfc_players ADD COLUMN {col} INTEGER")

            cursor = conn.execute("PRAGMA table_info(wizard_sessions)")
            wizard_columns = {row[1] for row in cursor.fetchall()}
            if "player_data_json" not in wizard_columns:
                conn.execute("ALTER TABLE wizard_sessions ADD COLUMN player_data_json TEXT")
            if "guild_id" not in wizard_columns:
                conn.execute("ALTER TABLE wizard_sessions ADD COLUMN guild_id INTEGER")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_wizard_views (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    view_type TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_rank_confirmations (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    member_name TEXT,
                    rank TEXT,
                    player_name TEXT,
                    alliance_tag TEXT
                )
            """)
            conn.commit()

    def get_guild_config(self, guild_id: int) -> Optional[GuildConfig]:
        self._bust_stale_cache()
        if guild_id in self._guild_config_cache:
            return self._guild_config_cache[guild_id]
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """SELECT guild_id, bot_profile, verify_channel_id, log_channel_id, support_channel_id,
                          verified_role_id, unverified_role_id, member_role_id, commodore_role_id,
                          admiral_role_id, admin_role_id, ops71_plus_role_id, minimum_ops_level,
                          stfc_server_number, update_check_hours, require_screenshot, manage_alliance_roles
                   FROM guild_configs WHERE guild_id = ?""",
                (guild_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            config = GuildConfig(
                guild_id=row[0],
                bot_profile=row[1],
                verify_channel_id=row[2],
                log_channel_id=row[3],
                support_channel_id=row[4],
                verified_role_id=row[5],
                unverified_role_id=row[6],
                member_role_id=row[7],
                commodore_role_id=row[8],
                admiral_role_id=row[9],
                admin_role_id=row[10],
                ops71_plus_role_id=row[11],
                minimum_ops_level=row[12],
                stfc_server_number=row[13],
                update_check_hours=row[14] if row[14] is not None else 24,
                require_screenshot=bool(row[15]) if row[15] is not None else True,
                manage_alliance_roles=bool(row[16]) if row[16] is not None else False,
            )
            self._guild_config_cache[guild_id] = config
            return config

    def save_guild_config(self, config: GuildConfig) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO guild_configs
                   (guild_id, bot_profile, verify_channel_id, log_channel_id, support_channel_id,
                    verified_role_id, unverified_role_id, member_role_id, commodore_role_id,
                    admiral_role_id, admin_role_id, ops71_plus_role_id, minimum_ops_level,
                    stfc_server_number, update_check_hours, require_screenshot, manage_alliance_roles)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    config.guild_id,
                    config.bot_profile,
                    config.verify_channel_id,
                    config.log_channel_id,
                    config.support_channel_id,
                    config.verified_role_id,
                    config.unverified_role_id,
                    config.member_role_id,
                    config.commodore_role_id,
                    config.admiral_role_id,
                    config.admin_role_id,
                    config.ops71_plus_role_id,
                    config.minimum_ops_level,
                    config.stfc_server_number,
                    config.update_check_hours,
                    1 if config.require_screenshot else 0,
                    1 if config.manage_alliance_roles else 0,
                ),
            )
            conn.commit()
        self._cache_mtime = self._db_mtime()
        self._guild_config_cache[config.guild_id] = config

    def delete_guild_config(self, guild_id: int) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM guild_configs WHERE guild_id = ?", (guild_id,))
            conn.commit()
        self._cache_mtime = self._db_mtime()
        self._guild_config_cache.pop(guild_id, None)

    def get_all_guild_configs(self) -> list[GuildConfig]:
        self._bust_stale_cache()
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """SELECT guild_id, bot_profile, verify_channel_id, log_channel_id, support_channel_id,
                          verified_role_id, unverified_role_id, member_role_id, commodore_role_id,
                          admiral_role_id, admin_role_id, ops71_plus_role_id, minimum_ops_level,
                          stfc_server_number, update_check_hours, require_screenshot, manage_alliance_roles
                   FROM guild_configs"""
            )
            configs = []
            for row in cursor.fetchall():
                config = GuildConfig(
                    guild_id=row[0],
                    bot_profile=row[1],
                    verify_channel_id=row[2],
                    log_channel_id=row[3],
                    support_channel_id=row[4],
                    verified_role_id=row[5],
                    unverified_role_id=row[6],
                    member_role_id=row[7],
                    commodore_role_id=row[8],
                    admiral_role_id=row[9],
                    admin_role_id=row[10],
                    ops71_plus_role_id=row[11],
                    minimum_ops_level=row[12],
                    stfc_server_number=row[13],
                    update_check_hours=row[14] if row[14] is not None else 24,
                    require_screenshot=bool(row[15]) if row[15] is not None else True,
                    manage_alliance_roles=bool(row[16]) if row[16] is not None else False,
                )
                self._guild_config_cache[config.guild_id] = config
                configs.append(config)
            return configs

    def is_player_id_taken(self, player_id: str, exclude_user_id: int = None) -> bool:
        with sqlite3.connect(self.path) as conn:
            if exclude_user_id is not None:
                cursor = conn.execute(
                    "SELECT 1 FROM stfc_players WHERE player_id = ? AND user_id != ?",
                    (player_id, exclude_user_id),
                )
            else:
                cursor = conn.execute(
                    "SELECT 1 FROM stfc_players WHERE player_id = ?",
                    (player_id,),
                )
            return cursor.fetchone() is not None

    def save_pending_wizard_view(self, message_id: int, channel_id: int, user_id: int, view_type: str):
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pending_wizard_views
                (message_id, channel_id, user_id, view_type)
                VALUES (?, ?, ?, ?)
            """, (message_id, channel_id, user_id, view_type))
            conn.commit()

    def get_all_pending_wizard_views(self) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT message_id, channel_id, user_id, view_type FROM pending_wizard_views"
            )
            return [{
                "message_id": row[0],
                "channel_id": row[1],
                "user_id": row[2],
                "view_type": row[3],
            } for row in cursor.fetchall()]

    def delete_pending_wizard_view(self, message_id: int):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM pending_wizard_views WHERE message_id = ?", (message_id,))
            conn.commit()

    def get_pending_wizard_views_by_user(self, user_id: int) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT message_id, channel_id, user_id, view_type FROM pending_wizard_views WHERE user_id = ?",
                (user_id,),
            )
            return [{
                "message_id": row[0],
                "channel_id": row[1],
                "user_id": row[2],
                "view_type": row[3],
            } for row in cursor.fetchall()]

    def delete_pending_wizard_views_by_user(self, user_id: int):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM pending_wizard_views WHERE user_id = ?", (user_id,))
            conn.commit()

    def save_pending_rank_confirmation(self, message_id: int, channel_id: int, user_id: int,
                                       member_name: str, rank: str, player_name: str,
                                       alliance_tag: str):
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pending_rank_confirmations
                (message_id, channel_id, user_id, member_name, rank, player_name, alliance_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (message_id, channel_id, user_id, member_name, rank, player_name, alliance_tag))
            conn.commit()

    def get_all_pending_rank_confirmations(self) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT message_id, channel_id, user_id, member_name, rank, player_name, alliance_tag "
                "FROM pending_rank_confirmations"
            )
            return [{
                "message_id": row[0],
                "channel_id": row[1],
                "user_id": row[2],
                "member_name": row[3],
                "rank": row[4],
                "player_name": row[5],
                "alliance_tag": row[6],
            } for row in cursor.fetchall()]

    def delete_pending_rank_confirmation(self, message_id: int):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM pending_rank_confirmations WHERE message_id = ?", (message_id,))
            conn.commit()

    def store_stfc_player(
        self,
        user_id: int,
        stfc_link: str,
        player_data: "PlayerData",
    ):
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute("SELECT 1 FROM stfc_players WHERE user_id = ?", (user_id,))
            exists = cursor.fetchone() is not None

            if exists:
                old = conn.execute(
                    "SELECT alliance_role_id FROM stfc_players WHERE user_id = ?", (user_id,)
                ).fetchone()
                old_role_id = old[0] if old else None

                conn.execute("""
                    UPDATE stfc_players
                    SET stfc_link = ?, player_id = ?, username = ?, level = ?, server = ?,
                        alliance_tag = ?, rank = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (
                    stfc_link,
                    player_data.player_id,
                    player_data.username,
                    player_data.level,
                    player_data.server,
                    player_data.alliance_tag,
                    getattr(player_data, "rank", None),
                    user_id,
                ))

                if old_role_id is not None:
                    conn.execute(
                        "UPDATE stfc_players SET alliance_role_id = ? WHERE user_id = ?",
                        (old_role_id, user_id),
                    )
            else:
                conn.execute("""
                    INSERT INTO stfc_players
                    (user_id, stfc_link, player_id, username, level, server, alliance_tag, rank, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    user_id,
                    stfc_link,
                    player_data.player_id,
                    player_data.username,
                    player_data.level,
                    player_data.server,
                    player_data.alliance_tag,
                    getattr(player_data, "rank", None),
                ))
            conn.commit()

    def get_all_players(self) -> list[tuple]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT user_id, stfc_link, player_id FROM stfc_players"
            )
            return cursor.fetchall()

    def get_player_data(self, user_id: int) -> Optional[tuple]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT username, level, server, alliance_tag, rank FROM stfc_players WHERE user_id = ?",
                (user_id,),
            )
            return cursor.fetchone()

    def get_verification_status(self, user_id: int) -> Optional[str]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT verification_status FROM stfc_players WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def is_user_verified(self, user_id: int) -> bool:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT user_id FROM stfc_players WHERE user_id = ? AND verification_status = 'verified'",
                (user_id,),
            )
            return cursor.fetchone() is not None

    def mark_verified(self, user_id: int):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE stfc_players SET verification_status = 'verified', verified_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()

    def delete_verification(self, user_id: int):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM stfc_players WHERE user_id = ?", (user_id,))
            conn.commit()

    def log_verification_action(self, user_id: int, action: str, admin_id: int = None, reason: str = None):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO verification_logs (user_id, action, admin_id, reason)
                   VALUES (?, ?, ?, ?)""",
                (user_id, action, admin_id, reason),
            )
            conn.commit()

    def create_wizard_session(self, user_id: int, guild_id: Optional[int] = None):
        expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO wizard_sessions (user_id, guild_id, step, created_at, expires_at)
                   VALUES (?, ?, 1, CURRENT_TIMESTAMP, ?)""",
                (user_id, guild_id, expires_at),
            )
            conn.commit()

    def get_wizard_session(self, user_id: int) -> Optional[dict]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """SELECT user_id, step, stfc_link, screenshot_data, created_at, expires_at, player_data_json, guild_id
                   FROM wizard_sessions WHERE user_id = ?""",
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            expires_at = datetime.fromisoformat(row[5])
            if datetime.now() > expires_at:
                conn.execute("DELETE FROM wizard_sessions WHERE user_id = ?", (user_id,))
                conn.commit()
                return None
            return {
                "user_id": row[0],
                "step": row[1],
                "stfc_link": row[2],
                "screenshot_data": row[3],
                "created_at": row[4],
                "expires_at": row[5],
                "player_data_json": row[6],
                "guild_id": row[7],
            }

    def update_wizard_session(self, user_id: int, step: int = None, stfc_link: str = None,
                               screenshot_data: str = None, player_data_json: str = None):
        updates = []
        params = []
        if step is not None:
            updates.append("step = ?")
            params.append(step)
        if stfc_link is not None:
            updates.append("stfc_link = ?")
            params.append(stfc_link)
        if screenshot_data is not None:
            updates.append("screenshot_data = ?")
            params.append(screenshot_data)
        if player_data_json is not None:
            updates.append("player_data_json = ?")
            params.append(player_data_json)
        if not updates:
            return
        params.append(user_id)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"UPDATE wizard_sessions SET {', '.join(updates)} WHERE user_id = ?",
                params,
            )
            conn.commit()

    def get_wizard_player_data(self, user_id: int):
        session = self.get_wizard_session(user_id)
        if not session or not session.get("player_data_json"):
            return None
        try:
            data = json.loads(session["player_data_json"])
            return PlayerData(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def delete_wizard_session(self, user_id: int):
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM wizard_sessions WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_user_alliance_role_id(self, user_id: int) -> Optional[int]:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT alliance_role_id FROM stfc_players WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row[0] if row else None

    def update_user_alliance_role_id(self, user_id: int, alliance_role_id: Optional[int]):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE stfc_players SET alliance_role_id = ? WHERE user_id = ?",
                (alliance_role_id, user_id),
            )
            conn.commit()

    def get_user_full_data(self, user_id: int) -> Optional[tuple]:
        with sqlite3.connect(self.path) as conn:
            return conn.execute(
                "SELECT username, level, server, alliance_tag, rank, alliance_role_id FROM stfc_players WHERE user_id = ?",
                (user_id,),
            ).fetchone()

    def get_user_stfc_link(self, user_id: int) -> Optional[str]:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT stfc_link FROM stfc_players WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row[0] if row else None
