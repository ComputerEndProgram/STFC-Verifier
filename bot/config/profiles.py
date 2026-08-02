from bot.profiles.base import ProfileNotFoundError, VerificationProfile
from bot.profiles.stfc_verifier.profile import STFCVerifierProfile
from bot.profiles.stfc_verifier_alliance.profile import STFCVerifierAllianceProfile
from bot.profiles.veil_security.profile import VeilSecurityProfile

PROFILE_REGISTRY: dict[str, VerificationProfile] = {
    "stfc_verifier": STFCVerifierProfile(),
    "stfc_verifier_alliance": STFCVerifierAllianceProfile(),
    "veil_security": VeilSecurityProfile(),
}


def get_profile(profile_name: str) -> VerificationProfile:
    profile = PROFILE_REGISTRY.get(profile_name)
    if profile is None:
        valid = ", ".join(sorted(PROFILE_REGISTRY))
        raise ProfileNotFoundError(
            f"Unknown BOT_PROFILE '{profile_name}'. Expected one of: {valid}"
        )
    return profile
