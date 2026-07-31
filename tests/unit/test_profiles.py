from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config.guild_config import GuildConfig
from bot.config.profiles import ProfileNotFoundError, get_profile
from bot.core.store import PlayerData
from bot.profiles.stfc_verifier.profile import STFCVerifierProfile
from bot.profiles.veil_security.profile import VeilSecurityProfile


def test_profile_registry_contains_expected_profiles() -> None:
    stfc_prof = get_profile("stfc_verifier")
    assert isinstance(stfc_prof, STFCVerifierProfile)
    assert stfc_prof.name == "stfc_verifier"

    stfc_alliance_prof = get_profile("stfc_verifier_alliance")
    assert isinstance(stfc_alliance_prof, STFCVerifierProfile)

    veil_prof = get_profile("veil_security")
    assert isinstance(veil_prof, VeilSecurityProfile)
    assert veil_prof.name == "veil_security"


def test_unknown_profile_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        get_profile("not_real")


def test_stfc_verifier_nickname_building() -> None:
    profile = STFCVerifierProfile()
    p1 = PlayerData(player_id="1", username="TestPlayer", level=30, server=106, alliance_tag="ABC")
    assert profile.build_nickname(p1) == "[ABC] TestPlayer"

    p2 = PlayerData(player_id="2", username="TestPlayerNoTag", level=30, server=106, alliance_tag=None)
    assert profile.build_nickname(p2) == "TestPlayerNoTag"


def test_veil_security_nickname_building() -> None:
    profile = VeilSecurityProfile()
    p1 = PlayerData(player_id="1", username="TestPlayer", level=30, server=106, alliance_tag="ABC")
    assert profile.build_nickname(p1) == "[106] ABC - TestPlayer"

    p2 = PlayerData(player_id="2", username="TestPlayerNoTag", level=30, server=106, alliance_tag=None)
    assert profile.build_nickname(p2) == "[106] TestPlayerNoTag"


@pytest.mark.anyio
async def test_stfc_verifier_assign_roles_manage_alliance_true() -> None:
    profile = STFCVerifierProfile()
    config = GuildConfig(
        guild_id=1,
        bot_profile="stfc_verifier",
        member_role_id=10,
        commodore_role_id=11,
        admiral_role_id=12,
        stfc_server_number=106,
        manage_alliance_roles=True,
    )

    bot = MagicMock()
    member = MagicMock()
    member.id = 1001
    member.roles = []

    guild = MagicMock()
    member.guild = guild
    member_role = MagicMock()
    member_role.id = 10
    guild.get_role.side_effect = lambda r_id: member_role if r_id == 10 else None
    guild.roles = []

    alliance_role = MagicMock()
    alliance_role.id = 99
    alliance_role.name = "ABC"

    async def mock_create_role(name, color, reason):
        return alliance_role

    guild.create_role = AsyncMock(side_effect=mock_create_role)
    member.add_roles = AsyncMock()

    interaction = MagicMock()
    interaction.followup = AsyncMock()

    player_data = PlayerData(
        player_id="1", username="Player1", level=40, server=106, alliance_tag="ABC", rank="agent"
    )

    feedback, confirmation_view = await profile.assign_roles(bot, member, player_data, interaction, config)

    assert confirmation_view is None
    assert any("Base role assigned" in f for f in feedback)
    assert any("Alliance role assigned" in f for f in feedback)
    bot.store.update_user_alliance_role_id.assert_called_with(1001, 99)


@pytest.mark.anyio
async def test_stfc_verifier_assign_roles_manage_alliance_false() -> None:
    profile = STFCVerifierProfile()
    config = GuildConfig(
        guild_id=1,
        bot_profile="stfc_verifier",
        member_role_id=10,
        stfc_server_number=106,
        manage_alliance_roles=False,
    )

    bot = MagicMock()
    member = MagicMock()
    member.id = 1002
    member.roles = []

    guild = MagicMock()
    member.guild = guild
    member_role = MagicMock()
    member_role.id = 10
    guild.get_role.side_effect = lambda r_id: member_role if r_id == 10 else None
    guild.create_role = AsyncMock()
    member.add_roles = AsyncMock()

    interaction = MagicMock()
    interaction.followup = AsyncMock()

    player_data = PlayerData(
        player_id="2", username="Player2", level=40, server=106, alliance_tag="ABC", rank="agent"
    )

    feedback, confirmation_view = await profile.assign_roles(bot, member, player_data, interaction, config)

    assert confirmation_view is None
    assert any("Base role assigned" in f for f in feedback)
    assert not any("Alliance role assigned" in f for f in feedback)
    guild.create_role.assert_not_called()
