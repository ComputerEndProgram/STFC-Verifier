from __future__ import annotations

import types
import typing
from dataclasses import fields

from bot.config.guild_config import GuildConfig
from bot.config.profiles import PROFILE_REGISTRY

PROFILE_NAMES = {
    "stfc_verifier": "Verifier for Server Guilds",
    "stfc_verifier_alliance": "Verifier for Alliance Guilds",
    "veil_security": "OPS Level Verifier",
}

PROFILE_FIELDS = {
    name: frozenset(profile.config_fields) for name, profile in PROFILE_REGISTRY.items()
}

CHANNEL_FIELDS = frozenset(
    {"verify_channel_id", "log_channel_id", "support_channel_id"}
)
ROLE_FIELDS = frozenset(
    {
        "verified_role_id",
        "member_role_id",
        "commodore_role_id",
        "admiral_role_id",
        "admin_role_id",
        "ops71_plus_role_id",
    }
)

GROUPS: list[tuple[str, list[str]]] = [
    ("Profile", ["bot_profile"]),
    ("Channels", ["verify_channel_id", "log_channel_id", "support_channel_id"]),
    (
        "Roles",
        [
            "verified_role_id",
            "member_role_id",
            "commodore_role_id",
            "admiral_role_id",
            "admin_role_id",
            "ops71_plus_role_id",
        ],
    ),
    ("Criteria", ["minimum_ops_level", "stfc_server_number"]),
    (
        "Behavior",
        [
            "update_check_hours",
            "session_ttl_hours",
            "require_screenshot",
            "manage_alliance_roles",
        ],
    ),
]

FIELD_LABELS = {
    "guild_id": "Guild ID",
    "bot_profile": "Profile",
    "verify_channel_id": "Verify channel ID",
    "log_channel_id": "Log channel ID",
    "support_channel_id": "Support channel ID",
    "verified_role_id": "Verified role ID",
    "member_role_id": "Member role ID",
    "commodore_role_id": "Commodore role ID",
    "admiral_role_id": "Admiral role ID",
    "admin_role_id": "Admin role ID",
    "ops71_plus_role_id": "OPS 71+ role ID",
    "minimum_ops_level": "Minimum OPS level",
    "stfc_server_number": "STFC server number",
    "update_check_hours": "Update check hours",
    "session_ttl_hours": "Session TTL hours",
    "require_screenshot": "Require screenshot",
    "manage_alliance_roles": "Manage alliance roles",
}

FIELD_NOTES = {
    "member_role_id": "STFC profiles — base member role assigned on verification",
    "commodore_role_id": "STFC profiles — assigned after admin confirmation",
    "admiral_role_id": "STFC profiles — assigned after admin confirmation",
    "ops71_plus_role_id": "Veil Security — role for players meeting the OPS threshold",
    "minimum_ops_level": "Veil Security — minimum OPS level for the OPS role",
    "stfc_server_number": "STFC profiles — players on other servers are rejected",
    "update_check_hours": "Hours between automatic player data refresh checks",
    "session_ttl_hours": "Hours a verification wizard session stays valid before expiring",
    "require_screenshot": "Require a screenshot upload during the verification wizard",
    "manage_alliance_roles": "STFC — auto-create and assign alliance-tag roles",
}

_PROFILE_OPTIONS = [
    {"value": name, "label": PROFILE_NAMES.get(name, name)} for name in PROFILE_REGISTRY
]


def _annotation_parts(annotation):
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return tuple(a for a in typing.get_args(annotation) if a is not type(None))
    return (annotation,)


def _field_kind(name: str, annotation) -> str:
    if name == "bot_profile":
        return "select"
    parts = _annotation_parts(annotation)
    if bool in parts:
        return "checkbox"
    if int in parts:
        # Discord IDs are up to 20 digits, beyond JS Number.MAX_SAFE_INTEGER,
        # so they must be rendered as text inputs (numeric inputmode) rather
        # than <input type=number> which loses precision / refuses to submit.
        if name in CHANNEL_FIELDS:
            return "channel"
        if name in ROLE_FIELDS:
            return "role"
        return "id" if name.endswith("_id") else "number"
    return "text"


def _human_label(name: str) -> str:
    words = name.rstrip("_id").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words) if words else name


def build_form_spec(profile: str | None = None) -> list[dict]:
    """Field groups derived from the GuildConfig dataclass.

    Fields are grouped/labelled explicitly, but anything added to the model in
    the future that isn't listed here still shows up under "Other", so the form
    can't silently drift out of sync with the model.

    When ``profile`` is given, only the fields that profile uses are returned
    (used for the read-only "Current configuration" display). Every field spec
    also carries ``profiles`` so the form can toggle visibility client-side.
    """
    allowed = PROFILE_FIELDS.get(profile) if profile else None
    model_fields = {f.name: f for f in fields(GuildConfig)}
    groups: list[dict] = []
    for group_label, names in GROUPS:
        specs = []
        for name in names:
            field = model_fields.get(name)
            if field is None:
                continue
            if allowed is not None and name != "bot_profile" and name not in allowed:
                continue
            spec = {
                "name": name,
                "label": FIELD_LABELS.get(name, _human_label(name)),
                "kind": _field_kind(name, field.type),
                "note": FIELD_NOTES.get(name),
                "profiles": _profiles_for(name),
            }
            if name == "bot_profile":
                spec["options"] = _PROFILE_OPTIONS
                spec["profiles"] = list(PROFILE_FIELDS)
            specs.append(spec)
        if specs:
            groups.append({"label": group_label, "fields": specs})

    covered = {name for _, names in GROUPS for name in names}
    extras = [
        name for name in model_fields if name not in covered and name != "guild_id"
    ]
    if extras:
        specs = []
        for name in extras:
            if allowed is not None and name not in allowed:
                continue
            field = model_fields[name]
            specs.append(
                {
                    "name": name,
                    "label": FIELD_LABELS.get(name, _human_label(name)),
                    "kind": _field_kind(name, field.type),
                    "note": FIELD_NOTES.get(name),
                    "profiles": _profiles_for(name),
                }
            )
        if specs:
            groups.append({"label": "Other", "fields": specs})
    return groups


def _profiles_for(field_name: str) -> list[str]:
    return [
        name
        for name, profile_fields in PROFILE_FIELDS.items()
        if field_name in profile_fields
    ]


def config_to_values(config: GuildConfig | None) -> dict:
    values: dict[str, object] = {}
    for field in fields(GuildConfig):
        if field.name == "guild_id":
            continue
        value = getattr(config, field.name) if config else field.default
        if field.name == "bot_profile" or isinstance(value, bool):
            values[field.name] = value
        elif value is None:
            values[field.name] = ""
        else:
            values[field.name] = str(value)
    return values


class ConfigParseError(ValueError):
    pass


def form_to_values(form: dict) -> dict:
    """Raw form data -> display values, for re-rendering a form after an error."""
    values: dict[str, object] = {}
    for field in fields(GuildConfig):
        name = field.name
        if name == "guild_id":
            continue
        kind = _field_kind(name, field.type)
        if kind == "checkbox":
            values[name] = name in form
        else:
            values[name] = str(form.get(name) or "")
    return values


def values_to_config(guild_id: int, form: dict) -> GuildConfig:
    """Parse raw form data into a GuildConfig, validating types."""
    profile = str(form.get("bot_profile") or "stfc_verifier").strip()
    if profile not in PROFILE_REGISTRY:
        raise ConfigParseError(
            f"Invalid profile '{profile}'. Choose from: {', '.join(sorted(PROFILE_REGISTRY))}"
        )

    data: dict = {"guild_id": guild_id, "bot_profile": profile}
    for field in fields(GuildConfig):
        name = field.name
        if name in ("guild_id", "bot_profile"):
            continue
        kind = _field_kind(name, field.type)
        raw = form.get(name)
        if kind == "checkbox":
            data[name] = name in form
        elif kind in ("number", "id", "channel", "role"):
            text = str(raw or "").strip()
            if text == "":
                data[name] = None
            else:
                try:
                    data[name] = int(text)
                except ValueError:
                    raise ConfigParseError(f"'{name}' must be a whole number.")
        else:
            text = str(raw or "").strip()
            data[name] = text or None
    return GuildConfig(**data)
