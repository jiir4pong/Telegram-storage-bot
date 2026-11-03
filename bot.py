import asyncio
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = int(os.environ["CHANNEL_ID"])
OWNERS = {int(x.strip()) for x in os.environ["ALLOWED_USER_IDS"].split(",") if x.strip()}
if not OWNERS:
    raise RuntimeError("ALLOWED_USER_IDS is required")

DB = Path("/data/files.sqlite3")
DB.parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(DB, isolation_level=None, timeout=30)
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA busy_timeout=30000")
con.execute("""CREATE TABLE IF NOT EXISTS files (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
 size INTEGER NOT NULL, message_id INTEGER NOT NULL, uploader INTEGER NOT NULL,
 created INTEGER NOT NULL)""")
con.execute("""CREATE TABLE IF NOT EXISTS folders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE)""")
columns = {row[1] for row in con.execute("PRAGMA table_info(files)")}
if "folder_id" not in columns:
    con.execute("ALTER TABLE files ADD COLUMN folder_id INTEGER")
con.execute("CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_id)")
con.execute("CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind)")
con.execute("CREATE INDEX IF NOT EXISTS idx_files_created ON files(created)")
dp = Dispatcher()
MENU = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📁 Folders"), KeyboardButton(text="📄 Files")],
    [KeyboardButton(text="🔎 Search"), KeyboardButton(text="📊 Stats")],
    [KeyboardButton(text="❔ Help")]
], resize_keyboard=True)
KINDS = {"document", "photo", "video", "audio", "animation", "voice"}
MAX_RESULTS = 20
MAX_BATCH = 20
album_locks = {}

def allowed(m):
    return m.chat.type == "private" and bool(m.from_user and m.from_user.id in OWNERS)

async def deny(m):
    if m.chat.type == "private":
        await m.answer("Access denied.")

def args(m):
    return (m.text or "").partition(" ")[2].strip()

def kind_info(m):
    if m.document:
        return m.document.file_name or "document", "document", m.document.file_size or 0
    if m.video:
        return m.video.file_name or "video.mp4", "video", m.video.file_size or 0
    if m.audio:
        return m.audio.file_name or "audio", "audio", m.audio.file_size or 0
    if m.photo:
        return "photo.jpg", "photo", m.photo[-1].file_size or 0
    if m.animation:
        return m.animation.file_name or "animation.gif", "animation", m.animation.file_size or 0
    if m.voice:
        return "voice.ogg", "voice", m.voice.file_size or 0
    return None

def folder_by_name(name):
    row = con.execute("SELECT id FROM folders WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    return row[0] if row else None

def clean_name(name):
    name = name.strip()
    if not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError("Folder name must contain 1–80 printable characters.")
    return name

def file_keyboard(fid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ Get", callback_data=f"g:{fid}"),
         InlineKeyboardButton(text="📁 Move", callback_data=f"m:{fid}")],
        [InlineKeyboardButton(text="🗑 Delete", callback_data=f"d:{fid}")]
    ])

def listing(rows):
    return "\n".join(f"#{r[0]} {r[1][:55]} [{r[2]}] {r[3]/1048576:.1f} MB" for r in rows) or "No files found."

def parse_date(value):
    try:
        return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        raise ValueError("Date must use YYYY-MM-DD.")

def query_files(filters):
    sql = "SELECT id,name,kind,size FROM files WHERE 1=1"
    values = []
    for key, val in filters.items():
        if key == "name":
            sql += " AND name LIKE ? ESCAPE '\\'"
            values.append("%" + val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        elif key == "type":
            if val not in KINDS:
                raise ValueError("Invalid type. Use document/photo/video/audio/animation/voice.")
            sql += " AND kind=?"
            values.append(val)
        elif key == "min":
            sql += " AND size>=?"
            values.append(int(float(val) * 1048576))
        elif key == "max":
            sql += " AND size<=?"
            values.append(int(float(val) * 1048576))
        elif key == "after":
            sql += " AND created>=?"
            values.append(parse_date(val))
        elif key == "before":
            sql += " AND created<?"
            values.append(parse_date(val) + 86400)
        elif key == "folder":
            if val.lower() == "root":
                sql += " AND folder_id IS NULL"
            else:
                folder_id = folder_by_name(val)
                if folder_id is None:
                    return []
                sql += " AND folder_id=?"
                values.append(folder_id)
        else:
            raise ValueError(f"Unknown filter: {key}")
    return con.execute(sql + " ORDER BY id DESC LIMIT ?", (*values, MAX_RESULTS)).fetchall()

@dp.message(CommandStart())
async def start(m: Message):
    if not allowed(m):
        return await deny(m)
    await m.answer("Telegram Storage Bot ready. Send files directly. Use menu buttons or /help.", reply_markup=MENU)

@dp.message(Command("help"))
@dp.message(F.text == "❔ Help")
async def help_command(m: Message):
    if not allowed(m):
        return await deny(m)
    await m.answer(
        "/files — last 10 files\n/folders — list folders\n/mkdir Work — create folder\n"
        "/move 12 Work — move file; use root to unfile\n"
        "/search name=report type=pdf — example below\n"
        "/search name=report type=document min=1 max=50 after=2026-01-01 before=2026-12-31 folder=Work\n"
        "/batch 1,2,3 — select up to 20 files for actions\n"
        "/batchmove 1,2,3 Work — move multiple files\n"
        "/batchdelete 1,2,3 — delete multiple files (irreversible)\n"
        "/get 12 — retrieve\n/delete 12 — delete\n/stats — statistics\n/id — your ID\n"
        "Send a Telegram album to upload several files in one go. File categories are automatic."
    )

@dp.message(Command("id"))
async def user_id(m: Message):
    if m.chat.type == "private" and m.from_user:
        await m.answer(f"Your Telegram ID: {m.from_user.id}")

@dp.message(Command("folders"))
@dp.message(F.text == "📁 Folders")
async def folders(m: Message):
    if not allowed(m):
        return await deny(m)
    rows = con.execute("""SELECT f.id,f.name,COUNT(x.id) FROM folders f
        LEFT JOIN files x ON x.folder_id=f.id GROUP BY f.id ORDER BY f.name LIMIT 100""").fetchall()
    await m.answer("Folders:\n" + ("\n".join(f"{name} ({count} files)" for _, name, count in rows) or "None. Use /mkdir FolderName"))

@dp.message(Command("mkdir"))
async def mkdir(m: Message):
    if not allowed(m):
        return await deny(m)
    try:
        name = clean_name(args(m))
        con.execute("INSERT INTO folders(name) VALUES(?)", (name,))
    except sqlite3.IntegrityError:
        return await m.answer("Folder already exists.")
    except ValueError as e:
        return await m.answer(str(e))
    await m.answer(f"Folder created: {name}")

@dp.message(Command("move"))
async def move(m: Message):
    if not allowed(m):
        return await deny(m)
    parts = args(m).split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return await m.answer("Usage: /move 12 Work")
    folder = None if parts[1].lower() == "root" else folder_by_name(parts[1])
    if parts[1].lower() != "root" and folder is None:
        return await m.answer("Folder not found. Use /mkdir first.")
    result = con.execute("UPDATE files SET folder_id=? WHERE id=?", (folder, int(parts[0])))
    await m.answer("Moved." if result.rowcount else "File not found.")

@dp.message(Command("files"))
@dp.message(F.text == "📄 Files")
async def files(m: Message):
    if not allowed(m):
        return await deny(m)
    rows = con.execute("SELECT id,name,kind,size FROM files ORDER BY id DESC LIMIT 10").fetchall()
    await m.answer(listing(rows))
    if rows:
        await m.answer("Actions for newest file:", reply_markup=file_keyboard(rows[0][0]))

@dp.message(Command("search"))
@dp.message(F.text == "🔎 Search")
async def search(m: Message):
    if not allowed(m):
        return await deny(m)
    text = args(m)
    if not text:
        return await m.answer("Use /search report or /search name=report type=video min=2 after=2026-01-01")
    try:
        if "=" not in text:
            filters = {"name": text}
        else:
            import shlex
            pairs = shlex.split(text)
            filters = dict(p.split("=", 1) for p in pairs)
            if not filters or len(filters) != len(pairs):
                raise ValueError("Use key=value filters.")
            if any(k in filters for k in ("min", "max")):
                for key in ("min", "max"):
                    if key in filters and (not 0 <= float(filters[key]) <= 1048576):
                        raise ValueError("Size must be 0–1048576 MB.")
        rows = query_files(filters)
    except (ValueError, OverflowError) as e:
        return await m.answer(f"Invalid search: {e}")
    await m.answer(listing(rows))
    if rows:
        await m.answer("Actions for newest result:", reply_markup=file_keyboard(rows[0][0]))

@dp.message(Command("stats"))
@dp.message(F.text == "📊 Stats")
async def stats(m: Message):
    if not allowed(m):
        return await deny(m)
    count, total = con.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM files").fetchone()
    await m.answer(f"{count} files, {total/1073741824:.3f} GiB (reported sizes)")

def parse_ids(value):
    values = value.split(",")
    if not 1 <= len(values) <= MAX_BATCH or any(not x.strip().isdigit() for x in values):
        raise ValueError("Supply 1–20 numeric IDs separated by commas.")
    ids = list(dict.fromkeys(int(x.strip()) for x in values))
    return ids

@dp.message(Command("batch"))
async def batch(m: Message):
    if not allowed(m):
        return await deny(m)
    try:
        ids = parse_ids(args(m))
    except ValueError as e:
        return await m.answer(str(e))
    placeholders = ",".join("?" for _ in ids)
    rows = con.execute(f"SELECT id,name,kind,size FROM files WHERE id IN ({placeholders}) ORDER BY id", ids).fetchall()
    await m.answer(listing(rows) + "\nUse /batchmove 1,2 Work or /batchdelete 1,2")

@dp.message(Command("batchmove"))
async def batchmove(m: Message):
    if not allowed(m):
        return await deny(m)
    parts = args(m).split(maxsplit=1)
    if len(parts) != 2:
        return await m.answer("Usage: /batchmove 1,2,3 Work")
    try:
        ids = parse_ids(parts[0])
    except ValueError as e:
        return await m.answer(str(e))
    folder = None if parts[1].lower() == "root" else folder_by_name(parts[1])
    if parts[1].lower() != "root" and folder is None:
        return await m.answer("Folder not found.")
    placeholders = ",".join("?" for _ in ids)
    count = con.execute(f"UPDATE files SET folder_id=? WHERE id IN ({placeholders})", (folder, *ids)).rowcount
    await m.answer(f"Moved {count} files.")

async def send_file(bot, chat, fid):
    row = con.execute("SELECT message_id FROM files WHERE id=?", (fid,)).fetchone()
    if not row:
        return False
    await bot.copy_message(chat_id=chat, from_chat_id=CHANNEL, message_id=row[0])
    return True

async def remove_file(bot, fid):
    row = con.execute("SELECT message_id FROM files WHERE id=?", (fid,)).fetchone()
    if not row:
        return False
    await bot.delete_message(CHANNEL, row[0])
    con.execute("DELETE FROM files WHERE id=?", (fid,))
    return True

@dp.message(Command("get"))
async def get(m: Message, bot: Bot):
    if not allowed(m):
        return await deny(m)
    if not args(m).isdigit():
        return await m.answer("Usage: /get 123")
    try:
        if not await send_file(bot, m.chat.id, int(args(m))):
            await m.answer("File not found.")
    except TelegramAPIError:
        await m.answer("Cannot retrieve. Check original channel message.")

@dp.message(Command("delete"))
async def delete(m: Message, bot: Bot):
    if not allowed(m):
        return await deny(m)
    if not args(m).isdigit():
        return await m.answer("Usage: /delete 123")
    try:
        removed = await remove_file(bot, int(args(m)))
        await m.answer("Deleted." if removed else "File not found.")
    except TelegramAPIError:
        await m.answer("Telegram could not delete channel message. Index unchanged.")

@dp.message(Command("batchdelete"))
async def batchdelete(m: Message, bot: Bot):
    if not allowed(m):
        return await deny(m)
    try:
        ids = parse_ids(args(m))
    except ValueError as e:
        return await m.answer(str(e))
    done, failed = 0, []
    for fid in ids:
        try:
            if await remove_file(bot, fid):
                done += 1
            else:
                failed.append(fid)
        except TelegramAPIError:
            failed.append(fid)
    await m.answer(f"Deleted {done}. Failed/missing: {failed[:20]}")

@dp.callback_query()
async def callbacks(q: CallbackQuery, bot: Bot):
    if not q.from_user or q.from_user.id not in OWNERS or not q.message or q.message.chat.type != "private":
        return await q.answer("Access denied.", show_alert=True)
    data = q.data or ""
    if not re.fullmatch(r"(?:[gmdx]:[0-9]{1,18}|c:0)", data):
        return await q.answer("Unknown action.", show_alert=True)
    action, raw = data.split(":")
    fid = int(raw)
    await q.answer()
    try:
        if action == "g":
            if not await send_file(bot, q.message.chat.id, fid):
                await q.message.answer("File not found.")
        elif action == "d":
            # A second confirmation is required before deleting
            await q.message.answer(f"Delete file #{fid} permanently?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Confirm delete", callback_data=f"x:{fid}"),
                 InlineKeyboardButton(text="Cancel", callback_data="c:0")]]))
        elif action == "x":
            removed = await remove_file(bot, fid)
            await q.message.answer("Deleted." if removed else "File not found.")
        elif action == "c":
            await q.message.answer("Cancelled.")
        elif action == "m":
            await q.message.answer(f"Move file #{fid} with /move {fid} FolderName")
    except TelegramAPIError:
        await q.message.answer("Telegram API action failed.")

@dp.message(F.document | F.photo | F.video | F.audio | F.animation | F.voice)
async def upload(m: Message, bot: Bot):
    if not allowed(m):
        return await deny(m)
    info = kind_info(m)
    if not info:
        return
    name, kind, size = info
    try:
        posted = await bot.copy_message(CHANNEL, m.chat.id, m.message_id)
        cur = con.execute("INSERT INTO files(name,kind,size,message_id,uploader,created) VALUES(?,?,?,?,?,?)",
                          (name, kind, size, posted.message_id, m.from_user.id, int(time.time())))
        # Albums arrive as multiple Telegram updates. Each is stored individually.
        await m.answer(f"Saved #{cur.lastrowid}: {name}")
    except TelegramAPIError:
        logging.exception("Upload failed")
        await m.answer("Upload failed. Check channel permissions and Telegram file-size limits.")

@dp.message()
async def fallback(m: Message):
    if not allowed(m):
        return await deny(m)
    await m.answer("Send a file or use the menu /help.", reply_markup=MENU)

async def main():
    logging.basicConfig(level=logging.INFO)
    async with Bot(TOKEN) as bot:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
