import pytest
from starlette.testclient import TestClient

from admin_web.app import app
from bot.core.store import ProfileStore
from bot.config.guild_config import GuildConfig

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


def _install_discord_mocks(client, user_guilds, bot_ids) -> None:
    discord = client.app.state.discord

    async def get_user_guilds(access_token):
        return user_guilds

    async def get_bot_guild_ids():
        return set(bot_ids)

    discord.get_user_guilds = get_user_guilds
    discord.get_bot_guild_ids = get_bot_guild_ids


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


def test_guild_picker_lists_only_accessible(client):
    _standard_world(client)
    res = client.get("/app")
    assert res.status_code == 200
    assert "Alpha" in res.text
    assert "Not configured" in res.text
    assert "Beta" not in res.text
    assert "Gamma" not in res.text


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
