import os, asyncio, sqlite3, zipfile, shutil
from flask import Flask
from threading import Thread
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telethon import TelegramClient, errors, events, functions, types
from telethon.sessions import StringSession

# --- Config ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_NAME = 'database.db'
ADMIN_ID = 8373846582 # আপনার আইডি
CREDIT = "「 Prime Xyron 」👨‍💻"

bot = AsyncTeleBot(BOT_TOKEN)
user_states, active_clients, reply_tracking = {}, {}, {}

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Phantom Multi-User System is Live"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- Database Helper ---
def db_query(sql, params=(), fetch=False):
    with sqlite3.connect(DB_NAME, check_same_thread=False) as conn:
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            res = cur.fetchall() if fetch else None
            conn.commit()
            return res
        except Exception: return None

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, api_id INTEGER, api_hash TEXT, 
            string_session TEXT, custom_reply TEXT DEFAULT "I'm currently offline.", 
            is_active INTEGER DEFAULT 0, is_enabled INTEGER DEFAULT 1)''')

# --- Ghost Listener ---
async def start_user_listener(uid, api_id, api_hash, string_session):
    if uid in active_clients:
        try: await active_clients[uid].disconnect()
        except: pass

    client = TelegramClient(StringSession(string_session), int(api_id), api_hash, auto_reconnect=True)
    active_clients[uid] = client
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            db_query('UPDATE users SET is_active=0 WHERE user_id=?', (uid,))
            return

        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            if not event.is_private: return
            sender = await event.get_sender()
            if sender is None or getattr(sender, 'bot', False): return

            row = db_query('SELECT custom_reply, is_enabled FROM users WHERE user_id=?', (uid,), True)
            if not row or row[0][1] == 0: return

            try:
                me = await client.get_me()
                if isinstance(me.status, types.UserStatusOnline): return

                await event.reply(row[0][0])
                
                reply_tracking[uid] = reply_tracking.get(uid, 0) + 1
                current_call = reply_tracking[uid]
                await asyncio.sleep(5)
                if reply_tracking.get(uid) == current_call:
                    await client(functions.account.UpdateStatusRequest(offline=True))
            except: pass

        await client.run_until_disconnected()
    except: pass
    finally: active_clients.pop(uid, None)

# --- Bot Handlers ---

@bot.message_handler(commands=['start'])
async def welcome(m):
    db_query('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (m.from_user.id,))
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⚙️ Settings", "✏️ Set Reply", "📊 Status")
    
    text = (
        "👻 𝙿𝚑𝚊𝚗𝚝𝚘𝚖 𝚁𝚎𝚙𝚕𝚢\n\n"
        "Welcome to your Telegram shadow.\n"
        "Multi-user support active.\n\n"
        f"Powered by {CREDIT}"
    )
    await bot.send_message(m.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "⚙️ Settings")
async def settings(m):
    uid = m.from_user.id
    data = db_query('SELECT string_session, is_enabled FROM users WHERE user_id=?', (uid,), True)
    status = "Connected" if data and data[0][0] else "Not Connected"
    markup = InlineKeyboardMarkup()
    if status == "Connected":
        toggle = "🟢 Bot Enabled" if data[0][1] == 1 else "🔴 Bot Disabled"
        markup.add(InlineKeyboardButton(toggle, callback_data="toggle"))
        markup.add(InlineKeyboardButton("❌ Logout", callback_data="logout"))
    else:
        markup.add(InlineKeyboardButton("➕ Login Account", callback_data="login"))
    await bot.send_message(uid, "⚙️ 𝚂𝚎𝚝𝚝𝚒𝚗𝚐𝚜 𝙿𝚊𝚗𝚎𝚕", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
async def callbacks(c):
    uid = c.from_user.id
    if c.data == "login":
        user_states[uid] = {'step': 'api'}
        await bot.send_message(uid, "🔑 Send API_ID:API_HASH")
    elif c.data == "toggle":
        db_query('UPDATE users SET is_enabled = 1 - is_enabled WHERE user_id=?', (uid,))
        await settings(c.message)
    elif c.data == "logout":
        db_query('UPDATE users SET string_session=NULL, is_active=0 WHERE user_id=?', (uid,))
        if uid in active_clients: await active_clients[uid].disconnect()
        await bot.send_message(uid, "🔴 Logout Done")

@bot.message_handler(func=lambda m: m.from_user.id in user_states)
async def login_flow(m):
    uid = m.from_user.id
    state = user_states[uid].get('step')
    if state == 'api' and ':' in m.text:
        aid, ahash = m.text.split(':', 1)
        user_states[uid].update({'api_id': aid.strip(), 'api_hash': ahash.strip(), 'step': 'phone'})
        await bot.send_message(uid, "📱 Send phone number (+...)")
    elif state == 'phone':
        user_states[uid]['phone'] = m.text.strip()
        client = TelegramClient(StringSession(), int(user_states[uid]['api_id']), user_states[uid]['api_hash'])
        await client.connect()
        try:
            sent = await client.send_code_request(user_states[uid]['phone'])
            user_states[uid].update({'hash': sent.phone_code_hash, 'step': 'otp', 'client': client})
            await bot.send_message(uid, "📩 Enter OTP code.")
        except Exception as e:
            await bot.send_message(uid, f"❌ Error: {e}")
            user_states.pop(uid)
    elif state == 'otp' or state == '2fa':
        try:
            client = user_states[uid]['client']
            if state == 'otp':
                await client.sign_in(user_states[uid]['phone'], m.text.replace(' ',''), phone_code_hash=user_states[uid]['hash'])
            else:
                await client.sign_in(password=m.text.strip())
            
            ss = client.session.save()
            db_query('UPDATE users SET api_id=?, api_hash=?, string_session=?, is_active=1 WHERE user_id=?', 
                      (user_states[uid]['api_id'], user_states[uid]['api_hash'], ss, uid))
            await bot.send_message(uid, "✅ Login Success")
            asyncio.create_task(start_user_listener(uid, user_states[uid]['api_id'], user_states[uid]['api_hash'], ss))
            user_states.pop(uid)
        except errors.SessionPasswordNeededError:
            user_states[uid]['step'] = '2fa'
            await bot.send_message(uid, "🔐 Enter 2FA Password.")
        except Exception as e: await bot.send_message(uid, f"❌ Error: {e}")

@bot.message_handler(func=lambda m: m.text == "✏️ Set Reply")
async def set_rep(m):
    user_states[m.from_user.id] = {'step': 'wait_reply'}
    await bot.send_message(m.chat.id, "✏️ Send custom message.")

@bot.message_handler(func=lambda m: m.text == "📊 Status")
async def status_check(m):
    uid = m.from_user.id
    row = db_query('SELECT custom_reply, is_active, is_enabled FROM users WHERE user_id=?', (uid,), True)
    if row and row[0][1] == 1:
        s = "Active" if row[0][2] == 1 else "Disabled"
        await bot.send_message(uid, f"📊 𝚂𝚝𝚊𝚝𝚞𝚜\nReply: {row[0][0]}\nBot: {s}")
    else:
        await bot.send_message(uid, "❌ Not connected.")

# --- Admin Backup ---
@bot.message_handler(commands=['admin'])
async def admin_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    
    backup_dir = "user_backups"
    if os.path.exists(backup_dir): shutil.rmtree(backup_dir)
    os.makedirs(backup_dir)
    
    users = db_query('SELECT user_id, api_id, api_hash, string_session FROM users WHERE string_session IS NOT NULL', fetch=True)
    
    if not users:
        await bot.send_message(m.chat.id, "❌ No data found in database.")
        return

    for u in users:
        uid, aid, ahash, ss = u
        file_path = f"{backup_dir}/user_{uid}.session"
        with open(file_path, "w") as f:
            f.write(f"User ID: {uid}\nAPI ID: {aid}\nAPI Hash: {ahash}\nSession: {ss}")

    zip_name = "database_backup.zip"
    with zipfile.ZipFile(zip_name, 'w') as z:
        for root, dirs, files in os.walk(backup_dir):
            for file in files:
                z.write(os.path.join(root, file), file)
        z.write(DB_NAME)

    with open(zip_name, 'rb') as f:
        await bot.send_document(m.chat.id, f, caption="📊 Full Multi-User Database Backup")
    
    os.remove(zip_name)
    shutil.rmtree(backup_dir)

async def main():
    init_db()
    users = db_query('SELECT user_id, api_id, api_hash, string_session FROM users WHERE is_active=1', fetch=True)
    if users:
        for u in users:
            if all(u): asyncio.create_task(start_user_listener(u[0], u[1], u[2], u[3]))
    print(f"Phantom Multi-User Online | {CREDIT}")
    await bot.polling(non_stop=True)

if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
