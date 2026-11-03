# Telegram Storage Bot

A private Telegram file-index bot using a Telegram private channel for file storage and SQLite for metadata.

## Features
- Upload documents, photos, video, audio, animation and voice by sending to the bot
- /files — last 10 files
- /search keyword — search by filename
- /get ID — copy a stored file back to your chat
- /delete ID — delete a channel message and index entry (subject to Telegram API limitations)
- /stats — file count and total reported size
- /id — show your Telegram user ID

## Setup
1. Create a bot using @BotFather and keep its token secret.
2. Create a **private Telegram channel** and add the bot as an admin with **Post Messages** and **Delete Messages** permissions.
3. Obtain the numeric channel ID (typically begins with -100).
4. Set BOT_TOKEN, CHANNEL_ID and ALLOWED_USER_IDS in Coolify environment variables, **not in Git**.
5. Deploy this repository as a **Docker Compose** resource using compose.yaml. No domain or public port is required; the bot uses long polling.
6. Send /start to the bot and upload a small test file.

## Security and operations
- Only IDs in ALLOWED_USER_IDS may upload, list, search, retrieve or delete files.
- /id responds in private chats to help users identify their Telegram ID.
- The SQLite database is stored in the named volume telegram_storage_data. **Back up this volume** before redeploying or migrating.
- Do not commit .env, bot tokens, real user IDs, or channel identifiers to this public repository.
- Telegram is not a guaranteed permanent backup. Keep another copy of important files.
- Standard Telegram cloud Bot API has file-size limits (commonly 50 MB for uploads). Larger files require a different design.
- Run only one instance of the bot for polling.
