from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import httpx

API_BASE = "https://discord.com/api/v10"
OAUTH_TOKEN_URL = f"{API_BASE}/oauth2/token"
OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
CDN_BASE = "https://cdn.discordapp.com"

ADMINISTRATOR = 1 << 3
MANAGE_GUILD = 1 << 5

# Permission bits the bot needs to run verification (roles, nicknames,
# messages, embeds, attachments, message history).
BOT_PERMISSIONS = 402769920
BOT_OAUTH_SCOPE = "bot applications.commands"

TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    label: str,
    max_retries: int = 2,
) -> httpx.Response:
    """Idempotent GET with a few retries on transient Discord failures.

    Network errors and rate-limit/5xx responses are retried with a short
    backoff; everything else is returned for the caller to handle.
    """
    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url, headers=headers)
        except httpx.TransportError as exc:
            if attempt == max_retries:
                raise DiscordAPIError(
                    f"Discord GET {label} failed (network error)"
                ) from exc
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if resp.status_code in TRANSIENT_STATUSES and attempt < max_retries:
            retry_after = resp.headers.get("retry-after")
            delay = float(retry_after) if retry_after else 0.5 * (attempt + 1)
            await asyncio.sleep(delay)
            continue
        return resp
    raise AssertionError("unreachable")


def has_manage_guild(permissions: int, owner: bool = False) -> bool:
    return owner or bool(permissions & (ADMINISTRATOR | MANAGE_GUILD))


def guild_icon_url(guild: dict) -> str | None:
    icon = guild.get("icon")
    if not icon:
        return None
    return f"{CDN_BASE}/icons/{guild['id']}/{icon}.png?size=128"


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
        if self._client is None or self._client.is_closed:
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

    def bot_invite_url(self) -> str:
        """OAuth2 URL to invite the bot into a server."""
        params = urlencode(
            {
                "client_id": self.client_id,
                "permissions": BOT_PERMISSIONS,
                "scope": BOT_OAUTH_SCOPE,
            }
        )
        return f"{OAUTH_AUTHORIZE_URL}?{params}"

    async def _token_request(self, data: dict) -> dict:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        client = await self._http()
        resp = await client.post(OAUTH_TOKEN_URL, data=data, headers=headers)
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord token exchange failed (HTTP {resp.status_code})",
                resp.status_code,
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
        resp = await _get_with_retry(
            await self._http(), f"{API_BASE}{path}", headers, label=path
        )
        if resp.status_code == 401:
            raise DiscordAPIError("Discord access token rejected (HTTP 401)", 401)
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord API GET {path} failed (HTTP {resp.status_code})",
                resp.status_code,
            )
        return resp.json()

    async def get_bot_guild_ids(self) -> set[int]:
        """Guild IDs the bot is a member of.

        Fetched fresh on every call so permission checks can't go stale.
        """
        headers = {"Authorization": f"Bot {self.bot_token}"}
        resp = await _get_with_retry(
            await self._http(),
            f"{API_BASE}/users/@me/guilds",
            headers,
            label="bot guilds",
        )
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord bot guild lookup failed (HTTP {resp.status_code})",
                resp.status_code,
            )
        return {int(g["id"]) for g in resp.json()}

    async def get_guild_channels(self, guild_id: int) -> list[dict]:
        headers = {"Authorization": f"Bot {self.bot_token}"}
        resp = await _get_with_retry(
            await self._http(),
            f"{API_BASE}/guilds/{guild_id}/channels",
            headers,
            label=f"guild {guild_id} channels",
        )
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord channel lookup failed (HTTP {resp.status_code})",
                resp.status_code,
            )
        return resp.json()

    async def get_guild_roles(self, guild_id: int) -> list[dict]:
        headers = {"Authorization": f"Bot {self.bot_token}"}
        resp = await _get_with_retry(
            await self._http(),
            f"{API_BASE}/guilds/{guild_id}/roles",
            headers,
            label=f"guild {guild_id} roles",
        )
        if resp.status_code != 200:
            raise DiscordAPIError(
                f"Discord role lookup failed (HTTP {resp.status_code})",
                resp.status_code,
            )
        return resp.json()
