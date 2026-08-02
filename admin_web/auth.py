from __future__ import annotations

import logging
import secrets

from fastapi import Request
from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer

from admin_web.discord_api import DiscordAPI, DiscordAPIError, has_manage_guild
from admin_web.sessions import AdminSession, SessionStore
from admin_web.config import AdminWebConfig
from bot.core.store import ProfileStore

log = logging.getLogger("admin_web")

STATE_COOKIE = "admin_web_oauth_state"
STATE_TTL_SECONDS = 600


class LoginRequired(Exception):
    """Redirect the user to /login."""


class AccessDenied(Exception):
    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message)
        self.message = message


class AdminContext:
    def __init__(
        self,
        cfg: AdminWebConfig,
        sessions: SessionStore,
        store: ProfileStore,
        discord: DiscordAPI,
    ) -> None:
        self.cfg = cfg
        self.sessions = sessions
        self.store = store
        self.discord = discord
        self.serializer = URLSafeTimedSerializer(cfg.session_secret)

    # -- OAuth state -------------------------------------------------------

    def make_state(self) -> tuple[str, str]:
        """Return (inner_state, signed_token).

        The inner state goes to Discord as the OAuth ``state`` parameter;
        the signed token is stored in the cookie. On the callback Discord
        echoes back the inner state, which is compared against the token.
        """
        inner = secrets.token_urlsafe(16)
        token = self.serializer.dumps({"state": inner})
        return inner, token

    def verify_state(self, cookie_state: str, returned_state: str) -> bool:
        try:
            payload = self.serializer.loads(cookie_state, max_age=STATE_TTL_SECONDS)
        except (BadSignature, BadTimeSignature):
            return False
        return secrets.compare_digest(str(payload.get("state")), returned_state)

    # -- Session cookies ---------------------------------------------------

    def sign_cookie(self, token: str) -> str:
        return self.serializer.dumps({"token": token})

    def read_cookie(self, request: Request) -> AdminSession | None:
        raw = request.cookies.get(self.cfg.cookie_name)
        if not raw:
            return None
        try:
            payload = self.serializer.loads(raw)
        except (BadSignature, BadTimeSignature):
            return None
        token = payload.get("token")
        if not token:
            return None
        return self.sessions.get(token)

    def set_session_cookie(self, response, session: AdminSession) -> None:
        response.set_cookie(
            self.cfg.cookie_name,
            self.sign_cookie(session.token),
            max_age=86400 * self.cfg.session_ttl_days,
            httponly=True,
            secure=self.cfg.cookie_secure,
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(self, response) -> None:
        response.delete_cookie(self.cfg.cookie_name, path="/")

    def require_login(self, request: Request) -> AdminSession:
        session = self.read_cookie(request)
        if session is None:
            raise LoginRequired()
        return session

    # -- Discord permission checks -----------------------------------------

    async def _try_refresh(self, session: AdminSession) -> bool:
        if not session.refresh_token:
            return False
        try:
            data = await self.discord.refresh_access_token(session.refresh_token)
        except DiscordAPIError:
            return False
        self.sessions.update(
            session,
            access_token=data["access_token"],
            expires_in=data.get("expires_in"),
        )
        return True

    async def _user_guilds(self, request: Request, session: AdminSession) -> list[dict]:
        """Fresh guild list from Discord, retrying once after a token refresh."""
        try:
            return await self.discord.get_user_guilds(session.access_token)
        except DiscordAPIError as exc:
            if exc.status == 401:
                if await self._try_refresh(session):
                    try:
                        return await self.discord.get_user_guilds(session.access_token)
                    except DiscordAPIError:
                        pass
                self.sessions.delete(session.token)
                raise LoginRequired()
            log.warning(
                "Discord permission check failed for user %s: %s", session.user_id, exc
            )
            raise AccessDenied(
                "Could not reach Discord to verify your permissions — try again later."
            ) from exc

    async def accessible_guilds(self, request: Request, session: AdminSession) -> list[dict]:
        """Guilds where the user can manage AND the bot is present.

        The user's membership and permissions are re-fetched from Discord on
        every request — never trusted from a login-time snapshot.
        """
        user_guilds = await self._user_guilds(request, session)
        try:
            bot_ids = await self.discord.get_bot_guild_ids()
        except DiscordAPIError as exc:
            raise AccessDenied(
                "Could not verify the bot's server membership — try again later."
            ) from exc
        return [
            guild
            for guild in user_guilds
            if int(guild["id"]) in bot_ids
            and has_manage_guild(int(guild.get("permissions") or 0), bool(guild.get("owner")))
        ]

    async def require_guild(self, request: Request, guild_id: int) -> dict:
        """Server-side permission gate for a single guild, checked per request."""
        session = self.require_login(request)
        user_guilds = await self._user_guilds(request, session)
        try:
            bot_ids = await self.discord.get_bot_guild_ids()
        except DiscordAPIError as exc:
            raise AccessDenied(
                "Could not verify the bot's server membership — try again later."
            ) from exc

        guild = next((g for g in user_guilds if int(g["id"]) == guild_id), None)
        if guild is None:
            raise AccessDenied("You are not a member of this server.")
        if guild_id not in bot_ids:
            raise AccessDenied("The verification bot is not present in this server.")
        if not has_manage_guild(int(guild.get("permissions") or 0), bool(guild.get("owner"))):
            raise AccessDenied("You need Manage Server or Administrator permission for this server.")
        return guild
