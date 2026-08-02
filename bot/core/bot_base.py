import base64
import io
import json
import logging
import pathlib
import sqlite3
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from bot.config.guild_config import GuildConfig
from bot.config.profiles import get_profile
from bot.config.settings import Settings
from bot.core.i18n.translator import Translator
from bot.core.store import ProfileStore, _support_ticket_text
from bot.core.views import (
    ChannelStartView,
    ConfirmVerificationView,
    RankConfirmationView,
    SessionExpiredView,
    SkipStepsView,
    StartWizardView,
)

log = logging.getLogger("veil_bot")


class BaseBot(commands.Bot):
    """Shared multi-guild bot serving all verification profiles."""

    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.store = ProfileStore(str(settings.database_path))
        self._t = Translator(settings.default_language)
        self._last_update_check: dict[int, datetime] = {}

        debug = settings.debug
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        )

    def get_guild_config(self, guild_id: int) -> GuildConfig | None:
        return self.store.get_guild_config(guild_id)

    def save_guild_config(self, config: GuildConfig) -> None:
        self.store.save_guild_config(config)

    async def setup_hook(self):
        cogs_dir = pathlib.Path(__file__).resolve().parents[1] / "cogs"
        if cogs_dir.exists():
            for cog_file in cogs_dir.glob("*.py"):
                if cog_file.name.startswith("_"):
                    continue
                cog_name = f"bot.cogs.{cog_file.stem}"
                try:
                    await self.load_extension(cog_name)
                    log.info(f"[SETUP] Loaded cog: {cog_name}")
                except Exception as e:
                    log.error(f"[SETUP] Failed to load cog {cog_name}: {e}")

        await self.tree.sync()
        log.info("[SETUP] Commands synced globally")
        for config in self.store.get_all_guild_configs():
            try:
                guild = discord.Object(id=config.guild_id)
                await self.tree.sync(guild=guild)
                log.info(f"[SETUP] Commands synced to guild {config.guild_id}")
            except Exception as e:
                log.warning(f"[SETUP] Could not sync to guild {config.guild_id}: {e}")

        self.update_stfc_players.start()
        log.info("[SETUP] Background tasks started")

        self.add_view(ChannelStartView(self._t))
        log.info("[SETUP] Registered persistent ChannelStartView")

        await self._restore_pending_confirmations()
        await self._restore_pending_wizard_views()

    async def _restore_pending_wizard_views(self):
        try:
            pending = self.store.get_all_pending_wizard_views()
            if not pending:
                return
            log.info(f"[SETUP] Restoring {len(pending)} pending wizard view(s)")
            for row in pending:
                view_type = row["view_type"]
                user_id = row["user_id"]
                try:
                    user = await self.fetch_user(user_id)
                    channel = user.dm_channel or await user.create_dm()
                    await channel.fetch_message(row["message_id"])
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ) as e:
                    log.warning(
                        f"[SETUP] Could not restore wizard view {row['message_id']}: {e}"
                    )
                    self.store.delete_pending_wizard_view(row["message_id"])
                    continue

                session = self.store.get_wizard_session(user_id)
                guild_id = session.get("guild_id") if session else None
                config = self.get_guild_config(guild_id) if guild_id else None
                support_channel_id = config.support_channel_id if config else None

                if view_type == "StartWizardView":
                    view = StartWizardView(
                        self.store,
                        lambda sid=support_channel_id: _support_ticket_text(sid),
                        self._t,
                        guild_id=guild_id,
                    )
                elif view_type == "SkipStepsView":
                    view = SkipStepsView(user_id, self.store, self._t)
                elif view_type == "SessionExpiredView":
                    view = SessionExpiredView(user_id, self.store, self._t)
                elif view_type == "ConfirmVerificationView":
                    view = ConfirmVerificationView(
                        user_id, self.store, self._finalize_verification, self._t
                    )
                else:
                    log.warning(f"[SETUP] Unknown wizard view type: {view_type}")
                    continue

                view.confirmation_message_id = row["message_id"]
                view.confirmation_channel_id = row["channel_id"]
                self.add_view(view, message_id=row["message_id"])
                log.info(
                    f"[SETUP] Restored {view_type} for user {user_id} (msg: {row['message_id']})"
                )
        except Exception as e:
            log.error(f"[SETUP] Error restoring wizard views: {e}")

    async def _restore_pending_confirmations(self):
        try:
            pending = self.store.get_all_pending_rank_confirmations()
            if not pending:
                return
            log.info(f"[SETUP] Restoring {len(pending)} pending rank confirmation(s)")
            for row in pending:
                channel = self.get_channel(row["channel_id"])
                if not channel:
                    try:
                        channel = await self.fetch_channel(row["channel_id"])
                    except Exception:
                        channel = None
                if not channel or not getattr(channel, "guild", None):
                    log.warning(
                        f"[SETUP] Channel {row['channel_id']} not found for pending confirmation {row['message_id']}"
                    )
                    continue

                guild = channel.guild
                config = self.get_guild_config(guild.id)
                try:
                    msg = await channel.fetch_message(row["message_id"])
                except (discord.NotFound, discord.Forbidden):
                    log.warning(
                        f"[SETUP] Message {row['message_id']} not found, cleaning up"
                    )
                    self.store.delete_pending_rank_confirmation(row["message_id"])
                    continue
                view = RankConfirmationView(
                    row["user_id"],
                    row["member_name"],
                    row["rank"],
                    row["player_name"],
                    row["alliance_tag"],
                    config,
                    self.store,
                    lambda g=guild: g,
                    self._t,
                )
                view.log_message = msg
                view.confirmation_message_id = row["message_id"]
                view.confirmation_channel_id = row["channel_id"]
                self.add_view(view, message_id=row["message_id"])
                log.info(
                    f"[SETUP] Restored rank confirmation for {row['member_name']} (msg: {row['message_id']})"
                )
        except Exception as e:
            log.error(f"[SETUP] Error restoring pending confirmations: {e}")

    async def on_ready(self):
        log.info(f"[READY] Logged in as {self.user}")

    async def post_to_log_channel(
        self,
        guild_id: int,
        embed: discord.Embed = None,
        file: discord.File = None,
        view: discord.ui.View = None,
        content: str | None = None,
    ):
        config = self.get_guild_config(guild_id)
        if not config or not config.log_channel_id:
            return None
        guild = self.get_guild(guild_id)
        if not guild:
            return None
        log_ch = guild.get_channel(config.log_channel_id)
        if not log_ch:
            log.warning(
                f"[LOG] Log channel {config.log_channel_id} not found in guild {guild_id}"
            )
            return None
        try:
            return await log_ch.send(content=content, embed=embed, file=file, view=view)
        except Exception as e:
            log.warning(f"[LOG] Could not send to log channel: {e}")
            return None

    async def post_admin_notification(self, guild_id: int, message: str):
        config = self.get_guild_config(guild_id)
        if not config or not config.admin_role_id:
            return
        guild = self.get_guild(guild_id)
        if not guild:
            return
        admin_role = guild.get_role(config.admin_role_id)
        if not admin_role:
            log.warning(
                f"[ADMIN] Admin role {config.admin_role_id} not found in guild {guild_id}"
            )
            return
        for channel in guild.text_channels:
            try:
                await channel.send(f"{admin_role.mention} {message}")
                return
            except discord.Forbidden:
                continue
        log.warning("[ADMIN] Could not find a channel to send notification")

    async def on_message(self, message: discord.Message):
        log.debug(f"[WIZARD] on_message called for {message.author.id}")
        if message.author.bot:
            return
        if message.guild is not None:
            return

        user_id = message.author.id
        session = self.store.get_wizard_session(user_id)

        if not session:
            log.debug(f"[WIZARD] No active session for {user_id}, ignoring message")
            await self._handle_expired_session(message, user_id)
            return

        log.info(
            f"[WIZARD] Received DM from {user_id}: '{message.content[:50]}'... (step: {session['step']})"
        )

        try:
            if session["step"] == 1:
                await self._handle_step1(message, user_id, session)
            elif session["step"] == 2:
                await self._handle_step2(message, user_id, session)
        except Exception as e:
            log.exception(f"[WIZARD] Error in wizard flow for user {user_id}")
            await message.reply(f"❌ An error occurred: {e}")
            self.store.delete_wizard_session(user_id)

    async def _cleanup_user_wizard_views(self, user_id: int):
        views = self.store.get_pending_wizard_views_by_user(user_id)
        for v in views:
            try:
                channel = self.get_channel(v["channel_id"])
                if not channel:
                    channel = await self.fetch_channel(v["channel_id"])
                msg = await channel.fetch_message(v["message_id"])
                await msg.edit(view=None)
            except Exception as e:
                log.debug(f"[CLEANUP] Could not remove wizard view: {e}")
            self.store.delete_pending_wizard_view(v["message_id"])

    async def _handle_expired_session(self, message: discord.Message, user_id: int):
        with sqlite3.connect(self.store.path) as conn:
            cursor = conn.execute(
                "SELECT expires_at FROM wizard_sessions WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                expires_at = datetime.fromisoformat(row[0])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if datetime.now(UTC) > expires_at:
                    conn.execute(
                        "DELETE FROM wizard_sessions WHERE user_id = ?", (user_id,)
                    )
                    conn.commit()
                    embed = discord.Embed(
                        title=self._t.t(None, "wizard.session_expired_title"),
                        description=self._t.t(None, "wizard.session_expired_desc"),
                        colour=discord.Colour.orange(),
                    )
                    msg = await message.author.send(
                        embed=embed,
                        view=SessionExpiredView(user_id, self.store, self._t),
                    )
                    self.store.save_pending_wizard_view(
                        msg.id, msg.channel.id, user_id, "SessionExpiredView"
                    )
                    log.info(f"[WIZARD] Notified user {user_id} of session expiration")

    async def _handle_step1(
        self, message: discord.Message, user_id: int, session: dict
    ):
        from bot.core.stfc_scraper import STFCProScraper

        guild_id = session.get("guild_id")
        config = self.get_guild_config(guild_id) if guild_id else None
        require_screenshot = config.require_screenshot if config else True

        player_link = message.content.strip()
        player_id = STFCProScraper.extract_player_id_from_url(player_link)
        if not player_id:
            await message.reply(self._t.t(None, "wizard.invalid_link"))
            return

        player_data = STFCProScraper.fetch_player_data(player_id)
        if not player_data:
            await message.reply(
                self._t.t(None, "wizard.fetch_failed", player_id=player_id)
            )
            return

        player_data_json = json.dumps(
            {
                "player_id": player_data.player_id,
                "username": player_data.username,
                "level": player_data.level,
                "server": player_data.server,
                "alliance_tag": player_data.alliance_tag,
                "rank": getattr(player_data, "rank", None),
            }
        )
        self.store.update_wizard_session(
            user_id, stfc_link=player_link, player_data_json=player_data_json
        )
        self.store.update_wizard_session(user_id, step=2)

        if not require_screenshot:
            self.store.update_wizard_session(user_id, step=3)
            await self._show_summary_view(message, user_id, guild_id)
            log.info(
                f"[WIZARD] User {user_id} provided STFC link, skipping screenshot step"
            )
            return

        embed = discord.Embed(
            title=self._t.t(None, "wizard.step2.title"),
            description=self._t.t(None, "wizard.step2.description"),
            colour=discord.Colour.blue(),
        )
        embed.set_footer(text=self._t.t(None, "wizard.step2.footer"))
        msg = await message.reply(
            embed=embed, view=SkipStepsView(user_id, self.store, self._t)
        )
        self.store.save_pending_wizard_view(
            msg.id, msg.channel.id, user_id, "SkipStepsView"
        )
        log.info(f"[WIZARD] User {user_id} provided STFC link, moving to step 2")

    async def _handle_step2(
        self, message: discord.Message, user_id: int, session: dict
    ):
        if not message.attachments:
            await message.reply(self._t.t(None, "wizard.no_screenshot"))
            return

        screenshot = message.attachments[0]
        if not screenshot.content_type or not screenshot.content_type.startswith(
            "image/"
        ):
            await message.reply(self._t.t(None, "wizard.no_image"))
            return

        try:
            img_bytes = await screenshot.read()
            screenshot_b64 = base64.b64encode(img_bytes).decode("utf-8")
            self.store.update_wizard_session(
                user_id, screenshot_data=screenshot_b64, step=3
            )
        except Exception as e:
            log.error(f"[WIZARD] Failed to read screenshot: {e}")
            await message.reply(self._t.t(None, "wizard.screenshot_error"))
            return

        guild_id = session.get("guild_id")
        await self._show_summary_view(message, user_id, guild_id)
        log.info(f"[WIZARD] User {user_id} provided screenshot, showing summary")

    async def _show_summary_view(
        self, message: discord.Message, user_id: int, guild_id: int | None
    ):
        await self._cleanup_user_wizard_views(user_id)

        player_data = self.store.get_wizard_player_data(user_id)
        if not player_data:
            await message.reply(self._t.t(None, "wizard.session_error"))
            self.store.delete_wizard_session(user_id)
            return

        config = self.get_guild_config(guild_id) if guild_id else None
        bot_profile_name = config.bot_profile if config else "stfc_verifier"
        profile = get_profile(bot_profile_name)

        embed = (
            profile.build_summary_embed(player_data, config, self._t)
            if config
            else discord.Embed(
                title=self._t.t(None, "wizard.summary_title"),
                description=self._t.t(None, "wizard.summary_description"),
                colour=discord.Colour.gold(),
            )
        )
        msg = await message.reply(
            embed=embed,
            view=ConfirmVerificationView(
                user_id, self.store, self._finalize_verification, self._t
            ),
        )
        self.store.save_pending_wizard_view(
            msg.id, msg.channel.id, user_id, "ConfirmVerificationView"
        )

    async def _finalize_verification(
        self, interaction: discord.Interaction, session: dict
    ):
        user_id = session["user_id"]
        guild_id = session.get("guild_id")
        if not guild_id:
            await interaction.followup.send(
                self._t.t(None, "wizard.guild_not_found"), ephemeral=True
            )
            return

        config = self.get_guild_config(guild_id)
        if not config:
            await interaction.followup.send(
                self._t.t(None, "wizard.guild_not_found"), ephemeral=True
            )
            return

        guild = self.get_guild(guild_id)
        if not guild:
            await interaction.followup.send(
                self._t.t(None, "wizard.guild_not_found"), ephemeral=True
            )
            return

        member = guild.get_member(user_id)
        if not member:
            await interaction.followup.send(
                self._t.t(None, "wizard.member_not_found"), ephemeral=True
            )
            return

        player_link = session["stfc_link"]
        from bot.core.stfc_scraper import STFCProScraper, format_player_info

        player_id = STFCProScraper.extract_player_id_from_url(player_link)
        if not player_id:
            await interaction.followup.send(
                self._t.t(None, "wizard.invalid_link_stored"), ephemeral=True
            )
            return

        if self.store.is_player_id_taken(player_id, exclude_user_id=user_id):
            await interaction.followup.send(
                self._t.t(None, "verification.player_id_taken"),
                ephemeral=True,
            )
            return

        player_data = STFCProScraper.fetch_player_data(player_id)
        if not player_data:
            await interaction.followup.send(
                self._t.t(None, "wizard.fetch_error"), ephemeral=True
            )
            return

        profile = get_profile(config.bot_profile)

        feedback = [self._t.t(interaction.locale, "verification.complete")]
        feedback.append("✅ **stfc.pro Data:**")
        feedback.append(f"  {format_player_info(player_data)}\n")

        new_nick = profile.build_nickname(player_data)
        try:
            await member.edit(nick=new_nick)
            feedback.append(self._t.t(None, "wizard.nickname_set", nickname=new_nick))
            log.info(f"[WIZARD] Set nickname for {member.id}: {new_nick}")
        except discord.Forbidden:
            feedback.append(self._t.t(None, "wizard.nickname_failed"))
            log.warning(f"[WIZARD] Could not set nickname for {member.id} (Forbidden)")
        except Exception as e:
            feedback.append(self._t.t(None, "wizard.nickname_error", error=e))
            log.error(f"[WIZARD] Error setting nickname for {member.id}: {e}")

        self.store.store_stfc_player(member.id, player_link, player_data)
        self.store.delete_pending_wizard_views_by_user(member.id)

        role_feedback, confirmation_view = await profile.assign_roles(
            self, member, player_data, interaction, config
        )
        feedback.extend(role_feedback)

        self.store.mark_verified(member.id)
        self.store.log_verification_action(member.id, "verified")
        feedback.append(self._t.t(None, "wizard.player_data_stored"))

        if config.verified_role_id:
            verify_role = guild.get_role(config.verified_role_id)
            if verify_role:
                try:
                    await member.add_roles(verify_role, reason="Verified via stfc.pro")
                    feedback.append(self._t.t(None, "wizard.verify_role_assigned"))
                    log.info(f"[WIZARD] Assigned verify role to {member.id}")
                except Exception as e:
                    feedback.append(
                        self._t.t(None, "wizard.verify_role_error", error=e)
                    )
                    log.warning(
                        f"[WIZARD] Error assigning verify role to {member.id}: {e}"
                    )

        feedback_text = "\n".join(feedback)
        await interaction.followup.send(feedback_text, ephemeral=True)

        if config.log_channel_id:
            embed = profile.build_log_embed(
                member, player_data, session, self._t, interaction.locale
            )
            screenshot_file = None
            if session.get("screenshot_data"):
                try:
                    screenshot_bytes = base64.b64decode(session["screenshot_data"])
                    screenshot_file = discord.File(
                        io.BytesIO(screenshot_bytes), filename="verification.png"
                    )
                    embed.set_image(url="attachment://verification.png")
                except Exception as e:
                    log.warning(f"[WIZARD] Could not decode screenshot: {e}")

            try:
                if screenshot_file:
                    log_msg = await self.post_to_log_channel(
                        guild.id, embed=embed, file=screenshot_file
                    )
                else:
                    log_msg = await self.post_to_log_channel(guild.id, embed=embed)

                if confirmation_view and log_msg:
                    confirmation_view.log_message = log_msg
                    admin_ping = (
                        f"<@&{config.admin_role_id}>"
                        if config.admin_role_id
                        else "Admins"
                    )
                    alliance_display = (
                        f"[{player_data.alliance_tag}]"
                        if player_data.alliance_tag
                        else "N/A"
                    )
                    confirm_embed = discord.Embed(
                        title=self._t.t(None, "wizard.log_confirm_title"),
                        description=self._t.t(None, "wizard.log_confirm_desc"),
                        color=discord.Color.orange(),
                    )
                    confirm_embed.add_field(
                        name="Player",
                        value=f"{member.mention} ({player_data.username})",
                        inline=False,
                    )
                    confirm_embed.add_field(
                        name=self._t.t(None, "rank.label"),
                        value=getattr(player_data, "rank", "N/A"),
                        inline=True,
                    )
                    confirm_embed.add_field(
                        name=self._t.t(None, "rank.alliance_label"),
                        value=alliance_display,
                        inline=True,
                    )
                    confirm_msg = await self.post_to_log_channel(
                        guild.id,
                        embed=confirm_embed,
                        view=confirmation_view,
                        content=admin_ping,
                    )
                    if confirm_msg:
                        confirmation_view.log_message = confirm_msg
                        confirmation_view.confirmation_message_id = confirm_msg.id
                        confirmation_view.confirmation_channel_id = (
                            confirm_msg.channel.id
                        )
                        self.store.save_pending_rank_confirmation(
                            confirm_msg.id,
                            confirm_msg.channel.id,
                            member.id,
                            str(member),
                            player_data.rank,
                            player_data.username,
                            player_data.alliance_tag or "N/A",
                        )

                log.info("[WIZARD] Logged verification to log channel")
            except Exception as e:
                log.warning(f"[WIZARD] Could not log to channel: {e}")

        log.info(
            f"[WIZARD] user={member.id} name={player_data.username} "
            f"server={player_data.server} alliance={player_data.alliance_tag} "
            f"level={player_data.level}"
        )

    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        config = self.get_guild_config(member.guild.id)
        if not config:
            return

        try:
            embed = discord.Embed(
                title=self._t.t(None, "wizard.welcome.title"),
                description=self._t.t(None, "wizard.welcome.description"),
                colour=discord.Colour.blurple(),
            )
            embed.add_field(
                name=self._t.t(None, "wizard.welcome.field_what"),
                value=self._t.t(None, "wizard.welcome.field_what_value"),
                inline=False,
            )
            embed.add_field(
                name=self._t.t(None, "wizard.welcome.field_rules"),
                value=self._t.t(None, "wizard.welcome.field_rules_value"),
                inline=False,
            )
            embed.add_field(
                name=self._t.t(None, "wizard.welcome.field_ready"),
                value=self._t.t(None, "wizard.welcome.field_ready_value"),
                inline=False,
            )
            embed.set_footer(text=self._t.t(None, "wizard.welcome.footer"))
            msg = await member.send(
                embed=embed,
                view=StartWizardView(
                    self.store,
                    lambda: _support_ticket_text(config.support_channel_id),
                    self._t,
                    guild_id=member.guild.id,
                    locale=member.guild.preferred_locale,
                ),
            )
            self.store.save_pending_wizard_view(
                msg.id, msg.channel.id, member.id, "StartWizardView"
            )
            log.info(f"[WIZARD] Sent welcome message to new member {member.id}")
        except discord.Forbidden:
            log.warning(
                f"[WIZARD] Could not send DM to new member {member.id} (DMs disabled)"
            )
        except Exception as e:
            log.error(f"[WIZARD] Error sending welcome to member {member.id}: {e}")

    async def on_member_remove(self, member: discord.Member):
        config = self.get_guild_config(member.guild.id)
        if not config:
            return
        if self.store.get_player_data(member.id):
            self.store.delete_verification(member.id)
            self.store.log_verification_action(
                member.id, "removed", None, "User left the server"
            )
            log.info(f"[DB] Deleted verification for user {member.id} (left server)")
        self.store.delete_wizard_session(member.id)
        log.info(f"[WIZARD] Cleared wizard session for user {member.id}")

    @tasks.loop(hours=1)
    async def update_stfc_players(self):
        configs = self.store.get_all_guild_configs()
        if not configs:
            return

        players = self.store.get_all_players()
        if not players:
            log.info("[UPDATE] No players to check")
            return

        now = datetime.now(UTC)
        log.info("[UPDATE] Starting periodic player update check")

        for config in configs:
            interval_hours = config.update_check_hours or 24
            last = self._last_update_check.get(config.guild_id)
            if last and (now - last).total_seconds() < interval_hours * 3600:
                continue

            guild = self.get_guild(config.guild_id)
            if not guild:
                continue

            profile = get_profile(config.bot_profile)
            for user_id, stfc_link, player_id in players:
                member = guild.get_member(user_id)
                if not member:
                    continue

                try:
                    from bot.core.stfc_scraper import STFCProScraper

                    player_data = STFCProScraper.fetch_player_data(player_id)
                    if not player_data:
                        log.warning(
                            f"[UPDATE] Could not fetch data for player {player_id}"
                        )
                        continue

                    await profile.handle_update(
                        self, member, user_id, stfc_link, player_data, config
                    )
                except Exception as e:
                    log.error(f"[UPDATE] Error updating player {player_id}: {e}")

            self._last_update_check[config.guild_id] = now

        log.info("[UPDATE] Periodic player update check completed")

    @update_stfc_players.before_loop
    async def before_update_stfc(self):
        await self.wait_until_ready()
