import os
import tempfile

from bot.config.guild_config import GuildConfig
from bot.config.settings import Settings
from bot.core.store import ProfileStore


def _clear_env() -> None:
    keys = [
        "DISCORD_TOKEN",
        "DATABASE_URL",
        "SQLITE_PATH",
        "DEBUG",
        "DEFAULT_LANGUAGE",
    ]
    for key in keys:
        os.environ.pop(key, None)


def test_settings_from_env_loads_global_settings() -> None:
    _clear_env()
    os.environ["DISCORD_TOKEN"] = "test_global_token"
    os.environ["DEBUG"] = "1"
    os.environ["DEFAULT_LANGUAGE"] = "en"

    settings = Settings.from_env()

    assert settings.discord_token == "test_global_token"
    assert settings.debug is True
    assert settings.default_language == "en"
    assert settings.database_path.as_posix().endswith("data/verifier.sqlite3")


def test_guild_config_store_crud_and_caching() -> None:
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tmp:
        db_path = tmp.name

    try:
        store = ProfileStore(db_path)
        assert store.get_guild_config(123456) is None

        config = GuildConfig(
            guild_id=123456,
            bot_profile="stfc_verifier",
            verify_channel_id=100,
            log_channel_id=200,
            member_role_id=300,
            stfc_server_number=106,
            manage_alliance_roles=True,
        )
        store.save_guild_config(config)

        # Test cached / stored retrieval
        loaded = store.get_guild_config(123456)
        assert loaded is not None
        assert loaded.guild_id == 123456
        assert loaded.bot_profile == "stfc_verifier"
        assert loaded.verify_channel_id == 100
        assert loaded.log_channel_id == 200
        assert loaded.member_role_id == 300
        assert loaded.stfc_server_number == 106
        assert loaded.manage_alliance_roles is True
        assert loaded.session_ttl_hours == 168

        # Test updates
        updated_config = GuildConfig(
            guild_id=123456,
            bot_profile="veil_security",
            minimum_ops_level=71,
            ops71_plus_role_id=400,
            manage_alliance_roles=False,
        )
        store.save_guild_config(updated_config)

        loaded_updated = store.get_guild_config(123456)
        assert loaded_updated is not None
        assert loaded_updated.bot_profile == "veil_security"
        assert loaded_updated.minimum_ops_level == 71
        assert loaded_updated.manage_alliance_roles is False

        # Test deletion
        store.delete_guild_config(123456)
        assert store.get_guild_config(123456) is None
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_guild_config_cache_invalidates_on_external_write() -> None:
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tmp:
        db_path = tmp.name

    try:
        bot_store = ProfileStore(db_path)
        web_store = ProfileStore(db_path)

        original = GuildConfig(
            guild_id=424242,
            bot_profile="stfc_verifier",
            verify_channel_id=100,
            member_role_id=300,
            stfc_server_number=106,
        )
        bot_store.save_guild_config(original)

        # The bot resolves config from its in-memory cache.
        loaded = bot_store.get_guild_config(424242)
        assert loaded is not None
        assert loaded.bot_profile == "stfc_verifier"

        # The web UI (separate process) writes a new config to the same DB file.
        web_store.save_guild_config(
            GuildConfig(
                guild_id=424242,
                bot_profile="veil_security",
                minimum_ops_level=71,
                ops71_plus_role_id=400,
                require_screenshot=False,
            )
        )

        # The bot must observe the external change without a restart.
        reloaded = bot_store.get_guild_config(424242)
        assert reloaded is not None
        assert reloaded.bot_profile == "veil_security"
        assert reloaded.minimum_ops_level == 71
        assert reloaded.require_screenshot is False

        # Deletions by the web UI must also be picked up.
        web_store.delete_guild_config(424242)
        assert bot_store.get_guild_config(424242) is None
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
