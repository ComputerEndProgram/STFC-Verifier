from dataclasses import dataclass


@dataclass
class GuildConfig:
    guild_id: int
    bot_profile: str = "stfc_verifier"
    verify_channel_id: int | None = None
    log_channel_id: int | None = None
    support_channel_id: int | None = None
    verified_role_id: int | None = None
    member_role_id: int | None = None
    commodore_role_id: int | None = None
    admiral_role_id: int | None = None
    admin_role_id: int | None = None
    ops71_plus_role_id: int | None = None
    minimum_ops_level: int | None = None
    stfc_server_number: int | None = None
    update_check_hours: int = 24
    session_ttl_hours: int = 168
    require_screenshot: bool = True
    manage_alliance_roles: bool = False
