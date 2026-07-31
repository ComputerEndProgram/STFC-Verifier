from __future__ import annotations

from urllib.parse import urlencode

import httpx

API_BASE = "https://discord.com/api/v10"
OAUTH_TOKEN_URL = f"{API_BASE}/oauth2/token"
OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
CDN_BASE = "https://cdn.discordapp.com"

ADMINISTRATOR = 1 << 3
MANAGE_GUILD = 1 << 5


def has_manage_guild(permissions: int, owner: bool = False) -> bool:
    return owner or bool(permissions & (ADMINISTRATOR | MANAGE_GUILD))


def guild_icon_url(guild: dict) -> str | None:
    icon = guild.get("icon")
    if not icon:
        return None
    return f"{CDN_BASE}/icons/{guild['id']}/{icon}.png?size=128"


def user_avatar_url(user: dict) -> str | None:
    avatar = user.get("avatar")
    if not avatar:
        return None
    return f"{CDN_BASE}/avatars/{user['id']}/{avatar}.png?size=128"


class DiscordAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DiscordAPI:
    """Minimal Discord REST client for OAuth + guild membership lookups."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        bot_token: str,
        scopes: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.bot_token = bot_token
        self.scopes = scopes
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def authorize_url(self, state: str) -> str:
        params = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": self.scopes,
                "state": state,
            }
        )
        return f"{OAUTH_AUTHORIZE_URL}?{params}"

    async def _token_request(self, data: dict) -> dict:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with await self._http() as client:
            resp = await client.post(OAUTH_TOKEN_URL, data=data, headers=headers)
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord token exchange failed (HTTP {resp.status_code})", resp.status_code
            )
        return resp.json()

    async def exchange_code(self, code: str) -> dict:
        return await self._token_request(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        )

    async def refresh_access_token(self, refresh_token: str) -> dict:
        return await self._token_request(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    async def get_user(self, access_token: str) -> dict:
        return await self._bearer_get("/users/@me", access_token)

    async def get_user_guilds(self, access_token: str) -> list[dict]:
        return await self._bearer_get("/users/@me/guilds", access_token)

    async def _bearer_get(self, path: str, access_token: str) -> dict | list[dict]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with await self._http() as client:
            resp = await client.get(f"{API_BASE}{path}", headers=headers)
        if resp.status_code == 401:
            raise DiscordAPIError("Discord access token rejected (HTTP 401)", 401)
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord API GET {path} failed (HTTP {resp.status_code})", resp.status_code
            )
        return resp.json()

    async def get_bot_guild_ids(self) -> set[int]:
        """Guild IDs the bot is a member of.

        Fetched fresh on every call so permission checks can't go stale.
        """
        headers = {"Authorization": f"Bot {self.bot_token}"}
        async with await self._http() as client:
            resp = await client.get(f"{API_BASE}/users/@me/guilds", headers=headers)
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord bot guild lookup failed (HTTP {resp.status_code})", resp.status_code
            )
        return {int(g["id"]) for g in resp.json()}
