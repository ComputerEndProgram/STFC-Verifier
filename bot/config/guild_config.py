from dataclasses import dataclass
from typing import Optional


@dataclass
class GuildConfig:
    guild_id: int
    bot_profile: str = "stfc_verifier"
    verify_channel_id: Optional[int] = None
    log_channel_id: Optional[int] = None
    support_channel_id: Optional[int] = None
    verified_role_id: Optional[int] = None
    unverified_role_id: Optional[int] = None
    member_role_id: Optional[int] = None
    commodore_role_id: Optional[int] = None
    admiral_role_id: Optional[int] = None
    admin_role_id: Optional[int] = None
    ops71_plus_role_id: Optional[int] = None
    minimum_ops_level: Optional[int] = None
    stfc_server_number: Optional[int] = None
    update_check_hours: int = 24
    require_screenshot: bool = True
    manage_alliance_roles: bool = False
