# Enhanced STFC Scraper with Rank Extraction & Discord Bot

## Overview
This project contains an enhanced STFC player data scraper that extracts alliance rank information, and a full Discord bot for managing alliance ranks in your STFC server's Discord community.

### Components

1. **STFC Scraper** (`stfc_scraper.py`): Fetches player data from stfc.pro/stfc.wtf including rank
2. **Rank-Based Discord Bot** (`bot.py`): Discord bot for verification and rank management

## What's Different from Original

### Original Scraper (Veil-Bot)
- ✅ Extracted player data from metadata tags only (title, description)
- ✅ Retrieved: player_id, username, level, alliance_tag, server
- ✅ Did NOT extract player rank (Agent, Operative, Premier, Commodore, Admiral)

### Enhanced Scraper (rank-fetch)
- ✅ All original functionality preserved
- ✅ **NEW: Extracts player rank** from HTML body using regex pattern
- ✅ **NEW: Handles players without alliance tags** (makes alliance_tag optional)
- ✅ Rank field in PlayerData: `Optional[str]` with possible values: `Agent`, `Operative`, `Premier`, `Commodore`, `Admiral`

## Key Changes

### 1. PlayerData Dataclass
```python
# Before: alliance_tag required
player_id: str
username: str
level: int
alliance_tag: str  # Always required
server: int

# After: alliance_tag optional, rank added
player_id: str
username: str
level: int
server: int
alliance_tag: Optional[str] = None  # Optional (players can have no alliance)
rank: Optional[str] = None           # NEW: Player rank
```

### 2. Rank Extraction
Added regex pattern to extract rank from HTML body:
```python
rank_match = re.search(r'>(Agent|Operative|Premier|Commodore|Admiral)</span>', response.text)
rank = rank_match.group(1) if rank_match else None
```

### 3. Alliance Tag Handling
Updated to gracefully handle players without an alliance:
- First tries: `"of [ALLIANCE], server X"` pattern
- Falls back to: `", server X"` pattern (no alliance)
- Returns `alliance_tag = None` if not present

## Usage

```python
from stfc_scraper import STFCProScraper

# Fetch player data
result = STFCProScraper.fetch_player_data("2659122580")

# Result includes rank
print(result)
# Output: PlayerData(id=2659122580, name=DarthHαywire, level=77, server=118, alliance=[SITH], rank=Commodore)
```

## Test Cases (Verified ✅)

### Player with Alliance
- ID: `2659122580` (DarthHαywire)
- Result: `rank=Commodore`, `alliance=[SITH]`

### Player without Alliance
- ID: `1689521808` (CmdrRetiredByeBye)
- Result: `rank=Agent`, `alliance=None`

## Environment

- Python 3.x
- Virtual environment: `venv/` (pre-configured)
- Dependencies: `requests`, `beautifulsoup4`, `discord.py`, `python-dotenv`

## Setup

```bash
cd /home/ubuntu/rank-fetch
source venv/bin/activate
pip install -r requirements.txt
```

---

## STFC Rank-Based Discord Bot

### Features

- **Player Verification**: Users submit their STFC player URL/ID with a screenshot
- **Rank Management**: Automatically assigns Discord roles based on alliance rank:
  - **Agent/Operative/Premier** → Base role (assigned immediately)
  - **Commodore** → Commodore role (requires admin confirmation)
  - **Admiral** → Admiral role (requires admin confirmation)
- **Nickname Management**: Sets user nickname to `[TAG] username` format
- **Server Validation**: Verifies player is on the correct STFC server
- **Rank Change Detection**: Daily updates detect rank changes and request admin confirmation for any change (promotion or demotion)
- **Admin Confirmation UI**: Interactive buttons for admins to accept/reject rank changes
- **Screenshot Logging**: Stores verification screenshots in log channel for record-keeping

### Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Fill in the required values:
   - `DISCORD_TOKEN`: Your Discord bot token
   - `GUILD_ID`: Your Discord server ID
   - `STFC_SERVER_ID`: The STFC server ID to verify against (e.g., 118)
   - Role IDs: `MEMBER_ROLE_ID`, `COMMODORE_ROLE_ID`, `ADMIRAL_ROLE_ID`, `ADMIN_ROLE_ID`
   - Channel IDs: `VERIFY_CHANNEL_ID`, `LOG_CHANNEL_ID`

### Running the Bot

```bash
cd /home/ubuntu/rank-fetch
source venv/bin/activate
python3 bot.py
```

### Discord Commands

- **/verify** - Verify your STFC player account
  - Requires: Player URL/ID (e.g., `https://stfc.pro/players/2659122580`)
  - Requires: Screenshot of your player profile
  - Returns: Confirmation of verification and nickname update

### Workflow

#### Initial Verification
1. User runs `/verify` with their player URL and screenshot
2. Bot fetches data and verifies server ID matches
3. Nickname is set to `[TAG] username`
4. Base role is assigned immediately (for Agent/Operative/Premier)
5. For Commodore/Admiral, bot posts confirmation request to log channel
6. Admin accepts/rejects via buttons

#### Daily Rank Updates
1. Bot checks all verified players every 24 hours (configurable)
2. If rank changes detected, bot posts confirmation request
3. ANY rank change (promotion or demotion) requires confirmation
4. Admin accepts/rejects, roles are updated accordingly

### Supported Ranks

- **Agent** → Base tier
- **Operative** → Base tier
- **Premier** → Base tier
- **Commodore** → Leadership tier (requires confirmation)
- **Admiral** → Leadership tier (requires confirmation)

### Database

Player data is stored in SQLite database (`stfc_players.db` by default):
- Discord user ID
- STFC player ID and username
- Server ID, level, alliance tag, rank
- Screenshot URL for verification record
