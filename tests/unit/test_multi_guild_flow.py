from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config.guild_config import GuildConfig
from bot.cogs.admin import AdminCog
from bot.profiles.veil_security.profile import VeilSecurityProfile
from bot.core.store import PlayerData


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


@pytest.mark.anyio
async def test_admin_setup_command() -> None:
    bot = MagicMock()
    bot.get_guild_config.return_value = None
    saved_configs = []

    def mock_save(cfg):
        saved_configs.append(cfg)

    bot.save_guild_config.side_effect = mock_save

    cog = AdminCog(bot)

    interaction = MagicMock()
    interaction.guild.id = 8888
    interaction.guild.name = "Test Server"
    interaction.user.guild_permissions.manage_guild = True
    interaction.user.guild_permissions.administrator = True
    interaction.response.send_message = AsyncMock()

    await cog._handle_setup(
        interaction,
        profile="stfc_verifier",
        manage_alliance_roles=True,
        stfc_server_number=106,
    )

    assert len(saved_configs) == 1
    assert saved_configs[0].guild_id == 8888
    assert saved_configs[0].bot_profile == "stfc_verifier"
    assert saved_configs[0].manage_alliance_roles is True
    assert saved_configs[0].stfc_server_number == 106
    interaction.response.send_message.assert_called_once()
