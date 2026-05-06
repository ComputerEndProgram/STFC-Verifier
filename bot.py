"""
STFC Rank-Based Discord Bot - Alliance Rank Management

Features:
  - Verify STFC players via stfc.pro/stfc.wtf data
  - Extract alliance rank (Agent, Operative, Premier, Commodore, Admiral)
  - Set nicknames to [TAG] username format
  - Assign roles based on alliance rank
  - Request admin confirmation for Commodore/Admiral promotions
  - Detect rank changes on daily updates and request confirmation
  - Screenshot logging for verification records
"""

import os
import re
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands, ui
from discord.ext import tasks, commands
from dotenv import load_dotenv

from stfc_scraper import STFCProScraper, PlayerData

# ---------------------------------------------------------------------------
# Environment & Logging
# ---------------------------------------------------------------------------
load_dotenv()

DEBUG = os.getenv("DEBUG", "0") not in ("0", "", "false", "False", "no", "No")
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)
log = logging.getLogger("stfc_rank_bot")


# ---------------------------------------------------------------------------
# Config Helpers
# ---------------------------------------------------------------------------
def _env_int(name: str, required: bool = True, default: Optional[int] = None) -> Optional[int]:
    """Load integer from environment variable."""
    v = os.getenv(name)
    if v is None or v == "":
        if required:
            raise SystemExit(f"Missing required env var: {name}")
        return default
    try:
        return int(v)
    except ValueError:
        raise SystemExit(f"Env var {name} must be an integer.")


def _env_str(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    """Load string from environment variable."""
    v = os.getenv(name)
    if v is None or v == "":
        if required:
            raise SystemExit(f"Missing required env var: {name}")
        return default
    return v


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DISCORD_TOKEN = _env_str("DISCORD_TOKEN")
GUILD_ID = _env_int("GUILD_ID")
STFC_SERVER_ID = _env_int("STFC_SERVER_ID")

VERIFY_CHANNEL_ID = _env_int("VERIFY_CHANNEL_ID")
LOG_CHANNEL_ID = _env_int("LOG_CHANNEL_ID", required=False, default=0)

MEMBER_ROLE_ID = _env_int("MEMBER_ROLE_ID")
COMMODORE_ROLE_ID = _env_int("COMMODORE_ROLE_ID")
ADMIRAL_ROLE_ID = _env_int("ADMIRAL_ROLE_ID")
ADMIN_ROLE_ID = _env_int("ADMIN_ROLE_ID", required=False, default=0)

UPDATE_CHECK_HOURS = int(os.getenv("UPDATE_CHECK_HOURS", "24"))
DB_PATH = os.getenv("DB_PATH", "stfc_players.db")
ENABLE_ALLIANCE_ROLES = os.getenv("ENABLE_ALLIANCE_ROLES", "0") not in ("0", "", "false", "False", "no", "No")

log.info(
    "Config: GUILD=%s STFC_SERVER=%s MEMBER_ROLE=%s COMMODORE_ROLE=%s ADMIRAL_ROLE=%s "
    "ADMIN_ROLE=%s VERIFY_CH=%s LOG_CH=%s UPDATE_CHECK=%sh ALLIANCE_ROLES=%s",
    GUILD_ID, STFC_SERVER_ID, MEMBER_ROLE_ID, COMMODORE_ROLE_ID, ADMIRAL_ROLE_ID,
    ADMIN_ROLE_ID, VERIFY_CHANNEL_ID, LOG_CHANNEL_ID, UPDATE_CHECK_HOURS, ENABLE_ALLIANCE_ROLES,
)


# ---------------------------------------------------------------------------
# Rank Classification
# ---------------------------------------------------------------------------
RANK_TIERS = {
    "agent": "base",
    "operative": "base",
    "premier": "base",
    "commodore": "commodore",
    "admiral": "admiral",
}

def get_rank_tier(rank: Optional[str]) -> Optional[str]:
    """Get the tier category for a rank."""
    if not rank:
        return None
    return RANK_TIERS.get(rank.lower())


# ---------------------------------------------------------------------------
# SQLite Store for STFC Player Links
# ---------------------------------------------------------------------------
class Store:
    """SQLite wrapper to store STFC player links and rank data."""

    def __init__(self, path: str):
        self.path = path
        self._init_db()

    def _init_db(self):
        """Initialize database tables."""
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stfc_players (
                    user_id INTEGER PRIMARY KEY,
                    player_id TEXT NOT NULL,
                    username TEXT,
                    level INTEGER,
                    server INTEGER,
                    alliance_tag TEXT,
                    rank TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    screenshot_url TEXT
                )
            """)
            conn.commit()

    def store_stfc_player(
        self,
        user_id: int,
        player_data: PlayerData,
        screenshot_url: Optional[str] = None,
    ):
        """Store or update a player's STFC data."""
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO stfc_players
                (user_id, player_id, username, level, server, alliance_tag, rank, screenshot_url, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                user_id,
                player_data.player_id,
                player_data.username,
                player_data.level,
                player_data.server,
                player_data.alliance_tag,
                player_data.rank,
                screenshot_url,
            ))
            conn.commit()

    def get_all_players(self) -> list[tuple]:
        """Get all stored player links for update checks."""
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT user_id, player_id FROM stfc_players"
            )
            return cursor.fetchall()

    def get_player_data(self, user_id: int) -> Optional[tuple]:
        """Get stored player data for a user.
        
        Returns: (username, level, server, alliance_tag, rank, screenshot_url)
        """
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT username, level, server, alliance_tag, rank, screenshot_url FROM stfc_players WHERE user_id = ?",
                (user_id,),
            )
            return cursor.fetchone()


store = Store(DB_PATH)


# ---------------------------------------------------------------------------
# Confirmation View with Accept/Reject Buttons
# ---------------------------------------------------------------------------
class RankConfirmationView(ui.View):
    """View for admin to confirm/reject rank changes."""

    def __init__(self, user_id: int, member_name: str, rank: str, player_name: str, alliance_tag: str):
        super().__init__(timeout=None)  # Persistent until manually dismissed
        self.user_id = user_id
        self.member_name = member_name
        self.rank = rank
        self.player_name = player_name
        self.alliance_tag = alliance_tag
        self.confirmed = None
        self.user_message = None  # Store user's pending message to edit later
        self.log_message = None  # Store log message to edit after confirmation

    @ui.button(label="✅ Accept", style=discord.ButtonStyle.green, custom_id="rank_accept")
    async def accept_button(self, interaction: discord.Interaction, button: ui.Button):
        """Accept the rank promotion."""
        self.confirmed = True
        await interaction.response.defer()
        await self.on_confirmation(interaction.guild)
        # Edit the log message to remove buttons and show confirmation
        if self.log_message:
            try:
                embed = self.log_message.embeds[0] if self.log_message.embeds else None
                if embed:
                    embed.color = discord.Color.green()
                    embed.title = "✅ Rank Confirmation - ACCEPTED"
                    await self.log_message.edit(embed=embed, view=None)
            except Exception as e:
                log.warning(f"[CONFIRM] Could not edit log message: {e}")
        self.stop()

    @ui.button(label="❌ Reject", style=discord.ButtonStyle.red, custom_id="rank_reject")
    async def reject_button(self, interaction: discord.Interaction, button: ui.Button):
        """Reject the rank promotion."""
        self.confirmed = False
        await interaction.response.defer()
        await self.on_confirmation(interaction.guild)
        # Edit the log message to remove buttons and show rejection
        if self.log_message:
            try:
                embed = self.log_message.embeds[0] if self.log_message.embeds else None
                if embed:
                    embed.color = discord.Color.red()
                    embed.title = "❌ Rank Confirmation - REJECTED"
                    await self.log_message.edit(embed=embed, view=None)
            except Exception as e:
                log.warning(f"[CONFIRM] Could not edit log message: {e}")
        self.stop()

    async def on_confirmation(self, guild: discord.Guild):
        """Handle the confirmation result."""
        member = guild.get_member(self.user_id)
        if not member:
            log.warning(f"[CONFIRM] Member {self.user_id} not found for confirmation")
            return

        if self.confirmed:
            log.info(f"[CONFIRM] Admin ACCEPTED rank change for {member.name}: {self.rank}")
            # Assign leadership roles (member role already assigned during verification)
            commodore_role = guild.get_role(COMMODORE_ROLE_ID)
            admiral_role = guild.get_role(ADMIRAL_ROLE_ID)
            
            rank_tier = get_rank_tier(self.rank)
            
            try:
                if rank_tier == "commodore":
                    # Assign commodore role (member role already assigned)
                    if commodore_role:
                        await member.add_roles(commodore_role, reason=f"Confirmed rank: {self.rank}")
                    # Remove admiral if they had it
                    if admiral_role and admiral_role in member.roles:
                        await member.remove_roles(admiral_role, reason="Rank downgrade")
                    log.info(f"[CONFIRM] Assigned commodore role to {member.name}")
                    
                elif rank_tier == "admiral":
                    # Assign admiral role (member role already assigned)
                    if admiral_role:
                        await member.add_roles(admiral_role, reason=f"Confirmed rank: {self.rank}")
                    # Remove commodore if they had it
                    if commodore_role and commodore_role in member.roles:
                        await member.remove_roles(commodore_role, reason="Rank promotion")
                    log.info(f"[CONFIRM] Assigned admiral role to {member.name}")
            except Exception as e:
                log.error(f"[CONFIRM] Error assigning leadership role: {e}")
            
            # Edit the user's message to show confirmation
            if self.user_message:
                try:
                    embed = discord.Embed(
                        title="✅ Verification Successful",
                        description=f"Welcome, **{self.player_name}**! Your rank has been confirmed by admins.",
                        color=discord.Color.green(),
                    )
                    embed.add_field(name="Rank", value=self.rank, inline=True)
                    embed.add_field(name="Alliance", value=f"[{self.alliance_tag}]" if self.alliance_tag != "N/A" else "N/A", inline=True)
                    await self.user_message.edit(embed=embed)
                except Exception as e:
                    log.warning(f"[CONFIRM] Could not edit user message: {e}")
        else:
            log.info(f"[CONFIRM] Admin REJECTED rank change for {member.name}: {self.rank}")
            
            # Edit the user's message to show rejection
            if self.user_message:
                try:
                    embed = discord.Embed(
                        title="❌ Verification Rejected",
                        description=f"Your rank promotion to {self.rank} was rejected by admins.",
                        color=discord.Color.red(),
                    )
                    await self.user_message.edit(embed=embed)
                except Exception as e:
                    log.warning(f"[CONFIRM] Could not edit user message: {e}")


# ---------------------------------------------------------------------------
# Discord Bot
# ---------------------------------------------------------------------------
class STFCRankBot(commands.Bot):
    """STFC Rank Management Bot for Discord."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        """Register commands and start background tasks."""
        await self.tree.sync(guild=discord.Object(GUILD_ID))
        log.info("[SETUP] Commands synced")

        self.update_stfc_ranks.start()
        log.info("[SETUP] Background tasks started")

    async def on_ready(self):
        """Bot ready."""
        log.info(f"[READY] Logged in as {self.user}")

    def _build_nickname(self, alliance_tag: Optional[str], username: str) -> str:
        """Build nickname in format [TAG] username."""
        if alliance_tag:
            return f"[{alliance_tag}] {username}"
        return username

    async def _assign_alliance_role(self, member: discord.Member, alliance_tag: Optional[str]):
        """Optionally assign alliance role based on tag name.
        
        If ENABLE_ALLIANCE_ROLES is true:
        - If user has alliance tag, find and assign role matching the tag
        - If user has no alliance tag, assign "N/A" role if it exists
        Otherwise, do nothing.
        """
        if not ENABLE_ALLIANCE_ROLES:
            return

        # Determine which role to assign
        role_name = alliance_tag if alliance_tag else "N/A"

        try:
            # Find role by name (case-sensitive to match Discord role creation)
            alliance_role = discord.utils.get(member.guild.roles, name=role_name)
            
            if alliance_role:
                await member.add_roles(alliance_role, reason=f"Alliance: {role_name}")
                log.info(f"[ALLIANCE] Assigned alliance role '{role_name}' to {member.name}")
            else:
                log.debug(f"[ALLIANCE] Role '{role_name}' not found for {member.name}")

        except discord.Forbidden:
            log.warning(f"[ALLIANCE] No permission to assign alliance role to {member.name}")
        except Exception as e:
            log.error(f"[ALLIANCE] Error assigning alliance role to {member.name}: {e}")

    async def _assign_ranks(
        self,
        member: discord.Member,
        player_data: PlayerData,
        request_confirmation: bool = False,
    ) -> Optional[RankConfirmationView]:
        """
        Assign roles based on rank.

        For initial verification: immediately assign base role, request confirmation for commodore/admiral.
        For updates: request confirmation for ANY rank change.

        Returns the view if confirmation is needed, otherwise None.
        """
        rank_tier = get_rank_tier(player_data.rank)
        
        # Get all rank-related roles
        member_role = member.guild.get_role(MEMBER_ROLE_ID)
        commodore_role = member.guild.get_role(COMMODORE_ROLE_ID)
        admiral_role = member.guild.get_role(ADMIRAL_ROLE_ID)

        if not member_role:
            log.error(f"[RANK] Member role {MEMBER_ROLE_ID} not found")
            return None

        try:
            # Always assign base member role and alliance role immediately
            await member.add_roles(member_role, reason=f"Rank: {player_data.rank}")
            # Assign alliance role if enabled
            await self._assign_alliance_role(member, player_data.alliance_tag)
            
            if rank_tier == "base":
                # Base ranks: remove leadership roles if they had them
                if commodore_role and commodore_role in member.roles:
                    await member.remove_roles(commodore_role, reason="Rank downgrade")
                if admiral_role and admiral_role in member.roles:
                    await member.remove_roles(admiral_role, reason="Rank downgrade")
                log.info(f"[RANK] Assigned base role to {member.name} (rank: {player_data.rank})")

            elif rank_tier == "commodore":
                # Commodore/Admiral always need confirmation before assigning leadership role
                # Base member role and alliance role already assigned above
                return RankConfirmationView(
                    member.id,
                    member.name,
                    player_data.rank,
                    player_data.username,
                    player_data.alliance_tag or "N/A",
                )

            elif rank_tier == "admiral":
                # Same as commodore - always request confirmation for the admiral role
                # Base member role and alliance role already assigned above
                return RankConfirmationView(
                    member.id,
                    member.name,
                    player_data.rank,
                    player_data.username,
                    player_data.alliance_tag or "N/A",
                )

        except discord.Forbidden:
            log.error(f"[RANK] No permission to assign roles to {member.name}")
            return None
        except Exception as e:
            log.error(f"[RANK] Error assigning roles to {member.name}: {e}")
            return None

        return None

    async def post_to_log_channel(self, embed: discord.Embed = None, file: discord.File = None, view: ui.View = None):
        """Post an embed to the log channel. Returns the sent message or None."""
        if not LOG_CHANNEL_ID:
            return None

        guild = self.get_guild(GUILD_ID)
        if not guild:
            return None

        log_ch = guild.get_channel(LOG_CHANNEL_ID)
        if not log_ch:
            log.warning(f"[LOG] Log channel {LOG_CHANNEL_ID} not found")
            return None

        try:
            message = await log_ch.send(embed=embed, file=file, view=view)
            return message
        except Exception as e:
            log.warning(f"[LOG] Could not send to log channel: {e}")
            return None

    @tasks.loop(hours=1)
    async def update_stfc_ranks(self):
        """Periodically check for rank changes and request admin confirmation."""
        guild = self.get_guild(GUILD_ID)
        if not guild:
            log.warning("[UPDATE] Guild not found")
            return

        # Only run every UPDATE_CHECK_HOURS hours
        await self._update_stfc_ranks_impl(guild)

    async def _update_stfc_ranks_impl(self, guild: discord.Guild):
        """Implementation of rank update checking."""
        log.info("[UPDATE] Starting periodic rank check")

        players = store.get_all_players()
        log.info(f"[UPDATE] Found {len(players)} players to check")

        for user_id, player_id in players:
            member = guild.get_member(user_id)
            if not member:
                log.debug(f"[UPDATE] Member {user_id} no longer in guild")
                continue

            try:
                player_data = STFCProScraper.fetch_player_data(player_id)
                if not player_data:
                    log.warning(f"[UPDATE] Could not fetch data for player {player_id}")
                    continue

                old_data = store.get_player_data(user_id)
                if not old_data:
                    continue

                old_rank = old_data[4]  # rank is 5th column
                new_rank = player_data.rank

                # Check if rank changed
                if old_rank != new_rank:
                    log.info(f"[UPDATE] Rank change detected for {member.name}: {old_rank} → {new_rank}")

                    # Update nickname in case it changed
                    new_nick = self._build_nickname(player_data.alliance_tag, player_data.username)
                    if member.nick != new_nick:
                        try:
                            await member.edit(nick=new_nick)
                        except discord.Forbidden:
                            log.warning(f"[UPDATE] Could not update nickname for {member.name}")

                    # Request confirmation for ANY rank change
                    confirmation_view = await self._assign_ranks(member, player_data, request_confirmation=True)

                    # Update database
                    store.store_stfc_player(user_id, player_data, old_data[5])  # screenshot_url is 6th column

                    # Post confirmation request if needed
                    if confirmation_view:
                        admin_ping = f"<@&{ADMIN_ROLE_ID}>" if ADMIN_ROLE_ID else "Admins"
                        alliance_display = f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
                        confirm_embed = discord.Embed(
                            title="🔔 Rank Change Detected - Confirmation Required",
                            description=f"{admin_ping}, please confirm this rank change.",
                            color=discord.Color.orange(),
                        )
                        confirm_embed.add_field(name="Player", value=f"{member.mention} ({player_data.username})", inline=False)
                        confirm_embed.add_field(name="Previous Rank", value=old_rank or "N/A", inline=True)
                        confirm_embed.add_field(name="New Rank", value=new_rank or "N/A", inline=True)
                        confirm_embed.add_field(name="Alliance", value=alliance_display, inline=True)
                        await self.post_to_log_channel(embed=confirm_embed, view=confirmation_view)

            except Exception as e:
                log.error(f"[UPDATE] Error checking player {player_id}: {e}")
                continue

    @update_stfc_ranks.before_loop
    async def before_update_stfc_ranks(self):
        """Wait for bot to be ready before starting update loop."""
        await self.wait_until_ready()
        # Adjust loop to run at specified intervals
        current_hours = UPDATE_CHECK_HOURS
        if current_hours > 0:
            self.update_stfc_ranks.change_interval(hours=current_hours)


# ---------------------------------------------------------------------------
# Commands (Registered after bot instantiation)
# ---------------------------------------------------------------------------
def setup_commands(bot: STFCRankBot):
    """Register slash commands with the bot."""

    @bot.tree.command(
        name="verify",
        description="Verify your STFC player account with alliance rank",
        guild=discord.Object(GUILD_ID),
    )
    @app_commands.describe(
        player_url="Your stfc.pro/stfc.wtf/stfc.live player URL or player ID",
        screenshot="Screenshot of your player profile (for verification logging)"
    )
    async def verify_command(
        interaction: discord.Interaction,
        player_url: str,
        screenshot: discord.Attachment,
    ):
        """Verify STFC player account."""
        await interaction.response.defer(thinking=True)

        # Extract player ID from URL or use directly
        player_id = STFCProScraper.extract_player_id_from_url(player_url)
        if not player_id:
            await interaction.followup.send("❌ Invalid player URL or ID format.")
            return

        # Fetch player data
        player_data = STFCProScraper.fetch_player_data(player_id)
        if not player_data:
            await interaction.followup.send("❌ Could not fetch player data. Check the URL/ID and try again.")
            return

        # Verify server matches
        if player_data.server != STFC_SERVER_ID:
            embed = discord.Embed(
                title="❌ Wrong Server",
                description=f"Your player is on server **{player_data.server}** but this server is for **{STFC_SERVER_ID}**.",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
            return

        # Get member
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.followup.send("❌ Could not get your member profile.")
            return

        # Update nickname
        new_nick = bot._build_nickname(player_data.alliance_tag, player_data.username)
        try:
            await member.edit(nick=new_nick, reason="STFC Verification")
            log.info(f"[VERIFY] Updated nickname for {member.name}: {new_nick}")
        except discord.Forbidden:
            log.warning(f"[VERIFY] Could not update nickname for {member.name}")

        # Download screenshot
        screenshot_url = screenshot.url
        try:
            await screenshot.save(f"screenshots/{member.id}_{player_id}.png")
            log.info(f"[VERIFY] Saved screenshot for {member.name}")
        except Exception as e:
            log.warning(f"[VERIFY] Could not save screenshot: {e}")

        # Store player data
        store.store_stfc_player(member.id, player_data, screenshot_url)

        # Assign ranks (base role immediate, higher ranks need confirmation)
        confirmation_view = await bot._assign_ranks(member, player_data, request_confirmation=False)

        # Show different message based on whether confirmation is needed
        if confirmation_view:
            # Leadership rank - send pending message
            embed = discord.Embed(
                title="⏳ Verification Pending",
                description=f"Welcome, **{player_data.username}**! Your rank is being reviewed by admins.",
                color=discord.Color.orange(),
            )
            alliance_display = f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
            embed.add_field(name="Alliance", value=alliance_display, inline=True)
            embed.add_field(name="Rank", value=player_data.rank or "N/A", inline=True)
            embed.add_field(name="Level", value=str(player_data.level), inline=True)
            embed.add_field(name="Server", value=str(player_data.server), inline=True)
            embed.add_field(name="Status", value="⏳ Awaiting admin confirmation...", inline=False)
            user_message = await interaction.followup.send(embed=embed)
            # Store message reference so we can edit it later
            confirmation_view.user_message = user_message
        else:
            # Base rank - send success message immediately
            embed = discord.Embed(
                title="✅ Verification Successful",
                description=f"Welcome, **{player_data.username}**!",
                color=discord.Color.green(),
            )
            alliance_display = f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
            embed.add_field(name="Alliance", value=alliance_display, inline=True)
            embed.add_field(name="Rank", value=player_data.rank or "N/A", inline=True)
            embed.add_field(name="Level", value=str(player_data.level), inline=True)
            embed.add_field(name="Server", value=str(player_data.server), inline=True)
            await interaction.followup.send(embed=embed)

        # Log verification with screenshot
        log_embed = discord.Embed(
            title="📋 Player Verified",
            description=f"{member.mention} has verified as **{player_data.username}**",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        alliance_display = f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
        log_embed.add_field(name="Alliance", value=alliance_display, inline=True)
        log_embed.add_field(name="Rank", value=player_data.rank or "N/A", inline=True)
        log_embed.add_field(name="Server", value=str(player_data.server), inline=True)
        log_embed.set_image(url=screenshot_url)
        await bot.post_to_log_channel(embed=log_embed)

        # If rank requires confirmation, post confirmation request
        if confirmation_view:
            admin_ping = f"<@&{ADMIN_ROLE_ID}>" if ADMIN_ROLE_ID else "Admins"
            confirm_embed = discord.Embed(
                title="🔔 Rank Confirmation Required",
                description=f"{admin_ping}, please confirm this rank promotion.",
                color=discord.Color.orange(),
            )
            confirm_embed.add_field(name="Player", value=f"{member.mention} ({player_data.username})", inline=False)
            confirm_embed.add_field(name="Rank", value=player_data.rank, inline=True)
            alliance_display = f"[{player_data.alliance_tag}]" if player_data.alliance_tag else "N/A"
            confirm_embed.add_field(name="Alliance", value=alliance_display, inline=True)
            log_message = await bot.post_to_log_channel(embed=confirm_embed, view=confirmation_view)
            # Store log message reference so we can edit it later
            if log_message:
                confirmation_view.log_message = log_message


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Create screenshots directory if it doesn't exist
    os.makedirs("screenshots", exist_ok=True)

    bot = STFCRankBot()
    setup_commands(bot)
    bot.run(DISCORD_TOKEN)
