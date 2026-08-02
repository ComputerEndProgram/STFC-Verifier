from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

import discord

from bot.config.guild_config import GuildConfig


class ProfileNotFoundError(ValueError):
    pass


COMMON_CONFIG_FIELDS = (
    "verify_channel_id",
    "log_channel_id",
    "support_channel_id",
    "verified_role_id",
    "admin_role_id",
    "update_check_hours",
    "session_ttl_hours",
    "require_screenshot",
)


@dataclass(slots=True)
class VerificationResult:
    passed: bool
    reason: str | None = None


class VerificationProfile(Protocol):
    name: str
    required_inputs: Sequence[str]
    required_roles: Sequence[str]
    optional_roles: Sequence[str]
    features: Sequence[str]
    config_fields: Sequence[str]

    def build_steps(self) -> list[str]:
        ...

    def verify(self, answers: dict[str, str]) -> VerificationResult:
        ...

    def finalize(self, answers: dict[str, str]) -> dict[str, str]:
        ...

    def build_nickname(self, player_data) -> str:
        ...

    def build_summary_embed(
        self, player_data, config: GuildConfig, translator, locale=None
    ) -> discord.Embed:
        ...

    def build_log_embed(
        self, member: discord.Member, player_data, session: dict, translator, locale=None
    ) -> discord.Embed:
        ...

    async def assign_roles(
        self,
        bot,
        member: discord.Member,
        player_data,
        interaction: discord.Interaction,
        config: GuildConfig,
    ) -> tuple[list[str], Optional[discord.ui.View]]:
        ...

    async def handle_update(
        self,
        bot,
        member: discord.Member,
        user_id: int,
        stfc_link: str,
        player_data,
        config: GuildConfig,
    ) -> None:
        ...
