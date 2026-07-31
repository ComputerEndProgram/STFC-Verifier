import pytest

from bot.config.profiles import ProfileNotFoundError, get_profile


def test_get_profile_known() -> None:
    profile = get_profile("stfc_verifier")
    assert profile.name == "stfc_verifier"
    assert "rank_tiers" in profile.features

    profile = get_profile("stfc_verifier_alliance")
    assert profile.name in ("stfc_verifier", "stfc_verifier_alliance")

    profile = get_profile("veil_security")
    assert profile.name == "veil_security"
    assert "ops_level_check" in profile.features


def test_get_profile_unknown_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        get_profile("nonexistent_profile")
