# Telegram Storage Bot

Lightweight Telegram Private Channel storage bot with SQLite metadata, Python 3.12, aiogram 3.22 and Docker Compose. Suitable for Coolify or small EC2 instances. **No public HTTP port required** (long polling).

## Features
- Send a document, photo, video, audio, animation or voice note to store it in the configured private channel; file type is classified automatically.
- Telegram media groups/albums are supported as **multiple individually indexed files** (one confirmation per item). This does not provide an atomic multi-file transaction.
- Create virtual folders using `/mkdir`, list them using `/folders`, move existing files using `/move`.
- Search by filename, file type, size in MiB, UTC upload date and virtual folder.
- Reply keyboard menu plus inline buttons for the newest file/search result (get, move guidance, delete with confirmation).
- Select up to 20 files by ID and batch-move or batch-delete them.
- No downloads to VPS are needed: the bot uses Telegram `copyMessage` to transfer media into/out of the private channel.

## Commands

| Command | Example | Description |
|---|---|---|
| `/start` | `/start` | Show menu |
| `/help` | `/help` | Usage |
| `/id` | `/id` | Show Telegram ID |
| `/files` | `/files` | 10 newest files |
| `/folders` | `/folders` | List folders |
| `/mkdir` | `/mkdir Work` | Create folder |
| `/move` | `/move 12 Work` | Move file; use `root` for no folder |
| `/search` | `/search report` | Filename search |
| `/search` | `/search name=report type=document min=1 max=50 after=2026-01-01 before=2026-12-31 folder=Work` | Filtered search |
| `/get` | `/get 12` | Retrieve file |
| `/delete` | `/delete 12` | Delete file and channel message |
| `/batch` | `/batch 1,2,3` | Show selected files (max 20) |
| `/batchmove` | `/batchmove 1,2,3 Work` | Move selected files |
| `/batchdelete` | `/batchdelete 1,2,3` | **Immediately** delete selected files; irreversible |
| `/stats` | `/stats` | File count and reported sizes |

**Search notes:** types are `document`, `photo`, `video`, `audio`, `animation`, `voice`. PDF is categorized as `document`; search for `name=.pdf type=document`. Sizes use MiB. Dates use UTC and inclusive `before` date. Folder names containing spaces can be quoted in search, e.g. `folder="Client Work"`.

## Coolify deployment

1. Create a Telegram bot using [@BotFather](https://t.me/BotFather); keep token secret.
2. Create a private Telegram channel. Add the bot as administrator with **Post Messages** and **Delete Messages** permissions.
3. Obtain numeric channel ID (typically begins with `-100`).
4. In Coolify, add this GitHub repository as a Docker Compose resource with `compose.yaml`.
5. Set **secret** environment variables:
   - `BOT_TOKEN` = BotFather token
   - `CHANNEL_ID` = numeric private channel ID
   - `ALLOWED_USER_IDS` = comma-separated Telegram IDs permitted to use the bot
6. Deploy one replica. No domain, reverse proxy or public port required.
7. Send `/start` in a private chat with the bot.

## EC2 / Docker Compose

Install Docker Engine and Compose plugin on an Ubuntu EC2 instance, then:

```bash
git clone https://github.com/jiir4pong/Telegram-storage-bot.git
cd Telegram-storage-bot
cp .env.example .env
chmod 600 .env
# Edit .env locally and fill the real values (never commit this file)
docker compose up -d --build
docker compose logs -f --tail=100
```

## Database migration and backups

The existing `/data/files.sqlite3` schema is preserved. On startup, the bot adds a nullable `folder_id` column to the existing `files` table and creates a `folders` table and indexes. Existing files stay in the virtual root folder; file IDs and channel message IDs are retained.

**Before deploying the new version, back up the existing SQLite database and Docker volume.** Keep the same volume mapping in Coolify; do not delete/recreate the volume. SQLite uses WAL, so take a consistent backup with SQLite's backup API, not a live copy of only the `.sqlite3` file. For example, in a stopped container, archive the full volume; or while running, use `sqlite3.Connection.backup()`.

## Security and limitations

- All file commands, menus and callbacks require an allowed user ID in a private chat. `/id` reveals only the sender's own ID.
- The bot is deployed as a non-root user with Linux capabilities dropped and no published ports.
- SQL queries use bound parameters; dynamically built IN clauses contain only validated numeric IDs.
- Bot token must be stored only in secret environment variables; **never commit a real `.env`**.
- This is a public repository: do not include credentials, user IDs or private channel IDs.
- Telegram's standard cloud Bot API has size limits; test large files before relying on them.
- Deleting channel messages is subject to Telegram API restrictions. If Telegram deletion fails, the database record is retained.
- `/batchdelete` deletes immediately without confirmation; verify IDs first with `/batch`.
- A Telegram private channel is not a guaranteed permanent backup. Keep independent copies of important files.
- The application assumes **one polling instance** and a single SQLite writer process. Do not scale replicas.
- Folder management is virtual: moving a file updates SQLite metadata, not the Telegram message.
