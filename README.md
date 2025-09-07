# PoloSeek
Sharing is caring

Those who know

## Setup

### 1. Discord Bot Setup
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Copy the bot token
5. Enable the following bot permissions:
   - Send Messages
   - Embed Links
   - Read Message History
   - Use Slash Commands
6. In the OAuth2 section, select the "bot" scope. A URL will be generated at the bottom to add the bot.

Optionally,
- Go to the "Installation" section and set the Install Link dropdown to "None"
- Go to the "Bot" section and toggle off "Public Bot"

### 2. Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment file
cp .env.example .env
# Edit .env with your values
```

### 3. Configuration
Edit your `.env` file with the following values:
- `DISCORD_TOKEN`: Your bot token from Discord Developer Portal
- `DISCORD_OWNER_ID`: Your Discord user ID (enable Developer Mode in Discord, right-click your profile)
- `DISCORD_CHANNEL_ID`: Channel where bot responses should be sent
- `DEFAULT_OWNER_ID`: User ID to assign pass to when reservations expire (usually same as OWNER_ID)

### 4. Database Setup
The bot automatically creates the SQLite database (`poloseek.db`) with the following schema:

**parking_pass table:**
- `current_owner_id`: Discord user ID (19-digit integer)
- `last_updated`: Timestamp of last update

**reservations table:**
- `user_id`: Discord user ID
- `start_time`: Reservation start timestamp
- `end_time`: Reservation end timestamp  
- `active_status`: Boolean indicating if reservation is active
- `approved`: Boolean indicating if reservation has been approved

**users table:**
- `user_id`: Discord user ID
- `parking_memo`: String description (e.g., car details)

### 5. Chrome Setup
Ensure you are authenticated through NetID in the Default Chrome profile.

### 6. Running the Bot
```bash
python poloseek.py
```

## Slash Commands

### `/status`
Shows current parking pass owner with last updated timestamp

### `/refresh`
**Owner only** - Triggers web scraper to update pass data (currently placeholder)

### `/request <start_time> <end_time>`
Request a parking pass reservation
- Checks for time conflicts
- Creates reservation with 'pending' status
- Notifies current pass owner
- Prevents overlapping reservations

**Supported time formats:**
- `YYYY-MM-DD HH:MM`
- `MM/DD/YYYY HH:MM`
- `MM/DD HH:MM`
- `HH:MM` or `H:MM AM/PM`

**Examples:**
- `/request 2024-03-15 09:00 2024-03-15 17:00`
- `/request 3/15 9:00 AM 3/15 5:00 PM`

### `/reservations`
Lists all active and pending reservations with status indicators:
- 🟢 **ACTIVE** (currently happening)
- ✅ **APPROVED** (future reservation that's been approved)
- 🟡 **PENDING** (future reservation awaiting approval)
- 🔴 **EXPIRED** (past end time)

### `/give <user>`
**Owner only** - Assigns parking pass to specified user immediately (does not affect reservations)

### `/approve <user>`
**Owner only** - Approves the next pending reservation for a specific user
- Marks the reservation as approved
- Transfers pass immediately if no active reservation conflicts
- Waits for current reservation to end before transferring if needed
- Automatically transfers at scheduled start time
- Clears other pending reservations for the approved user
- Sends notification to approved user

## Bot Status
The bot's status automatically updates to show:
- Current pass owner's display name
- Last updated timestamp in human-readable CDT format

## Automatic Features

### Smart Reservation Management
- **Immediate Transfer**: Approved reservations transfer immediately if no conflicts
- **Queued Transfer**: Waits for current reservation to end before transferring to approved user
- **Scheduled Transfer**: Automatically transfers at approved reservation start time
- **Conflict Prevention**: Won't interrupt active reservations

### Expired Reservation Handling
- Automatically marks expired reservations as inactive
- Checks for approved reservations ready to start when current reservation expires
- Returns pass to default owner only if no approved reservations are waiting
- Sends notifications to channel for all transfers

### Time Zone Support
- All times displayed in CDT

## Reservation Workflow

1. **Request**: User creates reservation with `/request` (status: 🟡 PENDING)
2. **Approval**: Owner approves with `/approve` (status: ✅ APPROVED)
3. **Transfer**: Pass automatically transfers at appropriate time
4. **Active**: Reservation becomes active (status: 🟢 ACTIVE)
5. **Expiry**: Pass returns to next approved user or default owner

## Adding User Car Information
To add parking memos (car information) for users, manually insert into the database:

```sql
INSERT INTO users (user_id, parking_memo) VALUES (1234567890123456789, 'nathan');
```

This information will be displayed in status commands to help identify vehicles.

## Notes
- SQLite database file will be created in the same directory as the bot script
- All timestamps are stored in ISO format and converted to CDT for display
- The `/give` command provides immediate transfer
