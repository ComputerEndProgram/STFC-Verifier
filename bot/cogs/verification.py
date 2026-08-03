import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.i18n.translator import Translator
from bot.core.store import _support_ticket_text
from bot.core.views import StartWizardView

log = logging.getLogger("veil_bot")


class VerificationCog(commands.Cog):
    """Handles STFC verification commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._t = Translator(getattr(bot.settings, "default_language", "en"))

    @app_commands.command(
        name="verify",
        description="Start STFC verification wizard",
    )
    @app_commands.guild_only()
    async def verify_cmd(self, interaction: discord.Interaction):
        locale = interaction.locale
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id
        config = self.bot.get_guild_config(guild_id) if guild_id else None

        if not config:
            if interaction.user.guild_permissions.manage_guild:
                await interaction.followup.send(
                    "⚠️ The verification bot is not configured for this server yet. Please configure it in the admin web UI.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "⚠️ The verification bot has not been configured for this server yet. Please contact a server administrator.",
                    ephemeral=True,
                )
            return

        store = self.bot.store
        _t = self._t

        if store.get_player_data(guild_id, interaction.user.id):
            support_id = config.support_channel_id
            ticket_text = (
                f"Open a support ticket in <#{support_id}>."
                if support_id
                else "Open a support ticket using the support process configured by your admins."
            )
            await interaction.followup.send(
                _t.t(
                    locale, "verification.already_verified", support_ticket=ticket_text
                ),
                ephemeral=True,
            )
            log.info(
                f"[WIZARD] User {interaction.user.id} attempted re-verification via command (already verified)"
            )
            return

        embed = discord.Embed(
            title=_t.t(locale, "wizard.welcome.title"),
            description=_t.t(locale, "wizard.welcome.description"),
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name=_t.t(locale, "wizard.welcome.field_what"),
            value=_t.t(locale, "wizard.welcome.field_what_value"),
            inline=False,
        )
        embed.add_field(
            name=_t.t(locale, "wizard.welcome.field_rules"),
            value=_t.t(locale, "wizard.welcome.field_rules_value"),
            inline=False,
        )
        embed.add_field(
            name=_t.t(locale, "wizard.welcome.field_ready"),
            value=_t.t(locale, "wizard.welcome.field_ready_value"),
            inline=False,
        )
        embed.set_footer(text=_t.t(locale, "wizard.welcome.footer"))

        try:
            msg = await interaction.user.send(
                embed=embed,
                view=StartWizardView(
                    store,
                    lambda: _support_ticket_text(config.support_channel_id),
                    self._t,
                    guild_id=guild_id,
                    locale=interaction.locale,
                ),
            )
            store.save_pending_wizard_view(
                msg.id, msg.channel.id, interaction.user.id, "StartWizardView"
            )
            await interaction.followup.send(
                _t.t(locale, "verification.dm_sent"),
                ephemeral=True,
            )
            log.info(
                f"[WIZARD] User {interaction.user.id} triggered verification via /verify command"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                _t.t(locale, "verification.dm_failed"),
                ephemeral=True,
            )
            log.warning(
                f"[WIZARD] Could not send DM to {interaction.user.id} (DMs disabled)"
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
