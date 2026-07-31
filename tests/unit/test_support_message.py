from bot.config.guild_config import GuildConfig
from bot.core.i18n.translator import Translator
from bot.core.verification.finalizer import build_support_message


def test_support_message_uses_channel_mention_when_configured() -> None:
    translator = Translator(default_language="en")
    config = GuildConfig(guild_id=1, support_channel_id=150)
    message = build_support_message(translator, "en", config=config)
    assert message == "Open a support ticket in <#150>."


def test_support_message_falls_back_when_channel_not_configured() -> None:
    translator = Translator(default_language="en")
    config = GuildConfig(guild_id=1, support_channel_id=None)
    message = build_support_message(translator, "en", config=config)
    assert "support process configured by your admins" in message
