# Merged architecture

## Core modules

- `bot/core/`: shared runtime logic
- `bot/profiles/`: profile-specific verification criteria and behavior
- `bot/i18n/`: language JSON files (`en`, `de`, `fr`)
- `bot/config/`: env + settings + profile registry + `GuildConfig`
- `admin_web/`: Discord-OAuth-protected admin UI (separate process)
- `migrations/`: shared and profile-specific SQL migrations
- `scripts/`: legacy import entrypoints from old repos
- `tests/`: unit/integration/migration tests

## Per-guild configuration

One merged bot process serves every guild. Each guild's settings live in a
`GuildConfig` row (`bot/config/guild_config.py`) in a single shared SQLite
database, keyed by `guild_id`:

- `bot_profile` selects the verification profile: `stfc_verifier`,
  `stfc_verifier_alliance`, or `veil_security`
- channel/role IDs, criteria (OPS level, server number, update interval),
  and behavior flags (require screenshot, manage alliance roles)

`ProfileStore` (`bot/core/store.py`) loads configs per guild and caches them,
watching the database file's mtime so external edits are picked up by the
running bot without a restart. `get_profile(config.bot_profile)` returns the
matching implementation from `bot/config/profiles.py`.

## Config and dynamic mentions

All deployment-specific IDs are stored per-guild in the database, edited via
the admin web UI. Messages build channel mentions dynamically:

- configured: `<#{channel_id}>`
- not configured: fallback translation key

## Admin web UI

`admin_web/` is a FastAPI app run as a separate process sharing the same
database. It exposes the `GuildConfig` fields as an edit form (derived via
`dataclasses.fields()`). Access is granted per request: the user must hold
Manage Server (or Administrator) in the guild, and both the user and the bot
must be members of that guild. Sessions are server-side in the database.

## i18n behavior

- Locale normalization to language only (`en-US -> en`, `es-419 -> es`, `nb -> no`)
- `Translator.t(lang, key, **kwargs)` with fallback to `en`
- Missing key in both language and `en` returns the key string

## Session persistence and restart restore

`wizard_sessions` stores `language`, `current_step`, `answers_json`, and TTL.
`persistent_views` stores message/channel/custom ID state for startup restoration.

## Data separation

One shared SQLite database (`data/verifier.sqlite3` by default) holds guild
configs, verification records, sessions, and persistent views. Guilds are
isolated by `guild_id` rows rather than by separate databases. Override the
location with `SQLITE_PATH` or `DATABASE_URL`.
