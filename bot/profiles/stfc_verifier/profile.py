import logging

import discord

from bot.config.guild_config import GuildConfig
from bot.core.verification.steps import FINALIZE_STEP, START_STEP, SUBMIT_STEP
from bot.core.views import RankConfirmationView
from bot.profiles.base import (
    COMMON_CONFIG_FIELDS,
    VerificationProfile,
    VerificationResult,
)

log = logging.getLogger("veil_bot")


def get_rank_tier(rank: str | None) -> str | None:
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


class STFCVerifierProfile(VerificationProfile):
    name = "stfc_verifier"
    required_inputs = ("stfc_link", "screenshot")
    required_roles = ("member_role_id", "commodore_role_id", "admiral_role_id")
    optional_roles = ("verified_role_id", "admin_role_id")
    features = ("rank_tiers", "alliance_roles", "server_check", "rank_confirmation")
    config_fields = COMMON_CONFIG_FIELDS + (
        "member_role_id",
        "commodore_role_id",
        "admiral_role_id",
        "stfc_server_number",
        "manage_alliance_roles",
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
            nick = f"[{player_data.alliance_tag}] {player_data.username}"
        else:
            nick = player_data.username
        if len(nick) > 32:
            nick = nick[:32]
        return nick

    def build_summary_embed(
        self, player_data, config: GuildConfig, translator, locale=None
    ) -> discord.Embed:
        embed = discord.Embed(
            title=translator.t(locale, "wizard.summary_title"),
            description=translator.t(locale, "wizard.summary_description"),
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="Player Name", value=f"{player_data.username}", inline=True
        )
        embed.add_field(name="Level", value=f"{player_data.level}", inline=True)
        embed.add_field(name="Server", value=f"{player_data.server}", inline=True)
        embed.add_field(
            name="Alliance", value=player_data.alliance_tag or "None", inline=True
        )
        embed.add_field(
            name="Rank", value=getattr(player_data, "rank", "Unknown"), inline=True
        )
        embed.set_footer(text=translator.t(locale, "wizard.summary_footer"))
        return embed

    def build_log_embed(
        self,
        member: discord.Member,
        player_data,
        session: dict,
        translator,
        locale=None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=translator.t(locale, "wizard.log_title"),
            description=f"**{member.mention}** verified as **{player_data.username}**",
            colour=discord.Colour.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Player", value=f"{player_data.username}", inline=True)
        embed.add_field(
            name="Rank", value=getattr(player_data, "rank", "N/A"), inline=True
        )
        embed.add_field(name="Level", value=f"{player_data.level}", inline=True)
        embed.add_field(name="Server", value=f"{player_data.server}", inline=True)
        embed.add_field(
            name="Alliance", value=player_data.alliance_tag or "None", inline=True
        )
        return embed

    async def assign_roles(
        self,
        bot,
        member: discord.Member,
        player_data,
        interaction: discord.Interaction,
        config: GuildConfig,
    ) -> tuple[list[str], RankConfirmationView | None]:
        feedback = []
        confirmation_view = None

        stfc_server_id = config.stfc_server_number
        if stfc_server_id and player_data.server != stfc_server_id:
            await interaction.followup.send(
                bot._t.t(
                    interaction.locale,
                    "verification.server_wrong",
                    server_id=stfc_server_id,
                    current_server=player_data.server,
                ),
                ephemeral=True,
            )
            log.warning(
                f"[WIZARD] User {member.id} attempted verification on wrong "
                f"server: {player_data.server} (expected {stfc_server_id})"
            )
            return feedback, confirmation_view

        guild = member.guild
        member_role = (
            guild.get_role(config.member_role_id)
            if config.member_role_id and guild
            else None
        )
        commodore_role = (
            guild.get_role(config.commodore_role_id)
            if config.commodore_role_id and guild
            else None
        )
        admiral_role = (
            guild.get_role(config.admiral_role_id)
            if config.admiral_role_id and guild
            else None
        )

        rank_tier = get_rank_tier(getattr(player_data, "rank", None))

        if not member_role:
            feedback.append(
                f"❌ Member role {config.member_role_id} not found - cannot assign ranks"
            )
            log.error(
                f"[WIZARD] Member role {config.member_role_id} not found for {member.id}"
            )
        else:
            try:
                await member.add_roles(
                    member_role, reason=f"Verified rank: {player_data.rank}"
                )
                feedback.append(f"✅ Base role assigned (rank: {player_data.rank})")

                if rank_tier == "base":
                    if commodore_role and commodore_role in member.roles:
                        await member.remove_roles(
                            commodore_role, reason="Rank downgrade"
                        )
                    if admiral_role and admiral_role in member.roles:
                        await member.remove_roles(admiral_role, reason="Rank downgrade")
                    log.info(
                        f"[WIZARD] Assigned base role to {member.id} (rank: {player_data.rank})"
                    )

                elif rank_tier in ("commodore", "admiral"):
                    confirmation_view = RankConfirmationView(
                        member.id,
                        member.name,
                        player_data.rank,
                        player_data.username,
                        player_data.alliance_tag or "N/A",
                        config,
                        bot.store,
                        lambda: guild,
                        bot._t,
                        locale=interaction.locale,
                    )
                    role_name = "Commodore" if rank_tier == "commodore" else "Admiral"
                    feedback.append(
                        f"⏳ {role_name} role pending admin confirmation..."
                    )
                    log.info(
                        f"[WIZARD] Created confirmation for {member.id}: {role_name} rank"
                    )
            except Exception as e:
                feedback.append(f"❌ Error assigning roles: {e}")
                log.error(f"[WIZARD] Error assigning roles to {member.id}: {e}")

        if config.manage_alliance_roles:
            if player_data.alliance_tag:
                alliance_role = await self._get_or_create_alliance_role(
                    guild, player_data.alliance_tag
                )
                if alliance_role:
                    try:
                        await member.add_roles(
                            alliance_role,
                            reason=f"Alliance tag: {player_data.alliance_tag}",
                        )
                        feedback.append(
                            f"✅ Alliance role assigned: `{alliance_role.name}`"
                        )
                        bot.store.update_user_alliance_role_id(
                            member.id, alliance_role.id
                        )
                        log.info(
                            f"[WIZARD] Assigned alliance role {alliance_role.name} to {member.id}"
                        )
                    except Exception as e:
                        feedback.append(f"⚠️ Error assigning alliance role: {e}")
                        log.warning(
                            f"[WIZARD] Error assigning alliance role to {member.id}: {e}"
                        )
            else:
                na_role = await self._get_or_create_na_role(guild)
                if na_role:
                    try:
                        await member.add_roles(na_role, reason="No alliance")
                        feedback.append(f"✅ Alliance role assigned: `{na_role.name}`")
                        bot.store.update_user_alliance_role_id(member.id, na_role.id)
                        log.info(f"[WIZARD] Assigned N/A role to {member.id}")
                    except Exception as e:
                        feedback.append(f"⚠️ Error assigning N/A role: {e}")
                        log.warning(
                            f"[WIZARD] Error assigning N/A role to {member.id}: {e}"
                        )

        return feedback, confirmation_view

    async def _get_or_create_alliance_role(
        self, guild: discord.Guild, alliance_tag: str
    ) -> discord.Role | None:
        if not guild:
            return None
        for role in guild.roles:
            if role.name == alliance_tag:
                return role
        try:
            new_role = await guild.create_role(
                name=alliance_tag,
                color=discord.Color.blue(),
                reason=f"Auto-created for alliance tag: {alliance_tag}",
            )
            log.info(f"[ALLIANCE] Created new role: {alliance_tag} (ID: {new_role.id})")
            return new_role
        except discord.Forbidden:
            log.error(f"[ALLIANCE] No permission to create role {alliance_tag}")
            return None
        except Exception as e:
            log.error(f"[ALLIANCE] Error creating role {alliance_tag}: {e}")
            return None

    async def _get_or_create_na_role(self, guild: discord.Guild) -> discord.Role | None:
        if not guild:
            return None
        for role in guild.roles:
            if role.name == "N/A":
                return role
        try:
            new_role = await guild.create_role(
                name="N/A",
                color=discord.Color.light_gray(),
                reason="Auto-created for users without an alliance",
            )
            log.info(f"[ALLIANCE] Created new N/A role (ID: {new_role.id})")
            return new_role
        except discord.Forbidden:
            log.error("[ALLIANCE] No permission to create N/A role")
            return None
        except Exception as e:
            log.error(f"[ALLIANCE] Error creating N/A role: {e}")
            return None

    async def handle_update(
        self,
        bot,
        member: discord.Member,
        user_id: int,
        stfc_link: str,
        player_data,
        config: GuildConfig,
    ) -> None:
        old_data = bot.store.get_user_full_data(user_id)
        if not old_data:
            return

        old_rank = old_data[4] if len(old_data) > 4 else None
        old_alliance_tag = old_data[3] if len(old_data) > 3 else None
        old_alliance_role_id = old_data[5] if len(old_data) > 5 else None

        guild = member.guild

        new_nick = self.build_nickname(player_data)
        if member.nick != new_nick:
            try:
                await member.edit(nick=new_nick)
                log.info(
                    f"[UPDATE] Updated nickname for {member.id} ({member.name}): {new_nick}"
                )
            except discord.Forbidden:
                log.debug(
                    f"[UPDATE] Could not update nickname for {member.id} (Forbidden)"
                )
            except Exception as e:
                log.warning(f"[UPDATE] Error updating nickname for {member.id}: {e}")

        if config.manage_alliance_roles:
            new_alliance_tag = player_data.alliance_tag or "N/A"
            alliance_changed = old_alliance_tag != new_alliance_tag
            needs_initial_assignment = (
                new_alliance_tag != "N/A" and not old_alliance_role_id
            ) or (
                new_alliance_tag == "N/A"
                and old_alliance_tag
                and not old_alliance_role_id
            )

            if alliance_changed or needs_initial_assignment:
                if alliance_changed:
                    log.info(
                        f"[UPDATE] Alliance change for {member.id}: {old_alliance_tag} → {new_alliance_tag}"
                    )
                else:
                    log.info(
                        f"[UPDATE] Initial alliance role for {member.id}: {new_alliance_tag}"
                    )

                if old_alliance_role_id and guild:
                    old_role = guild.get_role(old_alliance_role_id)
                    if old_role and old_role in member.roles:
                        try:
                            await member.remove_roles(
                                old_role,
                                reason=f"Alliance changed from {old_alliance_tag} to {new_alliance_tag}",
                            )
                            log.info(
                                f"[UPDATE] Removed old alliance role {old_role.name} from {member.id}"
                            )
                        except Exception as e:
                            log.warning(
                                f"[UPDATE] Error removing old alliance role from {member.id}: {e}"
                            )

                if new_alliance_tag == "N/A":
                    new_role = await self._get_or_create_na_role(guild)
                else:
                    new_role = await self._get_or_create_alliance_role(
                        guild, new_alliance_tag
                    )

                if new_role:
                    try:
                        if new_role not in member.roles:
                            await member.add_roles(
                                new_role, reason=f"Alliance tag: {new_alliance_tag}"
                            )
                        log.info(
                            f"[UPDATE] Assigned alliance role {new_role.name} to {member.id}"
                        )
                        bot.store.update_user_alliance_role_id(user_id, new_role.id)
                    except Exception as e:
                        log.warning(
                            f"[UPDATE] Error assigning new alliance role to {member.id}: {e}"
                        )

        if old_rank != player_data.rank:
            log.info(
                f"[UPDATE] Rank change for {member.id}: {old_rank} → {player_data.rank}"
            )
            confirmation_view = RankConfirmationView(
                member.id,
                member.name,
                player_data.rank,
                player_data.username,
                player_data.alliance_tag or "N/A",
                config,
                bot.store,
                lambda: guild,
                bot._t,
                locale=getattr(member.guild, "preferred_locale", None),
            )
            admin_ping = (
                f"<@&{config.admin_role_id}>" if config.admin_role_id else "Admins"
            )
            alliance_display = (
                f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
            )
            confirm_embed = discord.Embed(
                title=bot._t.t(None, "wizard.log_update_confirm_title"),
                description=f"{admin_ping}, please confirm this rank change.",
                color=discord.Color.orange(),
            )
            confirm_embed.add_field(
                name="Player",
                value=f"{member.mention} ({player_data.username})",
                inline=False,
            )
            confirm_embed.add_field(
                name="Previous Rank", value=old_rank or "N/A", inline=True
            )
            confirm_embed.add_field(
                name="New Rank", value=player_data.rank or "N/A", inline=True
            )
            confirm_embed.add_field(
                name="Alliance", value=alliance_display, inline=True
            )
            log_msg = await bot.post_to_log_channel(
                guild.id, embed=confirm_embed, view=confirmation_view
            )
            if log_msg:
                confirmation_view.log_message = log_msg
                confirmation_view.confirmation_message_id = log_msg.id
                confirmation_view.confirmation_channel_id = log_msg.channel.id
                bot.store.save_pending_rank_confirmation(
                    log_msg.id,
                    log_msg.channel.id,
                    member.id,
                    str(member),
                    player_data.rank,
                    player_data.username,
                    player_data.alliance_tag or "N/A",
                )

        bot.store.store_stfc_player(user_id, stfc_link, player_data)
