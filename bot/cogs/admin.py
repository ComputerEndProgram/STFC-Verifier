import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.i18n.translator import Translator
from bot.core.store import _support_ticket_text
from bot.core.views import ChannelStartView, StartWizardView
from bot.config.profiles import get_profile
from bot.core.stfc_scraper import STFCProScraper, format_player_info

log = logging.getLogger("veil_bot")

_RANK_TIERS = {
    "agent": "base",
    "operative": "base",
    "premier": "base",
    "commodore": "commodore",
    "admiral": "admiral",
}


def _get_rank_tier(rank: Optional[str]) -> Optional[str]:
    if not rank:
        return None
    return _RANK_TIERS.get(rank.lower())


class AdminCog(commands.Cog):
    """Handles admin commands and guild configuration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._t = Translator(getattr(bot.settings, "default_language", "en"))

    admin = app_commands.Group(name="admin", description="Admin commands")

    @admin.command(
        name="recall",
        description="[ADMIN] Recall a user's verification, remove all roles, and alert them",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        user="The user to recall verification for",
        reason="Reason for the recall",
    )
    async def recall_verification_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str = "No reason provided",
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ Could not verify your permissions.",
                ephemeral=True,
            )

        config = self.bot.get_guild_config(interaction.guild.id)
        if not config:
            if interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message(
                    "⚠️ This server is not configured yet. Please configure it in the admin web UI.",
                    ephemeral=True,
                )
            return await interaction.response.send_message(
                "⚠️ The verification bot has not been configured for this server yet.",
                ephemeral=True,
            )

        store = self.bot.store
        _t = self._t
        locale = interaction.locale

        admin_role = (
            interaction.guild.get_role(config.admin_role_id)
            if config.admin_role_id
            else None
        )
        is_admin_user = (admin_role and admin_role in interaction.user.roles) or interaction.user.guild_permissions.administrator
        if not is_admin_user:
            return await interaction.response.send_message(
                "❌ You do not have permission to use this command.",
                ephemeral=True,
            )

        await interaction.response.defer(thinking=True)

        player_data = store.get_player_data(user.id)
        if not player_data:
            return await interaction.followup.send(
                f"❌ **{user.mention}** has not verified their STFC account yet.",
                ephemeral=True,
            )

        guild = interaction.guild
        member = guild.get_member(user.id)
        if not member:
            return await interaction.followup.send(
                "❌ User is not in the server or could not be found.",
                ephemeral=True,
            )

        try:
            roles_to_remove = []

            if config.member_role_id:
                member_role = guild.get_role(config.member_role_id)
                if member_role and member_role in member.roles:
                    roles_to_remove.append(member_role)

            if config.commodore_role_id:
                commodore_role = guild.get_role(config.commodore_role_id)
                if commodore_role and commodore_role in member.roles:
                    roles_to_remove.append(commodore_role)

            if config.admiral_role_id:
                admiral_role = guild.get_role(config.admiral_role_id)
                if admiral_role and admiral_role in member.roles:
                    roles_to_remove.append(admiral_role)

            if config.ops71_plus_role_id:
                ops_role = guild.get_role(config.ops71_plus_role_id)
                if ops_role and ops_role in member.roles:
                    roles_to_remove.append(ops_role)

            if config.verified_role_id:
                verify_role = guild.get_role(config.verified_role_id)
                if verify_role and verify_role in member.roles:
                    roles_to_remove.append(verify_role)

            alliance_role_id = store.get_user_alliance_role_id(user.id)
            if alliance_role_id:
                alliance_role = guild.get_role(alliance_role_id)
                if alliance_role and alliance_role in member.roles:
                    roles_to_remove.append(alliance_role)

            if player_data and len(player_data) >= 3:
                server_role = discord.utils.find(
                    lambda r: r.name == str(player_data[2]),
                    guild.roles,
                )
                if server_role and server_role in member.roles:
                    roles_to_remove.append(server_role)

            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"[RECALL] {reason}")
                log.info(f"[RECALL] Removed {len(roles_to_remove)} roles from {member.id}")
        except Exception as e:
            log.warning(f"[RECALL] Error removing roles from {member.id}: {e}")

        store.delete_verification(user.id)
        store.log_verification_action(user.id, "recalled", interaction.user.id, reason)

        try:
            embed = discord.Embed(
                title=_t.t(locale, "wizard.recalled_title"),
                description=_t.t(locale, "wizard.recalled_desc"),
                colour=discord.Colour.red(),
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(
                name=_t.t(locale, "wizard.recalled_what"),
                value=_t.t(locale, "wizard.recalled_what_value"),
                inline=False,
            )
            embed.set_footer(text=_t.t(locale, "wizard.recalled_footer"))

            msg = await member.send(
                embed=embed,
                view=StartWizardView(
                    store,
                    lambda: _support_ticket_text(config.support_channel_id),
                    self._t,
                    guild_id=guild.id,
                    locale=locale,
                ),
            )
            store.save_pending_wizard_view(msg.id, msg.channel.id, member.id, "StartWizardView")
            log.info(f"[RECALL] Sent recall notification to {member.id}")
        except discord.Forbidden:
            log.warning(f"[RECALL] Could not send DM to {member.id} (DMs disabled)")
        except Exception as e:
            log.warning(f"[RECALL] Error sending DM to {member.id}: {e}")

        await interaction.followup.send(
            _t.t(locale, "wizard.recalled_success", member=member.mention),
            ephemeral=True,
        )

        if config.log_channel_id:
            embed = discord.Embed(
                title=_t.t(locale, "wizard.log_recalled_title"),
                description=f"**{member.mention}** verification recalled by {interaction.user.mention}",
                colour=discord.Colour.red(),
                timestamp=interaction.created_at,
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            if player_data:
                embed.add_field(name="Player", value=f"{player_data[0]}", inline=True)
                rank_field = player_data[4] if len(player_data) > 4 else None
                if rank_field:
                    embed.add_field(name=_t.t(locale, "rank.label"), value=f"{rank_field}", inline=True)

            try:
                await self.bot.post_to_log_channel(guild.id, embed=embed)
                log.info("[RECALL] Logged recall to log channel")
            except Exception as e:
                log.warning(f"[RECALL] Could not log to channel: {e}")

        log.info(f"[RECALL] user={member.id} admin={interaction.user.id} reason={reason}")

    @admin.command(
        name="verify",
        description="[ADMIN] Manually verify a user with their STFC player link (skips wizard)",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        player_url="Player stfc.pro/stfc.wtf URL or numeric player ID",
        user="The Discord user to verify",
    )
    async def admin_verify_cmd(
        self,
        interaction: discord.Interaction,
        player_url: str,
        user: discord.User,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ Could not verify your permissions.",
                ephemeral=True,
            )

        config = self.bot.get_guild_config(interaction.guild.id)
        if not config:
            if interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message(
                    "⚠️ This server is not configured yet. Please configure it in the admin web UI.",
                    ephemeral=True,
                )
            return await interaction.response.send_message(
                "⚠️ The verification bot has not been configured for this server yet.",
                ephemeral=True,
            )

        store = self.bot.store

        admin_role = (
            interaction.guild.get_role(config.admin_role_id)
            if config.admin_role_id
            else None
        )
        is_admin_user = (admin_role and admin_role in interaction.user.roles) or interaction.user.guild_permissions.administrator
        if not is_admin_user:
            return await interaction.response.send_message(
                "❌ You do not have permission to use this command.",
                ephemeral=True,
            )

        await interaction.response.defer(thinking=True)

        guild = interaction.guild
        member = guild.get_member(user.id)
        if not member:
            return await interaction.followup.send(
                "❌ User is not in the server or could not be found.",
                ephemeral=True,
            )

        player_id = STFCProScraper.extract_player_id_from_url(player_url.strip())
        if not player_id:
            return await interaction.followup.send(
                "❌ Invalid player link. Use format:\n"
                "`https://stfc.pro/players/XXXXXXXXXXXXX` or `https://stfc.wtf/players/XXXXXXXXXXXXX` or just `XXXXXXXXXXXXX`",
                ephemeral=True,
            )

        player_data = STFCProScraper.fetch_player_data(player_id)
        if not player_data:
            return await interaction.followup.send(
                f"❌ Could not fetch player data from stfc.pro for ID `{player_id}`. Check the link.",
                ephemeral=True,
            )

        if store.is_player_id_taken(player_id, exclude_user_id=user.id):
            return await interaction.followup.send(
                "❌ This STFC player account is already linked to another Discord user.",
                ephemeral=True,
            )

        profile = get_profile(config.bot_profile)

        feedback = ["📋 **Admin Verification Complete**\n"]
        feedback.append("✅ **stfc.pro Data:**")
        feedback.append(f"  {format_player_info(player_data)}\n")

        new_nick = profile.build_nickname(player_data)
        try:
            await member.edit(nick=new_nick)
            feedback.append(f"✅ Nickname set to: `{new_nick}`")
            log.info(f"[ADMIN] Set nickname for {member.id}: {new_nick}")
        except discord.Forbidden:
            feedback.append("⚠️ Could not set nickname (missing permissions)")
            log.warning(f"[ADMIN] Could not set nickname for {member.id} (Forbidden)")
        except Exception as e:
            feedback.append(f"⚠️ Error setting nickname: {e}")
            log.error(f"[ADMIN] Error setting nickname for {member.id}: {e}")

        store.store_stfc_player(member.id, player_url, player_data)
        store.delete_pending_wizard_views_by_user(member.id)

        try:
            role_feedback, confirmation_view = await profile.assign_roles(
                self.bot, member, player_data, interaction, config
            )
            feedback.extend(role_feedback)
        except Exception as e:
            feedback.append(f"❌ Error assigning roles: {e}")
            log.error(f"[ADMIN] Error assigning roles to {member.id}: {e}")
            confirmation_view = None

        store.mark_verified(member.id)
        store.log_verification_action(
            member.id, "verified", interaction.user.id, "Manual admin verification"
        )
        feedback.append("💾 Player data stored for periodic updates")

        if config.verified_role_id:
            verify_role = guild.get_role(config.verified_role_id)
            if verify_role:
                try:
                    await member.add_roles(verify_role, reason="Verified via admin command")
                    feedback.append("✅ Verification role assigned")
                    log.info(f"[ADMIN] Assigned verify role to {member.id}")
                except Exception as e:
                    feedback.append(f"⚠️ Error assigning verify role: {e}")
                    log.warning(f"[ADMIN] Error assigning verify role to {member.id}: {e}")

        feedback_text = "\n".join(feedback)
        await interaction.followup.send(feedback_text, ephemeral=True)

        if config.log_channel_id:
            session = {
                "user_id": member.id,
                "stfc_link": player_url,
                "screenshot_data": None,
            }
            embed = profile.build_log_embed(member, player_data, session)
            embed.add_field(
                name="Action",
                value=f"Manual verification by {interaction.user.mention}",
                inline=False,
            )
            rank_tier = _get_rank_tier(getattr(player_data, "rank", None))
            if rank_tier and rank_tier != "base":
                embed.add_field(name="Rank Tier", value=rank_tier.title(), inline=True)

            try:
                log_msg = await self.bot.post_to_log_channel(guild.id, embed=embed)
                log.info("[ADMIN] Logged manual verification to log channel")

                if confirmation_view and log_msg:
                    confirmation_view.log_message = log_msg
                    admin_ping = (
                        f"<@&{config.admin_role_id}>" if config.admin_role_id else "Admins"
                    )
                    alliance_display = (
                        f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
                    )
                    confirm_embed = discord.Embed(
                        title="🔔 Leadership Rank Confirmation Required",
                        description="Please confirm this rank promotion.",
                        color=discord.Color.orange(),
                    )
                    confirm_embed.add_field(
                        name="Player",
                        value=f"{member.mention} ({player_data.username})",
                        inline=False,
                    )
                    confirm_embed.add_field(
                        name="Rank",
                        value=getattr(player_data, "rank", "N/A"),
                        inline=True,
                    )
                    confirm_embed.add_field(
                        name="Alliance", value=alliance_display, inline=True
                    )
                    confirm_msg = await self.bot.post_to_log_channel(
                        guild.id, embed=confirm_embed, view=confirmation_view, content=admin_ping
                    )
                    if confirm_msg:
                        confirmation_view.log_message = confirm_msg
                        confirmation_view.confirmation_message_id = confirm_msg.id
                        confirmation_view.confirmation_channel_id = confirm_msg.channel.id
                        store.save_pending_rank_confirmation(
                            confirm_msg.id,
                            confirm_msg.channel.id,
                            member.id,
                            str(member),
                            player_data.rank,
                            player_data.username,
                            player_data.alliance_tag or "N/A",
                        )
            except Exception as e:
                log.warning(f"[ADMIN] Could not log to channel: {e}")

        log.info(
            f"[ADMIN] user={member.id} name={player_data.username} "
            f"server={player_data.server} alliance={player_data.alliance_tag} "
            f"level={player_data.level} admin={interaction.user.id}"
        )

    @admin.command(
        name="send_button",
        description="[ADMIN] Post the verification button to the verify channel",
    )
    @app_commands.guild_only()
    async def send_button_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ Could not verify your permissions.",
                ephemeral=True,
            )

        config = self.bot.get_guild_config(interaction.guild.id)
        if not config:
            if interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message(
                    "⚠️ This server is not configured yet. Please configure it in the admin web UI.",
                    ephemeral=True,
                )
            return await interaction.response.send_message(
                "⚠️ The verification bot has not been configured for this server yet.",
                ephemeral=True,
            )

        admin_role = (
            interaction.guild.get_role(config.admin_role_id)
            if config.admin_role_id
            else None
        )
        is_admin_user = (admin_role and admin_role in interaction.user.roles) or interaction.user.guild_permissions.administrator
        if not is_admin_user:
            return await interaction.response.send_message(
                "❌ You do not have permission to use this command.",
                ephemeral=True,
            )

        if not config.verify_channel_id:
            return await interaction.response.send_message(
                "❌ Verification channel is not configured for this server.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        channel = guild.get_channel(config.verify_channel_id)
        if not channel:
            return await interaction.followup.send(
                f"❌ Verify channel <#{config.verify_channel_id}> not found.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="STFC Verification",
            description="Click the button below to start the verification process.",
            colour=discord.Colour.blurple(),
        )

        try:
            await channel.send(embed=embed, view=ChannelStartView())
            await interaction.followup.send(
                f"✅ Verification button posted to <#{config.verify_channel_id}>.",
                ephemeral=True,
            )
            log.info(
                f"[ADMIN] Sent verification button to channel {config.verify_channel_id} by {interaction.user.id}"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to send messages in that channel.",
                ephemeral=True,
            )
            log.warning(
                f"[ADMIN] Could not send to verify channel {config.verify_channel_id} (Forbidden)"
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            log.error(f"[ADMIN] Error sending verification button: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
