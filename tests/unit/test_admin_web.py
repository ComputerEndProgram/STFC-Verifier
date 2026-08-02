import asyncio

import httpx
import pytest
from starlette.testclient import TestClient

from admin_web.app import app
from admin_web.discord_api import DiscordAPI
from bot.core.store import ProfileStore

MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3

USER = {"id": "1000", "username": "tester", "global_name": "Tester", "avatar": None}


def _guild(gid: int, name: str, permissions: int, owner: bool = False) -> dict:
    return {
        "id": str(gid),
        "name": name,
        "permissions": str(permissions),
        "owner": owner,
        "icon": None,
    }


def _install_discord_mocks(
    client, user_guilds, bot_ids, guild_channels=(), guild_roles=()
) -> None:
    discord = client.app.state.discord

    async def get_user_guilds(access_token):
        return user_guilds

    async def get_bot_guild_ids():
        return set(bot_ids)

    async def get_guild_channels(guild_id):
        return list(guild_channels)

    async def get_guild_roles(guild_id):
        return list(guild_roles)

    discord.get_user_guilds = get_user_guilds
    discord.get_bot_guild_ids = get_bot_guild_ids
    discord.get_guild_channels = get_guild_channels
    discord.get_guild_roles = get_guild_roles


def _login(client) -> None:
    ctx = client.app.state.ctx
    session = ctx.sessions.create(
        user=USER,
        access_token="acc-token",
        refresh_token="ref-token",
        expires_in=3600,
    )
    client.cookies.set(ctx.cfg.cookie_name, ctx.sign_cookie(session.token), path="/")
    return session


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "fake-bot-token")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "12345")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("ADMIN_WEB_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("ADMIN_WEB_BASE_URL", "http://testserver")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "verifier.sqlite3"))
    with TestClient(app, follow_redirects=False) as client:
        yield client


def _standard_world(client):
    """Guild 111: accessible. 222: bot present, no perms. 333: perms, no bot."""
    _install_discord_mocks(
        client,
        [
            _guild(111, "Alpha", MANAGE_GUILD),
            _guild(222, "Beta", 0),
            _guild(333, "Gamma", MANAGE_GUILD),
        ],
        bot_ids={111, 222},
    )
    return _login(client)


def test_guild_picker_lists_all_manageable_guilds(client):
    _standard_world(client)
    res = client.get("/app")
    assert res.status_code == 200
    assert "Alpha" in res.text
    assert "Not configured" in res.text
    assert "Gamma" in res.text  # manageable even without the bot
    assert "Beta" not in res.text  # no Manage Server permission


def test_guild_picker_offers_invite_when_bot_absent(client):
    _standard_world(client)
    res = client.get("/app")
    assert "/oauth2/authorize" in res.text
    assert "client_id=12345" in res.text
    assert "permissions=402769920" in res.text
    assert "Bot not in this server" in res.text
    assert 'href="/guilds/111"' in res.text  # bot present -> config page


def test_guild_page_renders_config_and_form(client):
    _standard_world(client)
    res = client.get("/guilds/111")
    assert res.status_code == 200
    assert "Current configuration" in res.text
    assert "Edit config" in res.text
    assert 'name="bot_profile"' in res.text
    assert 'name="verify_channel_id"' in res.text
    assert 'name="manage_alliance_roles"' in res.text
    assert 'name="csrf_token"' in res.text


def test_profile_options_use_renamed_labels(client):
    _standard_world(client)
    res = client.get("/guilds/111")
    assert "Verifier for Server Guilds" in res.text
    assert "Verifier for Alliance Guilds" in res.text
    assert "OPS Level Verifier" in res.text


def test_form_fields_tagged_with_profiles(client):
    _standard_world(client)
    res = client.get("/guilds/111")
    assert (
        'data-field="bot_profile" data-profiles="stfc_verifier stfc_verifier_alliance veil_security"'
        in res.text
    )
    assert (
        'data-field="member_role_id" data-profiles="stfc_verifier stfc_verifier_alliance"'
        in res.text
    )
    assert 'data-field="ops71_plus_role_id" data-profiles="veil_security"' in res.text
    assert (
        'data-field="verify_channel_id" data-profiles="stfc_verifier stfc_verifier_alliance veil_security"'
        in res.text
    )


def test_channel_role_search_fields_populated(client):
    """Channel/role fields are backed by searchable options from Discord."""
    _install_discord_mocks(
        client,
        [_guild(111, "Alpha", MANAGE_GUILD)],
        bot_ids={111},
        guild_channels=[
            {"id": "1111", "name": "verify", "type": 0},
            {"id": "1112", "name": "General Voice", "type": 2},
            {"id": "1113", "name": "announce", "type": 5},
        ],
        guild_roles=[
            {"id": "2222", "name": "Member"},
            {"id": "111", "name": "@everyone"},
        ],
    )
    _login(client)
    res = client.get("/guilds/111")
    assert 'value="1111">#verify' in res.text
    assert 'value="1113">#announce' in res.text
    assert 'value="2222">@Member' in res.text
    assert 'list="channel_options"' in res.text
    assert 'list="role_options"' in res.text
    assert "#General Voice" not in res.text  # voice channels excluded
    assert "@everyone" not in res.text  # @everyone excluded


def test_display_section_filtered_by_profile(client):
    """Current-config display shows only the fields the saved profile uses."""
    session = _standard_world(client)
    res = client.post(
        "/guilds/111/config",
        data={"csrf_token": session.csrf_token, "bot_profile": "veil_security"},
    )
    assert res.status_code == 303
    res = client.get("/guilds/111")
    display = res.text.split("Edit config")[0]
    assert "OPS 71+ role ID" in display
    assert "Minimum OPS level" in display
    assert "Member role ID" not in display
    assert "Manage alliance roles" not in display


def test_guild_access_denied_without_permission_or_bot(client):
    _standard_world(client)
    assert client.get("/guilds/222").status_code == 403  # bot present, no permission
    assert client.get("/guilds/333").status_code == 403  # permission, bot absent
    assert client.get("/guilds/999").status_code == 403  # not a member


def test_save_config_updates_store_and_other_process(client):
    session = _standard_world(client)
    res = client.post(
        "/guilds/111/config",
        data={
            "csrf_token": session.csrf_token,
            "bot_profile": "veil_security",
            "verify_channel_id": "555111",
            "log_channel_id": "555222",
            "minimum_ops_level": "71",
            "ops71_plus_role_id": "555333",
            "update_check_hours": "12",
            "session_ttl_hours": "72",
            "require_screenshot": "on",
        },
    )
    assert res.status_code == 303

    ctx = client.app.state.ctx
    config = ctx.store.get_guild_config(111)
    assert config is not None
    assert config.bot_profile == "veil_security"
    assert config.verify_channel_id == 555111
    assert config.minimum_ops_level == 71
    assert config.require_screenshot is True
    assert config.manage_alliance_roles is False
    assert config.update_check_hours == 12
    assert config.session_ttl_hours == 72

    # A separate ProfileStore instance (simulating the running bot process)
    # must observe the change without a restart.
    bot_store = ProfileStore(str(ctx.cfg.bot_settings.database_path))
    bot_store.get_guild_config(111)  # prime the bot's cache
    cached = bot_store.get_guild_config(111)
    assert cached is not None
    assert cached.bot_profile == "veil_security"


def test_save_config_requires_valid_csrf(client):
    _standard_world(client)
    res = client.post(
        "/guilds/111/config",
        data={"bot_profile": "veil_security", "csrf_token": "wrong-token"},
    )
    assert res.status_code == 403


def test_save_config_rejects_invalid_profile(client):
    _standard_world(client)
    session = _login(client)
    res = client.post(
        "/guilds/111/config",
        data={"bot_profile": "bogus", "csrf_token": session.csrf_token},
    )
    assert res.status_code == 200
    assert "Invalid profile" in res.text


def test_discord_api_retries_transient_errors():
    """A transient 5xx from Discord is retried instead of failing the request."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=[{"id": "1", "name": "general", "type": 0}])

    api = DiscordAPI(
        client_id="1",
        client_secret="s",
        redirect_uri="x",
        bot_token="b",
        scopes="identify",
    )

    async def exercise():
        api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        out = await api.get_guild_channels(1)
        assert out == [{"id": "1", "name": "general", "type": 0}]
        assert calls["n"] == 2
        await api.aclose()

    asyncio.run(exercise())


def test_discord_api_client_reused_across_requests():
    """The shared httpx client must survive multiple exchanges (regression:
    a closed client previously raised "Cannot reopen a client instance")."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref"})

    api = DiscordAPI(
        client_id="1",
        client_secret="s",
        redirect_uri="http://testserver/auth/callback",
        bot_token="b",
        scopes="identify",
    )

    async def exercise():
        api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await api.exchange_code("code-1")
        await api.exchange_code("code-2")
        await api.aclose()

    asyncio.run(exercise())


def test_logout_clears_session(client):
    _standard_world(client)
    res = client.post("/auth/logout")
    assert res.status_code == 303
    assert client.get("/app").status_code == 303  # redirected back to /login


def test_permissions_rechecked_when_user_loses_access(client):
    """Permission is verified per request, not just at login."""
    _install_discord_mocks(
        client,
        [_guild(111, "Alpha", MANAGE_GUILD)],
        bot_ids={111},
    )
    _login(client)
    assert client.get("/guilds/111").status_code == 200

    # Admin permission revoked after login -> next request must fail.
    _install_discord_mocks(
        client,
        [_guild(111, "Alpha", 0)],
        bot_ids={111},
    )
    assert client.get("/guilds/111").status_code == 403
