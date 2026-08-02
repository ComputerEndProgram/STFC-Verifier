from __future__ import annotations

from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from bot.config import env
from bot.config.settings import Settings


@dataclass(frozen=True, slots=True)
class AdminWebConfig:
    bot_settings: Settings
    client_id: str
    client_secret: str
    session_secret: str
    base_url: str
    host: str
    port: int
    cookie_secure: bool
    session_ttl_days: int = 30

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/callback"

    @property
    def oauth_scopes(self) -> str:
        return "identify guilds"

    @property
    def cookie_name(self) -> str:
        return "admin_web_session"

    @classmethod
    def from_env(cls) -> AdminWebConfig:
        load_dotenv(find_dotenv(usecwd=True))
        base_url = (
            env.optional("ADMIN_WEB_BASE_URL") or "http://127.0.0.1:8787"
        ).rstrip("/")
        cookie_secure = env.optional("ADMIN_WEB_COOKIE_SECURE")
        if cookie_secure is None:
            cookie_secure = base_url.startswith("https://")
        else:
            cookie_secure = cookie_secure.lower() in ("1", "true", "yes", "on")
        return cls(
            bot_settings=Settings.from_env(),
            client_id=env.required("DISCORD_CLIENT_ID"),
            client_secret=env.required("DISCORD_CLIENT_SECRET"),
            session_secret=env.required("ADMIN_WEB_SESSION_SECRET"),
            base_url=base_url,
            host=env.optional("ADMIN_WEB_HOST") or "127.0.0.1",
            port=int(env.optional("ADMIN_WEB_PORT") or "8787"),
            cookie_secure=cookie_secure,
            session_ttl_days=int(env.optional("ADMIN_WEB_SESSION_TTL_DAYS") or "30"),
        )
