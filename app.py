import os, asyncio, sqlite3, zipfile
from flask import Flask
from threading import Thread
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telethon import TelegramClient, errors, events, functions, types
from telethon.sessions import StringSession

# --- Config ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_NAME = 'database.db'
ADMIN_ID = 8373846582
CREDIT = "「 Prime Xyron 」👨‍💻"

bot = AsyncTeleBot(BOT_TOKEN)
user_states, active_clients, reply_tracking = {}, {}, {}

# --- Flask Server for Render ---
app = Flask('')
@app.route('/')
def home(): return "Phantom Ghost System is Live"

def run_flask():
    # Render সাধারণত পোর্ট পরিবেশ ভেরিয়েবল থেকে নেয়, না থাকলে ৮0৮0 ব্যবহার করবে
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
        except sqlite3.OperationalError:
            return None

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, api_id INTEGER, api_hash TEXT, 
            string_session TEXT, custom_reply TEXT DEFAULT "I'm currently offline.", 
            is_active INTEGER DEFAULT 0, is_enabled INTEGER DEFAULT 1)''')

# --- Ghost Listener (15s Logic) ---
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

        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def handler(event):
            row = db_query('SELECT custom_reply, is_enabled FROM users WHERE user_id=?', (uid,), True)
            if not row or row[0][1] == 0: return

            try:
                me = await client(functions.users.GetUsersRequest(id=['me']))
                if isinstance(me[0].status, types.UserStatusOnline): return

                # ১. আইডি অনলাইনে আনা
                await client(functions.account.UpdateStatusRequest(offline=False))
                
                # ২. রিপ্লাই দেওয়া
                await event.reply(row[0][0])
                
                # ৩. ১৫ সেকেন্ড টাইমার (Online Burst)
                reply_tracking[uid] = reply_tracking.get(uid, 0) + 1
                current_call = reply_tracking[uid]
                await asyncio.sleep(15)
                
                # ৪. অফলাইনে ফিরে যাওয়া
                if reply_tracking.get(uid) == current_call:
                    await client(functions.account.UpdateStatusRequest(offline=True))
                
            except: pass

        await client.run_until_disconnected()
    except: pass
    finally: active_clients.pop(uid, None)

# --- Bot Handlers with your Professional UI ---

@bot.message_handler(commands=['start'])
async def welcome(m):
    db_query('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (m.from_user.id,))
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⚙️ Settings", "✏️ Set Reply", "📊 Status")
    
    text = (
        "👻 𝙿𝚑𝚊𝚗𝚝𝚘𝚖 𝚁𝚎𝚙𝚕𝚢\n\n"
        "Welcome to your Telegram shadow.\n"
        "When you are offline, I automatically reply to messages for you.\n\n"
        "আপনি অনলাইনে থাকলে আমি কোনো রিপ্লাই করবো না.\n\n"
        "⚡ Smart Presence Detection\n"
        "💬 Custom Auto Reply\n"
        "🔐 Secure Login System\n\n"
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

    text = (
        "⚙️ 𝚂𝚎𝚝𝚝𝚒𝚗𝚐𝚜 𝙿𝚊𝚗𝚎𝚕\n\n"
        f"Account Status : {status}\n\n"
        "If your account is not connected,\n"
        "please login using your Telegram API.\n\n"
        "🔒 Your session will remain private."
    )
    await bot.send_message(uid, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
async def callbacks(c):
    uid = c.from_user.id
    if c.data == "login":
        user_states[uid] = {'step': 'api'}
        await bot.send_message(uid, "🔑 𝙰𝙿𝙸 𝙰𝚞𝚝𝚑𝚎𝚗𝚝𝚒𝚌𝚊𝚝𝚒𝚘𝚗\n\nSend your credentials in this format :\n\nAPI_ID:API_HASH\n\nExample :\n123456:abcd1234efgh5678\n\n⚠️ Never share your API with anyone.")
    elif c.data == "toggle":
        db_query('UPDATE users SET is_enabled = 1 - is_enabled WHERE user_id=?', (uid,))
        await settings(c.message)
    elif c.data == "logout":
        db_query('UPDATE users SET string_session=NULL, is_active=0 WHERE user_id=?', (uid,))
        if uid in active_clients: await active_clients[uid].disconnect()
        await bot.send_message(uid, "🔴 𝚂𝚎𝚜𝚜𝚒𝚘𝚗 𝚁𝚎𝚖𝚘𝚟𝚎𝚍\n\nYour Telegram session has been cleared.")

@bot.message_handler(func=lambda m: m.from_user.id in user_states)
async def login_flow(m):
    uid = m.from_user.id
    state = user_states[uid]['step']

    if state == 'api' and ':' in m.text:
        aid, ahash = m.text.split(':', 1)
        user_states[uid].update({'api_id': aid.strip(), 'api_hash': ahash.strip(), 'step': 'phone'})
        await bot.send_message(uid, "📱 𝙿𝚑𝚘𝚗𝚎 𝚅𝚎𝚛𝚒𝚏𝚒𝚌𝚊𝚝𝚒𝚘𝚗\n\nSend your Telegram phone number.\n\nExample :\n+8801XXXXXXXXX\n\nOTP code will be sent to your Telegram.")
    
    elif state == 'phone':
        user_states[uid]['phone'] = m.text.strip()
        client = TelegramClient(StringSession(), int(user_states[uid]['api_id']), user_states[uid]['api_hash'])
        await client.connect()
        try:
            sent = await client.send_code_request(user_states[uid]['phone'])
            user_states[uid].update({'hash': sent.phone_code_hash, 'step': 'otp', 'client': client})
            await bot.send_message(uid, "📩 𝙾𝚃𝙿 𝙲𝚘𝚍𝚎\n\nEnter the login code you received.\n\nExample :\n1 2 3 4 5\n\n⏳ Please enter it quickly before it expires.")
        except Exception as e:
            await bot.send_message(uid, f"❌ Error: {e}")
            user_states.pop(uid)

    elif state == 'otp':
        try:
            client = user_states[uid]['client']
            await client.sign_in(user_states[uid]['phone'], m.text.replace(' ',''), phone_code_hash=user_states[uid]['hash'])
            ss = client.session.save()
            db_query('UPDATE users SET api_id=?, api_hash=?, string_session=?, is_active=1 WHERE user_id=?', 
                      (user_states[uid]['api_id'], user_states[uid]['api_hash'], ss, uid))
            await bot.send_message(uid, "✅ 𝙻𝚘𝚐𝚒𝚗 𝚂𝚞𝚌𝚌𝚎𝚜𝚜\n\nYour Telegram account is now connected.\n\n👻 Phantom Reply is now active.")
            asyncio.create_task(start_user_listener(uid, user_states[uid]['api_id'], user_states[uid]['api_hash'], ss))
            user_states.pop(uid)
        except errors.SessionPasswordNeededError:
            user_states[uid]['step'] = '2fa'
            await bot.send_message(uid, "🔐 𝟸𝙵𝙰 𝚂𝚎𝚌𝚞𝚛𝚒𝚝𝚢\n\nYour account has Two-Step Verification enabled.\n\nPlease enter your password to continue.\n\nনিরাপত্তার জন্য এটি প্রয়োজন.")
        except Exception as e: await bot.send_message(uid, f"❌ Error: {e}")

    elif state == '2fa':
        client = user_states[uid]['client']
        await client.sign_in(password=m.text.strip())
        ss = client.session.save()
        db_query('UPDATE users SET string_session=?, is_active=1 WHERE user_id=?', (ss, uid))
        await bot.send_message(uid, "✅ 𝙻𝚘𝚐𝚒𝚗 𝚂𝚞𝚌𝚌𝚎𝚜𝚜")
        asyncio.create_task(start_user_listener(uid, user_states[uid]['api_id'], user_states[uid]['api_hash'], ss))
        user_states.pop(uid)

    elif state == 'wait_reply':
        db_query('UPDATE users SET custom_reply=? WHERE user_id=?', (m.text, uid))
        await bot.send_message(uid, "✅ 𝚁𝚎𝚙𝚕𝚢 𝚂𝚊𝚟𝚎𝚍\n\nYour auto-reply message has been updated successfully.")
        user_states.pop(uid)

@bot.message_handler(func=lambda m: m.text == "✏️ Set Reply")
async def set_rep(m):
    user_states[m.from_user.id] = {'step': 'wait_reply'}
    await bot.send_message(m.chat.id, "✏️ 𝙲𝚞𝚜𝚝𝚘𝚖 𝙰𝚞𝚝𝚘 𝚁𝚎𝚙𝚕𝚢\n\nSend the message you want people to receive when you are offline.\n\nExample :\nI'm currently offline. I'll reply later.\n\nআপনি চাইলে বাংলা বা ইংরেজি লিখতে পারেন.")

@bot.message_handler(func=lambda m: m.text == "📊 Status")
async def status_check(m):
    uid = m.from_user.id
    row = db_query('SELECT custom_reply, is_active, is_enabled FROM users WHERE user_id=?', (uid,), True)
    if row and row[0][1] == 1:
        s = "Active" if row[0][2] == 1 else "Disabled"
        text = f"📊 𝙱𝚘𝚝 𝚂𝚝𝚊𝚝𝚞𝚜\n\nReply : {row[0][0]}\n\nListener : {s}\n\nMode : Smart Offline Only\n\nআপনি অনলাইনে থাকলে বট কখনো রিপ্লাই করবে না."
        await bot.send_message(uid, text)
    else:
        await bot.send_message(uid, "❌ Not connected.")

@bot.message_handler(commands=['admin'])
async def admin_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    with zipfile.ZipFile("backup.zip", 'w') as z:
        if os.path.exists(DB_NAME): z.write(DB_NAME)
    with open("backup.zip", 'rb') as f:
        await bot.send_document(m.chat.id, f, caption="📊 Admin Backup")
    os.remove("backup.zip")

async def main():
    init_db()
    users = db_query('SELECT user_id, api_id, api_hash, string_session FROM users WHERE is_active=1', fetch=True)
    if users:
        for u in users:
            if all(u): asyncio.create_task(start_user_listener(u[0], u[1], u[2], u[3]))
    print(f"Phantom Burst Online | {CREDIT}")
    await bot.polling(non_stop=True)

if __name__ == '__main__':
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
