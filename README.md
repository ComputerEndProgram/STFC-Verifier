# STFC-Verifier

## What Was Built

I've expanded your rank-fetch scraper into a complete Discord bot for managing alliance ranks in your STFC server. The bot:

✅ Fetches player data including **Premier rank** support (newly added)  
✅ Verifies players are on your specific STFC server  
✅ Sets nicknames to `[TAG] username` format  
✅ Assigns roles based on alliance rank with smart confirmation logic  
✅ Detects daily rank changes and requests admin confirmation  
✅ Stores verification screenshots for record-keeping  

## Files Created/Modified

| File | Purpose |
|------|---------|
| `stfc_scraper.py` | Updated to support Premier rank |
| `bot.py` | Complete Discord bot implementation |
| `requirements.txt` | Python dependencies |
| `.env.example` | Configuration template |
| `README.md` | Updated with bot documentation |

## Setup (5 Steps)

### 1. Copy and Configure Environment
```bash
cd STFC-Verifier
cp .env.example .env
nano .env  # Edit with your values
```

**Required values:**
- `DISCORD_TOKEN` - Get from Discord Developer Portal
- `GUILD_ID` - Right-click your server, "Copy Server ID"
- `STFC_SERVER_ID` - Your STFC server (e.g., 118, 106)
- `MEMBER_ROLE_ID`, `COMMODORE_ROLE_ID`, `ADMIRAL_ROLE_ID`, `ADMIN_ROLE_ID`
- `VERIFY_CHANNEL_ID` - Where users run /verify
- `LOG_CHANNEL_ID` - Where rank confirmations are posted

### 2. Create Discord Roles
Create these roles in your Discord server (exact names matter for Discord):
- Member (or similar for base role)
- Commodore
- Admiral
- Admin (or similar for admins)

Get their IDs by right-clicking → Copy Role ID

### 3. Create Discord Channels
- A #verification channel (where users run /verify)
- A #rank-confirmations channel (where admin confirms ranks)

### 4. Create Discord Bot
1. Go to Discord Developer Portal
2. Create New Application
3. Go to Bot section, click Add Bot
4. Copy the TOKEN to `.env` as `DISCORD_TOKEN`
5. Go to OAuth2 → URL Generator
6. Select scopes: `bot`
7. Select permissions: `Send Messages`, `Manage Nicknames`, `Manage Roles`, `Read Message History`
8. Copy generated URL and use to invite bot to your server

### 5. Run the Bot
```bash
cd ~/rank-fetch
source venv/bin/activate
python3 bot.py
```

## How It Works

### User Verification Flow
1. User runs `/verify` command
2. User provides: STFC player URL/ID (e.g., `https://stfc.pro/players/2659122580`)
3. User uploads screenshot of their player profile
4. Bot verifies they're on the correct STFC server
5. Bot sets their nickname to `[TAG] username` (e.g., `[SITH] DarthHαywire`)
6. **Base ranks (Agent/Operative/Premier)**: Role assigned immediately ✓
7. **Leadership ranks (Commodore/Admiral)**: Admin gets confirmation message in log channel with Accept/Reject buttons

### Daily Update Flow
1. Bot checks all verified players every 24 hours (configurable)
2. If any rank change detected (up or down):
   - Bot posts confirmation request to log channel
   - Admin can Accept (apply new rank) or Reject (keep old rank)
3. User's nickname updates automatically if name changed

## Rank System

| Rank | Tier | Role Assignment | Confirmation Needed |
|------|------|-----------------|-------------------|
| Agent | Base | Immediate | ❌ No |
| Operative | Base | Immediate | ❌ No |
| Premier | Base | Immediate | ❌ No |
| Commodore | Leadership | After Admin Approval | ✅ Yes |
| Admiral | Leadership | After Admin Approval | ✅ Yes |

## Commands

**`/verify <player_url_or_id> <screenshot>`**
- Verify your STFC player account
- `player_url_or_id`: Your stfc.pro/stfc.wtf URL or player ID
- `screenshot`: Screenshot of your player profile (for logging)

Example:
```
/verify https://stfc.pro/players/2659122580 [upload screenshot]
```

## Admin Confirmation Messages

When a rank change (initial verification or daily update) needs confirmation, you'll see:
- **Blue log message** showing player verification with screenshot
- **Orange message** with Accept/Reject buttons for rank confirmation

Click the buttons to approve or deny the rank change.

## Database

Player data is stored in `stfc_players.db`:
- Discord user ID
- STFC player ID and username
- Server ID and level
- Alliance tag and rank
- Screenshot URL

Data is automatically backed up on each verification/update.

## Environment Variables Reference

```
DISCORD_TOKEN=<your_bot_token>
GUILD_ID=<server_id>
STFC_SERVER_ID=<stfc_server_id>
VERIFY_CHANNEL_ID=<verification_channel_id>
LOG_CHANNEL_ID=<log_channel_id>
MEMBER_ROLE_ID=<base_role_id>
COMMODORE_ROLE_ID=<commodore_role_id>
ADMIRAL_ROLE_ID=<admiral_role_id>
ADMIN_ROLE_ID=<admin_role_id>
UPDATE_CHECK_HOURS=24  # Daily updates
DB_PATH=stfc_players.db
DEBUG=0  # Set to 1 for verbose logging
```

## Troubleshooting

**Bot doesn't respond to /verify?**
- Make sure bot has permission to use slash commands
- Check if bot is in the server (with proper permissions)
- Verify `VERIFY_CHANNEL_ID` is set correctly

**Can't update nicknames?**
- Bot role must be ABOVE the roles it manages in Discord role hierarchy
- Give bot "Manage Nicknames" permission

**Confirmation messages not appearing?**
- Check `LOG_CHANNEL_ID` is correct and bot can post there
- Verify `ADMIN_ROLE_ID` is set (or empty to disable pinging)

**Player data not fetching?**
- Verify `STFC_SERVER_ID` matches the player's server
- Make sure player URL/ID is valid
- Check internet connection to stfc.pro

## Support & Customization

The bot is built to be extensible. You can:
- Change update frequency by setting `UPDATE_CHECK_HOURS`
- Add more rank tiers by modifying `RANK_TIERS` in `bot.py`
- Add more confirmation logic in `_assign_ranks()` method
- Customize embed messages and colors

Enjoy your rank management bot! 🚀
