import logging
from collections.abc import Callable

import discord

from bot.config.guild_config import GuildConfig
from bot.core.i18n.translator import Translator
from bot.core.store import ProfileStore, _support_ticket_text

log = logging.getLogger("veil_bot")

DEFAULT_SESSION_TTL_HOURS = 168


class ChannelStartView(discord.ui.View):
    """Persistent view posted in the verify channel. DMs the user with the
    real StartWizardView when clicked, so the channel message stays intact."""

    def __init__(self, translator: Translator | None = None):
        super().__init__(timeout=None)
        self._t = translator
        if translator:
            self.start_button.label = translator.t(None, "view.start_wizard")

    @discord.ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.green,
        custom_id="channel_start_verification",
    )
    async def start_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user = interaction.user
        if not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "❌ Could not start verification.",
                ephemeral=True,
            )
            return

        guild_id = interaction.guild_id
        bot = interaction.client
        config: GuildConfig | None = (
            bot.get_guild_config(guild_id) if guild_id else None
        )

        if not config:
            if user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "⚠️ This bot is not configured for this server yet. Please run `/setup` (or `/admin setup`) to configure it.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "⚠️ The verification bot is not configured for this server yet. Please contact a server administrator.",
                    ephemeral=True,
                )
            return

        store: ProfileStore = bot.store
        t: Translator = bot._t
        locale = interaction.locale

        if store.get_player_data(user.id):
            await interaction.response.send_message(
                t.t(
                    locale,
                    "wizard.already_verified",
                    support_ticket=_support_ticket_text(config.support_channel_id),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            t.t(locale, "verification.dm_sent"),
            ephemeral=True,
        )

        try:
            embed = discord.Embed(
                title=t.t(locale, "wizard.welcome.title"),
                description=t.t(locale, "wizard.welcome.description"),
                colour=discord.Colour.blurple(),
            )
            embed.add_field(
                name=t.t(locale, "wizard.welcome.field_what"),
                value=t.t(locale, "wizard.welcome.field_what_value"),
                inline=False,
            )
            embed.add_field(
                name=t.t(locale, "wizard.welcome.field_rules"),
                value=t.t(locale, "wizard.welcome.field_rules_value"),
                inline=False,
            )
            embed.add_field(
                name=t.t(locale, "wizard.welcome.field_ready"),
                value=t.t(locale, "wizard.welcome.field_ready_value"),
                inline=False,
            )
            embed.set_footer(text=t.t(locale, "wizard.welcome.footer"))

            msg = await user.send(
                embed=embed,
                view=StartWizardView(
                    store,
                    lambda: _support_ticket_text(config.support_channel_id),
                    t,
                    guild_id=guild_id,
                    locale=locale,
                ),
            )
            store.save_pending_wizard_view(
                msg.id, msg.channel.id, user.id, "StartWizardView"
            )
            log.info(f"[WIZARD] Sent verification DM to {user.id} via channel button")
        except discord.Forbidden:
            log.warning(f"[WIZARD] Could not send DM to {user.id} (DMs disabled)")
        except Exception as e:
            log.error(f"[WIZARD] Error sending verification DM to {user.id}: {e}")


class StartWizardView(discord.ui.View):
    def __init__(
        self,
        store: ProfileStore,
        support_ticket_fn: Callable[[], str],
        translator: Translator,
        guild_id: int | None = None,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self._store = store
        self._support_ticket = support_ticket_fn
        self._t = translator
        self.guild_id = guild_id
        self.locale = locale
        self.confirmation_message_id = None
        self.confirmation_channel_id = None
        self.start_button.label = translator.t(locale, "view.start_wizard")

    @discord.ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.green,
        custom_id="start_wizard_verify",
    )
    async def start_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user_id = interaction.user.id
        locale = interaction.locale

        if self._store.get_player_data(user_id):
            await interaction.response.send_message(
                self._t.t(
                    locale,
                    "wizard.already_verified",
                    support_ticket=self._support_ticket(),
                ),
                ephemeral=True,
            )
            log.info(
                f"[WIZARD] User {user_id} attempted re-verification (already verified)"
            )
            return

        config = self._store.get_guild_config(self.guild_id) if self.guild_id else None
        ttl_hours = config.session_ttl_hours if config else DEFAULT_SESSION_TTL_HOURS

        self._store.create_wizard_session(
            user_id, guild_id=self.guild_id, ttl_hours=ttl_hours
        )
        log.info(
            f"[WIZARD] Created session for user {user_id} (guild: {self.guild_id})"
        )

        self._store.delete_pending_wizard_views_by_user(user_id)

        await interaction.response.defer()
        await interaction.message.edit(view=None)

        embed = discord.Embed(
            title=self._t.t(locale, "wizard.step1.title"),
            description=self._t.t(locale, "wizard.step1.description"),
            colour=discord.Colour.blue(),
        )
        embed.set_footer(text=self._t.t(locale, "wizard.step1.footer"))
        await interaction.followup.send(
            content=self._t.t(locale, "verification.start"),
            embed=embed,
        )
        if self.confirmation_message_id:
            try:
                self._store.delete_pending_wizard_view(self.confirmation_message_id)
            except Exception as e:
                log.warning(f"[WIZARD] Could not clear pending wizard view: {e}")
        log.info(f"[WIZARD] User {user_id} started verification wizard")


class SkipStepsView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        store: ProfileStore,
        translator: Translator,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.user_id = user_id
        self._store = store
        self._t = translator
        self.confirmation_message_id = None
        self.confirmation_channel_id = None
        self.restart_button.label = translator.t(locale, "view.restart")

    @discord.ui.button(
        label="🔄 Restart",
        style=discord.ButtonStyle.danger,
        custom_id="skip_steps_restart",
    )
    async def restart_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                self._t.t(interaction.locale, "wizard.not_your_session"),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await interaction.message.edit(view=None)

        self._store.delete_pending_wizard_views_by_user(self.user_id)
        self._store.update_wizard_session(
            self.user_id, step=1, stfc_link=None, screenshot_data=None
        )

        embed = discord.Embed(
            title=self._t.t(interaction.locale, "wizard.step1.title"),
            description=self._t.t(interaction.locale, "wizard.step1.description"),
            colour=discord.Colour.blue(),
        )
        embed.set_footer(text=self._t.t(interaction.locale, "wizard.step1.footer"))
        await interaction.followup.send(
            content=self._t.t(interaction.locale, "verification.start"),
            embed=embed,
        )
        if self.confirmation_message_id:
            try:
                self._store.delete_pending_wizard_view(self.confirmation_message_id)
            except Exception as e:
                log.warning(f"[WIZARD] Could not clear pending wizard view: {e}")
        log.info(f"[WIZARD] User {self.user_id} restarted verification wizard")


class SessionExpiredView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        store: ProfileStore,
        translator: Translator,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.user_id = user_id
        self._store = store
        self._t = translator
        self.confirmation_message_id = None
        self.confirmation_channel_id = None
        self.restart_button.label = translator.t(locale, "view.restart_verification")

    @discord.ui.button(
        label="🔄 Restart Verification",
        style=discord.ButtonStyle.green,
        custom_id="session_expired_restart",
    )
    async def restart_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                self._t.t(interaction.locale, "wizard.not_your_session"),
                ephemeral=True,
            )
            return

        old_session = self._store.get_wizard_session(self.user_id)
        guild_id = old_session.get("guild_id") if old_session else None
        config = self._store.get_guild_config(guild_id) if guild_id else None
        ttl_hours = config.session_ttl_hours if config else DEFAULT_SESSION_TTL_HOURS

        self._store.create_wizard_session(
            self.user_id, guild_id=guild_id, ttl_hours=ttl_hours
        )
        log.info(f"[WIZARD] Created new session for user {self.user_id} after timeout")

        await interaction.response.defer()
        await interaction.message.edit(view=None)

        self._store.delete_pending_wizard_views_by_user(self.user_id)

        embed = discord.Embed(
            title=self._t.t(interaction.locale, "wizard.step1.title"),
            description=self._t.t(interaction.locale, "wizard.step1.description"),
            colour=discord.Colour.blue(),
        )
        embed.set_footer(
            text=self._t.t(interaction.locale, "wizard.step1.footer_expired")
        )
        await interaction.followup.send(
            content=self._t.t(interaction.locale, "verification.start"),
            embed=embed,
        )
        if self.confirmation_message_id:
            try:
                self._store.delete_pending_wizard_view(self.confirmation_message_id)
            except Exception as e:
                log.warning(f"[WIZARD] Could not clear pending wizard view: {e}")
        log.info(f"[WIZARD] Restarted wizard for user {self.user_id}")


class ConfirmVerificationView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        store: ProfileStore,
        finalize_callback: Callable,
        translator: Translator,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.user_id = user_id
        self._store = store
        self._finalize = finalize_callback
        self._t = translator
        self.confirmation_message_id = None
        self.confirmation_channel_id = None
        self.complete_button.label = translator.t(locale, "view.complete")
        self.restart_button.label = translator.t(locale, "view.restart")

    @discord.ui.button(
        label="✅ Complete",
        style=discord.ButtonStyle.green,
        custom_id="confirm_verification_complete",
    )
    async def complete_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                self._t.t(interaction.locale, "wizard.not_your_session"),
                ephemeral=True,
            )
            return

        session = self._store.get_wizard_session(self.user_id)
        if not session:
            await interaction.response.send_message(
                self._t.t(interaction.locale, "wizard.session_expired"),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        await interaction.message.edit(view=None)

        self._store.delete_pending_wizard_views_by_user(self.user_id)

        session = self._store.get_wizard_session(self.user_id)
        await self._finalize(interaction, session)
        self._store.delete_wizard_session(self.user_id)
        if self.confirmation_message_id:
            try:
                self._store.delete_pending_wizard_view(self.confirmation_message_id)
            except Exception as e:
                log.warning(f"[WIZARD] Could not clear pending wizard view: {e}")

    @discord.ui.button(
        label="🔄 Restart",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_verification_restart",
    )
    async def restart_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                self._t.t(interaction.locale, "wizard.not_your_session"),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await interaction.message.edit(view=None)

        self._store.delete_pending_wizard_views_by_user(self.user_id)
        self._store.update_wizard_session(
            self.user_id, step=1, stfc_link=None, screenshot_data=None
        )

        embed = discord.Embed(
            title=self._t.t(interaction.locale, "wizard.step1.title"),
            description=self._t.t(interaction.locale, "wizard.step1.description"),
            colour=discord.Colour.blue(),
        )
        embed.set_footer(text=self._t.t(interaction.locale, "wizard.step1.footer"))
        await interaction.followup.send(
            content=self._t.t(interaction.locale, "verification.start"),
            embed=embed,
        )
        if self.confirmation_message_id:
            try:
                self._store.delete_pending_wizard_view(self.confirmation_message_id)
            except Exception as e:
                log.warning(f"[WIZARD] Could not clear pending wizard view: {e}")
        log.info(f"[WIZARD] User {self.user_id} restarted verification wizard")


class RankConfirmationView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        member_name: str,
        rank: str,
        player_name: str,
        alliance_tag: str,
        settings,  # GuildConfig or Settings
        store: ProfileStore,
        guild_provider: Callable[[], discord.Guild | None],
        translator: Translator,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.member_name = member_name
        self.rank = rank
        self.player_name = player_name
        self.alliance_tag = alliance_tag
        self.settings = settings
        self.store = store
        self._guild_provider = guild_provider
        self._t = translator
        self.confirmed = None
        self.user_message = None
        self.log_message = None
        self.confirmation_message_id = None
        self.confirmation_channel_id = None
        self.accept_button.label = translator.t(locale, "view.accept")
        self.reject_button.label = translator.t(locale, "view.reject")

    @discord.ui.button(
        label="✅ Accept", style=discord.ButtonStyle.green, custom_id="rank_accept"
    )
    async def accept_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                self._t.t(interaction.locale, "rank.confirm.not_admin"),
                ephemeral=True,
            )
            return
        self.confirmed = True
        await interaction.response.defer()
        await self.on_confirmation(interaction.guild)
        if self.log_message:
            try:
                embed = self.log_message.embeds[0] if self.log_message.embeds else None
                if embed:
                    embed.color = discord.Color.green()
                    embed.title = self._t.t(
                        interaction.locale, "rank.confirm.accepted_title"
                    )
                    await self.log_message.edit(embed=embed, view=None)
            except Exception as e:
                log.warning(f"[CONFIRM] Could not edit log message: {e}")
        self.stop()

    @discord.ui.button(
        label="❌ Reject", style=discord.ButtonStyle.red, custom_id="rank_reject"
    )
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                self._t.t(interaction.locale, "rank.confirm.not_admin"),
                ephemeral=True,
            )
            return
        self.confirmed = False
        await interaction.response.defer()
        await self.on_confirmation(interaction.guild)
        if self.log_message:
            try:
                embed = self.log_message.embeds[0] if self.log_message.embeds else None
                if embed:
                    embed.color = discord.Color.red()
                    embed.title = self._t.t(
                        interaction.locale, "rank.confirm.rejected_title"
                    )
                    await self.log_message.edit(embed=embed, view=None)
            except Exception as e:
                log.warning(f"[CONFIRM] Could not edit log message: {e}")
        self.stop()

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        admin_role_id = getattr(self.settings, "admin_role_id", None)
        if not admin_role_id:
            return True
        role = interaction.guild.get_role(admin_role_id)
        return role is not None and role in interaction.user.roles

    async def on_confirmation(self, guild: discord.Guild):
        member = guild.get_member(self.user_id)
        if not member:
            log.warning(f"[CONFIRM] Member {self.user_id} not found for confirmation")
            return

        commodore_role_id = getattr(self.settings, "commodore_role_id", None)
        admiral_role_id = getattr(self.settings, "admiral_role_id", None)

        if self.confirmed:
            log.info(
                f"[CONFIRM] Admin ACCEPTED rank change for {self.member_name}: {self.rank}"
            )
            commodore_role = (
                guild.get_role(commodore_role_id) if commodore_role_id else None
            )
            admiral_role = guild.get_role(admiral_role_id) if admiral_role_id else None

            rank_tier = self._get_rank_tier(self.rank)

            try:
                if rank_tier == "commodore":
                    if commodore_role:
                        await member.add_roles(
                            commodore_role, reason=f"Confirmed rank: {self.rank}"
                        )
                    if admiral_role and admiral_role in member.roles:
                        await member.remove_roles(admiral_role, reason="Rank downgrade")
                    log.info(f"[CONFIRM] Assigned commodore role to {self.member_name}")
                elif rank_tier == "admiral":
                    if admiral_role:
                        await member.add_roles(
                            admiral_role, reason=f"Confirmed rank: {self.rank}"
                        )
                    if commodore_role and commodore_role in member.roles:
                        await member.remove_roles(
                            commodore_role, reason="Rank promotion"
                        )
                    log.info(f"[CONFIRM] Assigned admiral role to {self.member_name}")
            except Exception as e:
                log.error(f"[CONFIRM] Error assigning leadership role: {e}")

            if self.user_message:
                try:
                    embed = discord.Embed(
                        title=self._t.t(
                            self.user_message.guild.preferred_locale,
                            "rank.confirm.user_accepted_title",
                        ),
                        description=self._t.t(
                            self.user_message.guild.preferred_locale,
                            "rank.confirm.user_accepted_desc",
                            player_name=self.player_name,
                        ),
                        color=discord.Color.green(),
                    )
                    embed.add_field(
                        name=self._t.t(
                            self.user_message.guild.preferred_locale, "rank.label"
                        ),
                        value=self.rank,
                        inline=True,
                    )
                    embed.add_field(
                        name=self._t.t(
                            self.user_message.guild.preferred_locale,
                            "rank.alliance_label",
                        ),
                        value=f"[{self.alliance_tag}]"
                        if self.alliance_tag != "N/A"
                        else "N/A",
                        inline=True,
                    )
                    await self.user_message.edit(embed=embed)
                except Exception as e:
                    log.warning(f"[CONFIRM] Could not edit user message: {e}")

            try:
                dm_embed = discord.Embed(
                    title=self._t.t(None, "rank.confirm.dm_accepted_title"),
                    description=self._t.t(
                        None, "rank.confirm.dm_accepted_desc", rank=self.rank
                    ),
                    color=discord.Color.green(),
                )
                dm_embed.add_field(
                    name=self._t.t(None, "rank.label"), value=self.rank, inline=True
                )
                dm_embed.add_field(
                    name=self._t.t(None, "rank.alliance_label"),
                    value=f"[{self.alliance_tag}]"
                    if self.alliance_tag != "N/A"
                    else "N/A",
                    inline=True,
                )
                dm_embed.add_field(
                    name=self._t.t(None, "rank.confirm.dm_status"),
                    value=self._t.t(None, "rank.confirm.dm_status_value"),
                    inline=False,
                )
                dm_embed.set_footer(text=self._t.t(None, "rank.confirm.dm_footer"))
                await member.send(embed=dm_embed)
                log.info(f"[CONFIRM] Sent DM confirmation to {member.id}")
            except discord.Forbidden:
                log.warning(
                    f"[CONFIRM] Could not send DM to {member.id} (DMs disabled)"
                )
            except Exception as e:
                log.warning(f"[CONFIRM] Error sending DM to {member.id}: {e}")
        else:
            log.info(
                f"[CONFIRM] Admin REJECTED rank change for {self.member_name}: {self.rank}"
            )
            if self.user_message:
                try:
                    embed = discord.Embed(
                        title=self._t.t(
                            self.user_message.guild.preferred_locale,
                            "rank.confirm.user_rejected_title",
                        ),
                        description=self._t.t(
                            self.user_message.guild.preferred_locale,
                            "rank.confirm.user_rejected_desc",
                            rank=self.rank,
                        ),
                        color=discord.Color.red(),
                    )
                    await self.user_message.edit(embed=embed)
                except Exception as e:
                    log.warning(f"[CONFIRM] Could not edit user message: {e}")

            try:
                dm_embed = discord.Embed(
                    title=self._t.t(None, "rank.confirm.dm_rejected_title"),
                    description=self._t.t(
                        None, "rank.confirm.dm_rejected_desc", rank=self.rank
                    ),
                    color=discord.Color.red(),
                )
                dm_embed.add_field(
                    name=self._t.t(None, "rank.confirm.dm_next_steps"),
                    value=self._t.t(None, "rank.confirm.dm_next_steps_value"),
                    inline=False,
                )
                await member.send(embed=dm_embed)
                log.info(f"[CONFIRM] Sent DM rejection notice to {member.id}")
            except discord.Forbidden:
                log.warning(
                    f"[CONFIRM] Could not send DM to {member.id} (DMs disabled)"
                )
            except Exception as e:
                log.warning(f"[CONFIRM] Error sending DM to {member.id}: {e}")

        if self.confirmation_message_id:
            try:
                self.store.delete_pending_rank_confirmation(
                    self.confirmation_message_id
                )
                log.info(
                    f"[CONFIRM] Cleared pending confirmation for {self.member_name}"
                )
            except Exception as e:
                log.warning(f"[CONFIRM] Could not clear pending confirmation: {e}")

    @staticmethod
    def _get_rank_tier(rank: str | None) -> str | None:
        tiers = {
            "agent": "base",
            "operative": "base",
            "premier": "base",
            "commodore": "commodore",
            "admiral": "admiral",
        }
        if not rank:
            return None
        return tiers.get(rank.lower())
