import logging
from typing import Optional

import discord

from bot.config.guild_config import GuildConfig
from bot.core.verification.steps import FINALIZE_STEP, START_STEP, SUBMIT_STEP
from bot.profiles.base import COMMON_CONFIG_FIELDS, VerificationProfile, VerificationResult

log = logging.getLogger("veil_bot")


class VeilSecurityProfile(VerificationProfile):
    name = "veil_security"
    required_inputs = ("stfc_link", "screenshot")
    required_roles = ("ops71_plus_role_id",)
    optional_roles = ("verified_role_id", "admin_role_id")
    features = ("ops_level_check", "server_role_match")
    config_fields = COMMON_CONFIG_FIELDS + (
        "ops71_plus_role_id",
        "minimum_ops_level",
    )

    def build_steps(self) -> list[str]:
        return [START_STEP, SUBMIT_STEP, FINALIZE_STEP]

    def verify(self, answers: dict[str, str]) -> VerificationResult:
        if not answers.get("stfc_link"):
            return VerificationResult(False, "missing_stfc_link")
        return VerificationResult(True)

    def finalize(self, answers: dict[str, str]) -> dict[str, str]:
        return {"event": "verified", "profile": self.name}

    def build_nickname(self, player_data) -> str:
        if player_data.alliance_tag:
            nick = f"[{player_data.server}] {player_data.alliance_tag} - {player_data.username}"
        else:
            nick = f"[{player_data.server}] {player_data.username}"
        if len(nick) > 32:
            nick = nick[:32]
        return nick

    def build_summary_embed(self, player_data, config: GuildConfig, translator, locale=None) -> discord.Embed:
        min_ops = config.minimum_ops_level or 71
        embed = discord.Embed(
            title=translator.t(locale, "wizard.summary_title"),
            description=translator.t(locale, "wizard.summary_description"),
            colour=discord.Colour.gold(),
        )
        embed.add_field(name="Player Name", value=f"{player_data.username}", inline=True)
        embed.add_field(name="OPS Level", value=f"{player_data.level}", inline=True)
        embed.add_field(name="Server", value=f"{player_data.server}", inline=True)
        embed.add_field(name="Alliance", value=player_data.alliance_tag or "None", inline=True)
        ops_eligible = (
            "✅ Yes"
            if player_data.level >= min_ops
            else f"❌ No (Level {player_data.level} < {min_ops})"
        )
        embed.add_field(name="Eligible for OPS 71+ Role", value=ops_eligible, inline=False)
        embed.set_footer(text=translator.t(locale, "wizard.summary_footer"))
        return embed

    def build_log_embed(
        self, member: discord.Member, player_data, session: dict, translator, locale=None
    ) -> discord.Embed:
        embed = discord.Embed(
            title=translator.t(locale, "wizard.log_title"),
            description=f"**{member.mention}** verified as **{player_data.username}**",
            colour=discord.Colour.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Player", value=f"{player_data.username}", inline=True)
        embed.add_field(name="OPS Level", value=f"{player_data.level}", inline=True)
        embed.add_field(name="Server", value=f"{player_data.server}", inline=True)
        embed.add_field(name="Alliance", value=player_data.alliance_tag or "None", inline=True)
        return embed

    async def assign_roles(
        self,
        bot,
        member: discord.Member,
        player_data,
        interaction: discord.Interaction,
        config: GuildConfig,
    ) -> tuple[list[str], Optional[discord.ui.View]]:
        feedback = []
        confirmation_view = None

        guild = member.guild
        server_role = discord.utils.find(
            lambda r: r.name == str(player_data.server),
            guild.roles if guild else [],
        )

        if server_role:
            try:
                await member.add_roles(
                    server_role,
                    reason=f"Verified via stfc.pro (server {player_data.server})",
                )
                feedback.append(f"✅ Server role assigned: `{server_role.name}`")
                log.info(f"[WIZARD] Assigned server role {server_role.name} to {member.id}")
            except Exception as e:
                feedback.append(f"⚠️ Error assigning server role: {e}")
                log.warning(f"[WIZARD] Error assigning server role to {member.id}: {e}")
        else:
            feedback.append(f"⚠️ Server role `{player_data.server}` not found")
            await bot.post_admin_notification(
                guild.id,
                f"❌ Missing server role `{player_data.server}` for user {member.mention}",
            )
            log.error(f"[WIZARD] Server role {player_data.server} not found")

        min_ops = config.minimum_ops_level or 71
        ops_role_id = config.ops71_plus_role_id
        if player_data.level >= min_ops and ops_role_id:
            ops_role = guild.get_role(ops_role_id) if guild else None
            if ops_role:
                try:
                    await member.add_roles(
                        ops_role,
                        reason=f"Verified via stfc.pro - Level {player_data.level} >= {min_ops}",
                    )
                    feedback.append("✅ OPS 71+ role assigned")
                    log.info(f"[WIZARD] Assigned OPS 71+ role to {member.id} (level {player_data.level})")
                except Exception as e:
                    feedback.append(f"⚠️ Error assigning OPS role: {e}")
                    log.warning(f"[WIZARD] Error assigning OPS role to {member.id}: {e}")
        else:
            feedback.append(f"⚠️ OPS level {player_data.level} < {min_ops} - OPS role not assigned")
            log.info(
                f"[WIZARD] Skipped OPS role for {member.id} (level {player_data.level} < {min_ops})"
            )

        return feedback, confirmation_view

    async def handle_update(
        self,
        bot,
        member: discord.Member,
        user_id: int,
        stfc_link: str,
        player_data,
        config: GuildConfig,
    ) -> None:
        old_data = bot.store.get_player_data(user_id)
        old_level = old_data[1] if old_data else None

        new_nick = self.build_nickname(player_data)
        if member.nick != new_nick:
            try:
                await member.edit(nick=new_nick)
                log.info(f"[UPDATE] Updated nickname for {member.id} ({member.name}): {new_nick}")
            except discord.Forbidden:
                log.debug(f"[UPDATE] Could not update nickname for {member.id} (Forbidden)")
            except Exception as e:
                log.warning(f"[UPDATE] Error updating nickname for {member.id}: {e}")

        if old_level != player_data.level:
            log.info(f"[UPDATE] {member.id} ({member.name}) level changed: {old_level} → {player_data.level}")
            min_ops = config.minimum_ops_level or 71
            ops_role_id = config.ops71_plus_role_id
            has_ops_role = any(r.id == ops_role_id for r in member.roles) if ops_role_id else False

            if player_data.level >= min_ops and not has_ops_role and ops_role_id:
                guild = member.guild
                ops_role = guild.get_role(ops_role_id) if guild else None
                if ops_role:
                    try:
                        await member.add_roles(
                            ops_role,
                            reason=f"Auto-promoted to OPS 71+ (level {player_data.level})",
                        )
                        log.info(f"[UPDATE] Promoted {member.id} ({member.name}) to OPS 71+ (level {player_data.level})")
                    except Exception as e:
                        log.warning(f"[UPDATE] Could not assign OPS role to {member.id}: {e}")

        bot.store.store_stfc_player(user_id, stfc_link, player_data)
