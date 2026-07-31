from typing import Optional

from bot.config.guild_config import GuildConfig
from bot.core.i18n.translator import Translator


def build_support_message(
    translator: Translator,
    language: str,
    config: Optional[GuildConfig] = None,
    support_channel_id: Optional[int] = None,
) -> str:
    ch_id = (
        support_channel_id
        if support_channel_id is not None
        else (config.support_channel_id if config else None)
    )
    support_channel_mention = f"<#{ch_id}>" if ch_id else None

    if support_channel_mention:
        return translator.t(
            language,
            "verification.support_ticket",
            support_channel_mention=support_channel_mention,
        )
    return translator.t(language, "verification.support_ticket_fallback")
