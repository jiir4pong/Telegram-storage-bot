import asyncio, logging, os, sqlite3, time
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.exceptions import TelegramAPIError

TOKEN=os.environ['BOT_TOKEN']
CHANNEL=int(os.environ['CHANNEL_ID'])
OWNERS={int(x.strip()) for x in os.environ['ALLOWED_USER_IDS'].split(',') if x.strip()}
if not OWNERS: raise RuntimeError('ALLOWED_USER_IDS required')
DB=Path('/data/files.sqlite3'); DB.parent.mkdir(parents=True, exist_ok=True)
con=sqlite3.connect(DB, isolation_level=None)
con.execute('PRAGMA journal_mode=WAL')
con.execute('''CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL, message_id INTEGER NOT NULL, uploader INTEGER NOT NULL, created INTEGER NOT NULL)''')
dp=Dispatcher()

def allowed(m): return m.chat.type=='private' and m.from_user and m.from_user.id in OWNERS
async def deny(m):
    if m.chat.type=='private': await m.answer('Access denied.')

def detail(m):
    if m.document: return m.document.file_name or 'document', 'document', m.document.file_size or 0
    if m.video: return m.video.file_name or 'video.mp4', 'video', m.video.file_size or 0
    if m.audio: return m.audio.file_name or 'audio', 'audio', m.audio.file_size or 0
    if m.photo: return 'photo.jpg', 'photo', m.photo[-1].file_size or 0
    if m.animation: return m.animation.file_name or 'animation.gif', 'animation', m.animation.file_size or 0
    if m.voice: return 'voice.ogg', 'voice', m.voice.file_size or 0
    return None

@dp.message(CommandStart())
async def start(m:Message):
    if not allowed(m): return await deny(m)
    await m.answer('Storage Bot ready. Send a file, photo, video, audio or voice.\n/files — recent files\n/search keyword — search\n/get ID — retrieve\n/delete ID — delete\n/stats — totals\n/id — your user ID')

@dp.message(Command('id'))
async def user_id(m:Message):
    if m.chat.type=='private': await m.answer(f'Your Telegram ID: {m.from_user.id}')

@dp.message(Command('files'))
async def files(m:Message):
    if not allowed(m): return await deny(m)
    rows=con.execute('SELECT id,name,size FROM files ORDER BY id DESC LIMIT 10').fetchall()
    await m.answer('\n'.join(f'#{i} {name[:70]} ({size/1048576:.1f} MB)' for i,name,size in rows) or 'No files yet.')

@dp.message(Command('search'))
async def search(m:Message):
    if not allowed(m): return await deny(m)
    q=(m.text or '').partition(' ')[2].strip()
    if not q: return await m.answer('Usage: /search keyword')
    rows=con.execute("SELECT id,name FROM files WHERE name LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 20", ('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%',)).fetchall()
    await m.answer('\n'.join(f'#{i} {name[:90]}' for i,name in rows) or 'No matches.')

@dp.message(Command('stats'))
async def stats(m:Message):
    if not allowed(m): return await deny(m)
    count,total=con.execute('SELECT COUNT(*), COALESCE(SUM(size),0) FROM files').fetchone()
    await m.answer(f'{count} files, {total/1073741824:.3f} GiB (reported file sizes)')

@dp.message(Command('get'))
async def get(m:Message, bot:Bot):
    if not allowed(m): return await deny(m)
    arg=(m.text or '').split()
    if len(arg)!=2 or not arg[1].isdigit(): return await m.answer('Usage: /get 123')
    row=con.execute('SELECT message_id FROM files WHERE id=?',(int(arg[1]),)).fetchone()
    if not row: return await m.answer('File not found.')
    try: await bot.copy_message(chat_id=m.chat.id,from_chat_id=CHANNEL,message_id=row[0],protect_content=False)
    except TelegramAPIError: await m.answer('Could not retrieve file. Check channel permissions and whether the original exists.')

@dp.message(Command('delete'))
async def delete(m:Message, bot:Bot):
    if not allowed(m): return await deny(m)
    arg=(m.text or '').split()
    if len(arg)!=2 or not arg[1].isdigit(): return await m.answer('Usage: /delete 123')
    id=int(arg[1]); row=con.execute('SELECT message_id FROM files WHERE id=?',(id,)).fetchone()
    if not row: return await m.answer('File not found.')
    try: await bot.delete_message(CHANNEL,row[0])
    except TelegramAPIError: return await m.answer('Channel deletion failed; database entry kept. Telegram may limit deletion of older messages.')
    con.execute('DELETE FROM files WHERE id=?',(id,))
    await m.answer('Deleted from channel and index.')

@dp.message(F.document | F.photo | F.video | F.audio | F.animation | F.voice)
async def upload(m:Message,bot:Bot):
    if not allowed(m): return await deny(m)
    name,kind,size=detail(m)
    try:
        posted=await bot.copy_message(CHANNEL,m.chat.id,m.message_id)
        cur=con.execute('INSERT INTO files(name,kind,size,message_id,uploader,created) VALUES(?,?,?,?,?,?)',(name,kind,size,posted.message_id,m.from_user.id,int(time.time())))
        await m.answer(f'Saved #{cur.lastrowid}: {name}')
    except TelegramAPIError:
        logging.exception('Upload failed')
        await m.answer('Upload failed. Check file size and channel admin permissions.')

@dp.message()
async def fallback(m:Message):
    if not allowed(m): return await deny(m)
    await m.answer('Send a file or use /start for commands.')

async def main():
    logging.basicConfig(level=logging.INFO)
    bot=Bot(TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot,allowed_updates=['message'])

if __name__=='__main__': asyncio.run(main())
