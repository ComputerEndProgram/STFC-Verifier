from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config.guild_config import GuildConfig
from bot.core.store import PlayerData
from bot.profiles.veil_security.profile import VeilSecurityProfile


@pytest.mark.anyio
async def test_veil_security_assign_roles() -> None:
    profile = VeilSecurityProfile()
    config = GuildConfig(
        guild_id=1,
        bot_profile="veil_security",
        minimum_ops_level=71,
        ops71_plus_role_id=999,
    )

    bot = MagicMock()
    member = MagicMock()
    member.id = 500
    member.roles = []

    guild = MagicMock()
    member.guild = guild

    server_role = MagicMock()
    server_role.name = "106"
    ops_role = MagicMock()
    ops_role.id = 999

    guild.roles = [server_role]
    guild.get_role.side_effect = lambda r_id: ops_role if r_id == 999 else None
    member.add_roles = AsyncMock()

    interaction = MagicMock()

    player_data = PlayerData(
        player_id="1", username="VeilUser", level=72, server=106, alliance_tag="VEIL"
    )

    feedback, confirmation_view = await profile.assign_roles(
        bot, member, player_data, interaction, config
    )

    assert confirmation_view is None
    assert any("Server role assigned" in f for f in feedback)
    assert any("OPS 71+ role assigned" in f for f in feedback)
    assert member.add_roles.call_count == 2
