# STFC Verifier

A multi-profile Discord bot for verifying STFC (Star Trek Fleet Command) accounts via [stfc.pro](https://stfc.pro) / [stfc.wtf](https://stfc.wtf) player data.

One codebase, one bot process, many servers. Each server's verification profile (`stfc_verifier`, `stfc_verifier_alliance`, or `veil_security`) and its channel/role settings are stored per-guild in a shared SQLite database and edited through the built-in admin web UI.

## Profiles

| Profile | Description |
|---|---|
| `stfc_verifier` | Rank-based verification with automatic alliance role management |
| `stfc_verifier_alliance` | Rank-based verification (alliance variant, no auto-created alliance roles) |
| `veil_security` | OPS level-based verification with server and OPS 71+ role gates |

## Quick Start

Requires Python 3.11+. Either installer works — [uv](https://docs.astral.sh/uv/) (recommended) or pip.

# Option A: uv (recommended) — installs deps + creates .venv from the lockfile
```bash
uv sync --extra dev
```

# Option B: pip
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

# Configure
```bash
cp .env.example .env
```
# Edit .env — see below for required variables

# Run
```bash
.venv/bin/stfc-verifier
```

Note: on this machine `/usr/bin/python3.13` is a custom build without `ensurepip`,
so create the venv with `--without-pip` and bootstrap pip via `get-pip.py`
(https://bootstrap.pypa.io/get-pip.py) if `python3 -m venv .venv` fails.

## Environment Variables

See [`.env.example`](.env.example) for the full annotated template.

| Variable | Default | Description |
|---|---|---|
| `DISCORD_TOKEN` | — | Bot token from the [Discord Developer Portal](https://discord.com/developers/applications) |
| `DEBUG` | `0` | Enable verbose debug logging |
| `DEFAULT_LANGUAGE` | `en` | Fallback language for the verification wizard UI |

Per-server settings (profile, channels, roles, criteria) are **not** env vars anymore — they live in the `guild_configs` table of the database and are managed through the admin web UI.

### Database

By default, the bot creates a single SQLite database at `data/verifier.sqlite3`, shared by all guilds. Override with:

| Variable | Description |
|---|---|
| `SQLITE_PATH` | Absolute path to a SQLite file |
| `DATABASE_URL` | `sqlite:///` URL to a SQLite file |

## Admin Web UI

The admin web UI is the **only** way to configure a guild's settings. It runs embedded in the bot process (no separate command needed) and lets server admins view and edit each guild's configuration over Discord OAuth2 login. It uses the same database as the bot, and saved changes are picked up by the running bot without a restart.

### Required env vars

`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `ADMIN_WEB_SESSION_SECRET` (see `.env.example`). In the Discord Developer Portal, register the redirect URL `{ADMIN_WEB_BASE_URL}/auth/callback`.

### URL

`{ADMIN_WEB_BASE_URL}` (default `http://127.0.0.1:8787`).

### What you can configure per server

- **Profile** — `stfc_verifier` / `stfc_verifier_alliance` / `veil_security`
- **Channels** — verify, log, support (IDs)
- **Roles** — verified, member, commodore, admiral, admin, ops71+ (IDs)
- **Criteria** — minimum OPS level, STFC server number
- **Behavior** — update check hours, wizard session TTL hours, require screenshot, manage alliance roles

### Access control

Anyone can log in, but only users with **Manage Server** (or **Administrator**) permission in a guild — plus the bot and the user being members of that guild — can view or edit that guild's config. Permissions are re-checked against Discord on every page load and save.

## Commands

### User commands

| Command | Description |
|---|---|
| `/verify` | Starts the verification wizard (sends a DM with step-by-step instructions) |

### Admin commands

All admin commands require the guild's configured admin role.

| Command | Description |
|---|---|
| `/admin verify <player_url> <user>` | Manually verify a user by their stfc.pro/stfc.wtf link (skips the wizard and screenshot) |
| `/admin recall <user> [reason]` | Recall a user's verification, remove all roles, and notify them via DM |
| `/admin send_button` | Post the verification button to the verify channel for users who struggle with slash commands |

## Verification Flow

1. User runs `/verify` or clicks the verification button
2. Bot sends a DM with the welcome embed and a **Start Verification** button
3. User sends their stfc.pro/stfc.wtf player link
4. Bot fetches fresh player data from stfc.pro (username, level, server, alliance, rank)
5. *(Optional)* User uploads a screenshot (skipped when the guild's `require_screenshot` setting is off)
6. Bot shows a summary; user clicks **Complete**
7. Bot sets the nickname, assigns roles, stores player data, and logs to the log channel
8. For Commodore/Admiral ranks, a confirmation embed is posted to the log channel for admin approval

## Admin Manual Verification

When a user can't complete the wizard (DMs disabled, confusion, etc.), an admin can run:

```
/admin verify player_url: https://stfc.pro/players/1234567890 user: @username
```

This performs the same steps as the wizard (nickname, roles, logging) but skips the DM interaction and screenshot. Screenshot is always skipped.

## Tests

```bash
python3 -m pytest -q
```

## Architecture

```
bot/
├── main.py                    # Entry point
├── launcher.py                # Builds and runs the app (bot + embedded admin web)
├── app.py                     # Application wiring; starts admin web in a thread
├── config/
│   ├── settings.py            # Settings from .env
│   ├── guild_config.py        # Per-guild config dataclass (stored in DB)
│   └── profiles.py            # Profile registry
├── core/
│   ├── bot_base.py            # BaseBot — shared verification logic
│   ├── store.py               # SQLite store (ProfileStore) with config cache
│   ├── stfc_scraper.py        # STFC.pro/stfc.wtf player data scraper
│   ├── views.py               # Discord UI views (wizards, confirmations)
│   ├── verification/          # Session flow and step constants
│   └── i18n/                  # Translation system
├── cogs/
│   ├── verification.py        # /verify command
│   └── admin.py               # /admin commands (verify, recall, send_button)
├── profiles/                  # Per-guild verification profiles
│   ├── stfc_verifier/
│   ├── stfc_verifier_alliance/
│   └── veil_security/
└── i18n/                      # Translation JSON files (22 languages)

admin_web/                     # Admin web UI (served from within the bot process)
├── app.py                     # FastAPI app + routes
├── auth.py                    # Discord OAuth2 + per-request permission checks
├── forms.py                   # GuildConfig-derived edit form
├── sessions.py                # Server-side session store
├── static/lcars.css           # LCARS visual theme
└── templates/                 # Jinja2 templates
```
