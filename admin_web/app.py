from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from admin_web.auth import (
    STATE_COOKIE,
    STATE_TTL_SECONDS,
    AccessDenied,
    AdminContext,
    LoginRequired,
)
from admin_web.config import AdminWebConfig
from admin_web.discord_api import DiscordAPI, DiscordAPIError, guild_icon_url
from admin_web.forms import (
    PROFILE_NAMES,
    ConfigParseError,
    build_form_spec,
    config_to_values,
    form_to_values,
    values_to_config,
)
from admin_web.sessions import SessionStore
from bot.core.store import ProfileStore

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = AdminWebConfig.from_env()
    store = ProfileStore(str(cfg.bot_settings.database_path))
    sessions = SessionStore(
        str(cfg.bot_settings.database_path), ttl_days=cfg.session_ttl_days
    )
    discord = DiscordAPI(
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        redirect_uri=cfg.redirect_uri,
        bot_token=cfg.bot_settings.discord_token,
        scopes=cfg.oauth_scopes,
    )
    app.state.cfg = cfg
    app.state.discord = discord
    app.state.ctx = AdminContext(cfg, sessions, store, discord)
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    yield
    await discord.aclose()


app = FastAPI(title="STFC Verifier Admin", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _ctx(request: Request) -> AdminContext:
    return request.app.state.ctx


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _profile_label(name: str | None) -> str | None:
    if not name:
        return None
    return PROFILE_NAMES.get(name, name)


TEXT_CHANNEL_TYPES = (0, 5)  # GUILD_TEXT, GUILD_ANNOUNCEMENT


async def _guild_lookup_options(
    ctx: AdminContext, guild_id: int
) -> tuple[list[dict], list[dict]]:
    """Channels/roles of a guild the bot is in, for the form's search fields.

    Falls back to empty lists on failure so the page still renders.
    """
    try:
        channels = await ctx.discord.get_guild_channels(guild_id)
        roles = await ctx.discord.get_guild_roles(guild_id)
    except DiscordAPIError:
        return [], []
    channel_options = [
        {"id": c["id"], "name": f"#{c['name']}"}
        for c in channels
        if c.get("type") in TEXT_CHANNEL_TYPES
    ]
    role_options = [
        {"id": r["id"], "name": f"@{r['name']}"}
        for r in roles
        if r["id"] != str(guild_id)  # skip @everyone
    ]
    return channel_options, role_options


def _render(
    request: Request,
    template: str,
    *,
    title: str,
    eyebrow: str | None = None,
    nav_top: list[dict] | None = None,
    nav_bottom: list[dict] | None = None,
    actions: str | None = None,
    status_code: int = 200,
    **context,
):
    nav_top = nav_top or []
    nav_bottom = nav_bottom or []
    path = request.url.path
    for item in nav_top + nav_bottom:
        item.setdefault("active", item.get("to") == path)
    active = next((item for item in nav_top + nav_bottom if item.get("active")), None)
    frame_color = str(active.get("color", "6")) if active else "6"
    base = {
        "title": title,
        "eyebrow": eyebrow,
        "nav_top": nav_top,
        "nav_bottom": nav_bottom,
        "actions": actions,
        "frame_color": frame_color,
    }
    base.update(context)
    return _templates(request).TemplateResponse(
        request, template, base, status_code=status_code
    )


@app.exception_handler(LoginRequired)
async def on_login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(AccessDenied)
async def on_access_denied(request: Request, exc: AccessDenied):
    return _render(
        request,
        "error.html",
        title="Access denied",
        eyebrow="Admin console",
        nav_top=[
            {"label": "Home", "to": "/", "color": 5},
            {"label": "Login", "to": "/login", "color": 6},
        ],
        nav_bottom=[{"label": "Denied", "color": "alert"}],
        message=exc.message,
        status_code=403,
    )


# -- Public pages -----------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return _templates(request).TemplateResponse(
        request, "landing.html", {"title": "STFC Verifier"}
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    ctx = _ctx(request)
    if ctx.read_cookie(request) is not None:
        return RedirectResponse("/app", status_code=303)
    error_messages = {
        "state": "Authentication state did not match — please try again.",
        "oauth": "Discord sign-in failed — please try again.",
    }
    return _render(
        request,
        "login.html",
        title="Admin console",
        eyebrow="Access",
        nav_top=[
            {"label": "Home", "to": "/", "color": 5},
            {"label": "Guilds", "to": "/app", "color": 6},
        ],
        nav_bottom=[{"label": "02-4419", "color": 3}],
        error=error_messages.get(error, error),
    )


# -- Discord OAuth ----------------------------------------------------------


@app.get("/auth/login", response_class=RedirectResponse)
async def auth_login(request: Request):
    ctx = _ctx(request)
    if ctx.read_cookie(request) is not None:
        return RedirectResponse("/app", status_code=303)
    state, token = ctx.make_state()
    response = RedirectResponse(ctx.discord.authorize_url(state), status_code=303)
    response.set_cookie(
        STATE_COOKIE,
        token,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=ctx.cfg.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/auth/callback", response_class=RedirectResponse)
async def auth_callback(request: Request, code: str, state: str):
    ctx = _ctx(request)
    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not ctx.verify_state(expected, state):
        return RedirectResponse("/login?error=state", status_code=303)
    try:
        tokens = await ctx.discord.exchange_code(code)
        user = await ctx.discord.get_user(tokens["access_token"])
    except DiscordAPIError:
        return RedirectResponse("/login?error=oauth", status_code=303)
    session = ctx.sessions.create(
        user=user,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        expires_in=tokens.get("expires_in"),
    )
    response = RedirectResponse("/app", status_code=303)
    ctx.set_session_cookie(response, session)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@app.post("/auth/logout", response_class=RedirectResponse)
async def auth_logout(request: Request):
    ctx = _ctx(request)
    session = ctx.read_cookie(request)
    if session is not None:
        ctx.sessions.delete(session.token)
    response = RedirectResponse("/", status_code=303)
    ctx.clear_session_cookie(response)
    return response


# -- Authenticated pages ----------------------------------------------------


def _user_nav(session) -> tuple[list[dict], list[dict]]:
    name = session.user.get("global_name") or session.user.get("username") or "Operator"
    return (
        [
            {"label": "Guilds", "to": "/app", "color": 5},
            {"label": "Home", "to": "/", "color": 6},
        ],
        [
            {"label": name, "color": 2},
            {"label": "Log out", "color": "alert", "post_to": "/auth/logout"},
        ],
    )


def _logout_actions() -> str:
    return (
        '<form method="post" action="/auth/logout" style="display:inline-flex">'
        '<button type="submit" class="lcars-pill lcars-pill--ghost lcars-pill--sm">Log out</button>'
        "</form>"
    )


@app.get("/app", response_class=HTMLResponse)
async def guild_picker(request: Request):
    ctx = _ctx(request)
    session = ctx.require_login(request)
    guilds = await ctx.accessible_guilds(request, session)
    bot_ids = await ctx.bot_guild_ids(request)
    configs = {config.guild_id: config for config in ctx.store.get_all_guild_configs()}
    invite_url = ctx.discord.bot_invite_url()

    rows = []
    for guild in guilds:
        gid = int(guild["id"])
        config = configs.get(gid)
        rows.append(
            {
                "id": gid,
                "name": guild.get("name") or str(gid),
                "icon": guild_icon_url(guild),
                "profile": _profile_label(config.bot_profile) if config else None,
                "configured": config is not None,
                "bot_present": gid in bot_ids,
            }
        )
    rows.sort(key=lambda r: r["name"].lower())

    nav_top, nav_bottom = _user_nav(session)
    return _render(
        request,
        "index.html",
        title="Your guilds",
        eyebrow="Admin console",
        nav_top=nav_top,
        nav_bottom=nav_bottom,
        actions=_logout_actions(),
        guilds=rows,
        user=session.user,
        invite_url=invite_url,
    )


@app.get("/guilds/{guild_id}", response_class=HTMLResponse)
async def guild_page(request: Request, guild_id: int, saved: int = 0):
    ctx = _ctx(request)
    session = ctx.require_login(request)
    guild = await ctx.require_guild(request, guild_id)
    config = ctx.store.get_guild_config(guild_id)
    channels, roles = await _guild_lookup_options(ctx, guild_id)

    nav_top, nav_bottom = _user_nav(session)
    status = "configured" if config else "unconfigured"
    nav_bottom.insert(
        0,
        {
            "label": _profile_label(config.bot_profile) if config else "Not configured",
            "color": 5 if config else 3,
        },
    )
    return _render(
        request,
        "guild.html",
        title=f"{guild.get('name') or guild_id}",
        eyebrow="Guild configuration",
        nav_top=nav_top,
        nav_bottom=nav_bottom,
        actions=_logout_actions(),
        guild_id=guild_id,
        guild_name=guild.get("name") or str(guild_id),
        config=config,
        values=config_to_values(config),
        groups=build_form_spec(),
        display_groups=build_form_spec(config.bot_profile if config else None),
        channels=channels,
        roles=roles,
        csrf_token=session.csrf_token,
        saved=bool(saved),
        profile_label=_profile_label(config.bot_profile) if config else None,
        status=status,
    )


@app.post("/guilds/{guild_id}/config", response_class=HTMLResponse)
async def guild_config_save(request: Request, guild_id: int):
    ctx = _ctx(request)
    session = ctx.require_login(request)
    guild = await ctx.require_guild(request, guild_id)

    form = dict(await request.form())
    if form.get("csrf_token") != session.csrf_token:
        raise AccessDenied("Session validation failed. Refresh the page and try again.")

    try:
        config = values_to_config(guild_id, form)
    except ConfigParseError as exc:
        config = ctx.store.get_guild_config(guild_id)
        channels, roles = await _guild_lookup_options(ctx, guild_id)
        nav_top, nav_bottom = _user_nav(session)
        nav_bottom.insert(0, {"label": "Error", "color": "alert"})
        return _render(
            request,
            "guild.html",
            title=f"{guild.get('name') or guild_id}",
            eyebrow="Guild configuration",
            nav_top=nav_top,
            nav_bottom=nav_bottom,
            actions=_logout_actions(),
            guild_id=guild_id,
            guild_name=guild.get("name") or str(guild_id),
            config=config,
            values=form_to_values(form),
            groups=build_form_spec(),
            display_groups=build_form_spec(config.bot_profile if config else None),
            channels=channels,
            roles=roles,
            csrf_token=session.csrf_token,
            saved=False,
            form_error=str(exc),
            status="error",
        )

    ctx.store.save_guild_config(config)
    return RedirectResponse(f"/guilds/{guild_id}?saved=1", status_code=303)
