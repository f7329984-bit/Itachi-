import asyncio
import json
import os
import random
import time
import math
from datetime import datetime
from threading import Thread
from flask import Flask, jsonify
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityTextUrl, MessageEntityMentionName
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty

# =====================================================================
# ⚙️ CONFIG - APNA YAHI DAALO
# =====================================================================
API_ID = 24923714
API_HASH = '040929ee690bdb53b36484e017310358'
BOT_TOKEN = '8998315286:AAEqhh217BcA1e5XbTh0ku7s8I3omx19naU'  # @BotFather se lo
OWNER_ID = 8722144519  # Teri ID

SUDO_USERS = [OWNER_ID]
bot_status = "online"  # Default online
raid_active = {}
raid_speed = 1.5
GROUPS_CACHE = []
muted_users = {}  # Initialize here
USER_STATES = {}
BOT_USERNAME = ""
TEMP_DATA = {}

# =====================================================================
# 🌐 FLASK WEB SERVER FOR RENDER KEEP-ALIVE
# =====================================================================
app = Flask('')

@app.route('/')
def home():
    return jsonify({
        "status": "Bot is running!",
        "bot_status": bot_status,
        "groups": len(GROUPS_CACHE),
        "raid_lines": len(raid_lines) if 'raid_lines' in globals() else 0,
        "sudo_users": len(SUDO_USERS),
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/ping')
def ping():
    return jsonify({"status": "pong", "alive": True})

@app.route('/stats')
def stats():
    return jsonify({
        "bot_status": bot_status,
        "total_groups": len(GROUPS_CACHE),
        "raid_lines_count": len(raid_lines) if 'raid_lines' in globals() else 0,
        "sudo_users_count": len(SUDO_USERS),
        "active_raids": len(raid_active),
        "total_muted": sum(len(v) for v in muted_users.values()) if muted_users else 0
    })

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# Start web server in background thread (but not on Render - they handle it)
if not os.environ.get('RENDER'):
    Thread(target=run_web_server, daemon=True).start()

# =====================================================================
# 📁 AUTO FILE SYSTEM
# =====================================================================
DEFAULT_RAID_LINES = [
    "TERI MAKI CHUT MADARCHODO HIZDA HAI HAI TUM MADARCHODO BOL DE YUTA TERA BAAP HAI WARNA TERI KI CHUT KOI RAMDI KI AULAD NHI BACHA PAYEGA AAJ SAMJH LE MADRCHOD",
    "AIR JORDEN KE JUTE SE TERI KI CHUT PR MAAR MAAR KE LAAL KR DUNGA KALI SE LAAL 😋🥵 RANDI MADARCHODO",
    "MADARCHODO BAAP SE LADEGA APNE TERI MA KI CHUT KHA JAUNGA RAMDI",
]

DEFAULT_SHAYARI = {
    "love": ["Tumse milna ek khwab tha jo ab hakikat ban gaya 💕"],
    "sad": ["Tanhaiyon mein aansu bahate hain 😔"],
    "roast": ["Itni shakal buri ki aaina bhi tod de 🔥"],
}

# Create files if not exist
if not os.path.exists("raid_lines.json"):
    with open("raid_lines.json", "w") as f: json.dump(DEFAULT_RAID_LINES, f, indent=4)
if not os.path.exists("shayari.json"):
    with open("shayari.json", "w") as f: json.dump(DEFAULT_SHAYARI, f, indent=4)
if not os.path.exists("stickers.json"):
    with open("stickers.json", "w") as f: json.dump({"saved": []}, f, indent=4)
if not os.path.exists("muted_users.json"):
    with open("muted_users.json", "w") as f: json.dump({}, f, indent=4)
if not os.path.exists("settings.json"):
    with open("settings.json", "w") as f: json.dump({"photo_url": "https://picsum.photos/400/400"}, f, indent=4)

def read_json(path):
    try:
        with open(path) as f: return json.load(f)
    except: return {}

def write_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=4)

raid_lines = read_json("raid_lines.json")
shayari_data = read_json("shayari.json")
sticker_data = read_json("stickers.json")
settings = read_json("settings.json")
muted_users = read_json("muted_users.json")

# =====================================================================
# 🤖 BOT INIT
# =====================================================================
bot = TelegramClient('itachi_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# =====================================================================
# 🔐 HELPERS
# =====================================================================
async def is_auth(user_id):
    return user_id == OWNER_ID or user_id in SUDO_USERS

def get_mention(user):
    """REAL TAG/MENTION - bina username ke bhi kaam karta hai!"""
    return f"[{user.first_name}](tg://user?id={user.id})"

async def resolve_target(event, args):
    """Target resolve - reply ya @username ya userid se"""
    if event.is_reply:
        rep = await event.get_reply_message()
        return rep.sender_id, rep.sender
    if args:
        try:
            target = args[0]
            if target.startswith("@"):
                u = await bot.get_entity(target)
                return u.id, u
            return int(target), await bot.get_entity(int(target))
        except:
            return None, None
    return None, None

async def update_groups():
    """Update groups cache - FIXED FOR BOTS"""
    global GROUPS_CACHE
    GROUPS_CACHE = []
    try:
        # Bot apne groups ki list get kar sakta hai through get_dialogs
        dialogs = await bot.get_dialogs()
        for dialog in dialogs:
            if dialog.is_group or dialog.is_channel:
                GROUPS_CACHE.append(dialog.id)
        print(f"✅ Updated groups cache: {len(GROUPS_CACHE)} groups found")
    except Exception as e:
        print(f"⚠️ Error updating groups: {e}")
        # Agar error aaye to cache empty rakho
        GROUPS_CACHE = []

def format_text(text, user_mention=None):
    """Format text with user mention"""
    if user_mention:
        return text.replace("${USER}", user_mention)
    return text

# =====================================================================
# 🚫 BOT OFFLINE CHECK + UNAUTHORIZED PUNISH
# =====================================================================
@bot.on(events.NewMessage(incoming=True))
async def mute_checker(event):
    if not event.sender_id: return
    if event.sender_id == OWNER_ID or event.sender_id in SUDO_USERS: return
    
    cid = str(event.chat_id)
    uid = event.sender_id
    
    if cid in muted_users and uid in muted_users[cid]:
        try:
            await asyncio.sleep(0.05)
            await event.delete()
        except: pass

# =====================================================================
# 📋 MAIN COMMAND HANDLER
# =====================================================================
@bot.on(events.NewMessage(pattern=r'^[\.\/\!]'))
async def command_handler(event):
    global bot_status, raid_active, raid_speed, SUDO_USERS, muted_users, BOT_USERNAME, GROUPS_CACHE
    
    text = event.text.strip()
    user = await event.get_sender()
    user_id = user.id
    chat_id = event.chat_id
    
    # Extract command
    cmd_full = text[1:].strip()
    parts = cmd_full.split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:] if len(parts) > 1 else []
    
    if not BOT_USERNAME:
        me = await bot.get_me()
        BOT_USERNAME = me.username
    
    # ===== ALL KNOWN COMMANDS =====
    known = ['alive', 'start', 'menu', 'off', 'ping', 'speed', 'id', 'info', 'sudo', 'sudolist',
             'r', 'rr', 'rrr', 's', 'addline', 'lines', 'mute', 'unmute', 'shayari', 'addsticker',
             'sticker', 'broadcast', 'tagbroadcast', 'chatbox', 'hack', 'spam', 'quote', 'calc',
             'joke', 'gc', 'restart', 'truth', 'dare', 'setphoto', 'addsudo', 'remsudo', 'raidlines',
             'delallraid', 'shayaritypes', 'mutedlist', 'groupslist', 'botstats', 'forward']
    
    if cmd not in known:
        await event.reply(f"❌ **GALT COMMAND**\n`{text}` ye command exist nahi karti!\n📋 /menu se saari commands dekho!")
        return
    
    # ===== .alive =====
    if cmd == "alive":
        if not await is_auth(user_id):
            return await punish_unauthorized(event)
        
        bot_status = "online"
        me = await bot.get_me()
        await update_groups()
        
        photo_url = settings.get("photo_url", "https://picsum.photos/400/400")
        
        await event.reply(
            f"╔══════════════════════════════════╗\n"
            f"   🔥 **BOT IS NOW ONLINE** 🔥\n"
            f"╚══════════════════════════════════╝\n\n"
            f"🤖 **Bot:** @{me.username}\n"
            f"👑 **Owner:** `{OWNER_ID}`\n"
            f"⚡ **Mode:** `ACTIVE & LETHAL`\n"
            f"🔑 **Sudo Users:** `{len(SUDO_USERS)}`\n"
            f"📦 **Groups:** `{len(GROUPS_CACHE)}`\n"
            f"📜 **Raid Lines:** `{len(raid_lines)}`\n"
            f"🔇 **Muted Users:** `{sum(len(v) for v in muted_users.values())}`\n\n"
            f"✅ **BOT ONLINE!**",
            file=photo_url if photo_url.startswith("http") else None
        )
        return
    
    # ===== BOT OFFLINE CHECK =====
    if bot_status == "offline" and cmd not in ["alive", "start", "menu"]:
        await event.reply(f"❌ Bot offline hai! Pehle `.alive` karein!")
        return
    
    # ===== AUTH CHECK =====
    if not await is_auth(user_id):
        return await punish_unauthorized(event)
    
    # ===== /start or /menu =====
    if cmd in ["start", "menu"]:
        me = await bot.get_me()
        btns = [
            [Button.inline("👤 OWNER", data="owner")],
            [Button.inline("📋 COMMANDS", data="cmd_list")],
            [Button.url("➕ ADD TO GROUP", f"https://t.me/{me.username}?startgroup=true")],
        ]
        
        await event.reply(
            f"🔥 **ULTIMATE PRO MAX BOT** 🔥\n\n"
            f"👋 {get_mention(user)}!\n"
            f"⚡ **Status:** `{'🟢 ONLINE' if bot_status == 'online' else '🔴 OFFLINE'}`\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            buttons=btns
        )
        return
    
    # ===== .off =====
    if cmd == "off":
        bot_status = "offline"
        raid_active = {}
        await event.reply(f"🔴 Bot offline ho gaya! .alive se uthao!")
        return
    
    # ===== .ping =====
    if cmd == "ping":
        start = time.time()
        m = await event.reply("📡 Pinging...")
        end = time.time()
        ping = round((end-start)*1000, 2)
        await m.edit(f"⚡ **PONG!** `{ping}ms`")
        return
    
    # ===== .speed =====
    if cmd == "speed":
        await event.reply(f"🚀 **Raid Speed:** `{raid_speed}s`")
        return
    
    # ===== .id =====
    if cmd == "id":
        await event.reply(
            f"👤 **Name:** {get_mention(user)}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"👑 **Owner:** {'✅' if user_id==OWNER_ID else '❌'}\n"
            f"🔑 **Sudo:** {'✅' if user_id in SUDO_USERS else '❌'}"
        )
        return
    
    # ===== .info =====
    if cmd == "info":
        target_id, target_user = await resolve_target(event, args)
        if not target_id:
            await event.reply("❌ Usage: `.info @username`")
            return
        try:
            u = target_user or await bot.get_entity(target_id)
            await event.reply(
                f"👤 {get_mention(u)}\n"
                f"🆔 `{u.id}`\n"
                f"📛 @{u.username if u.username else 'N/A'}"
            )
        except Exception as e:
            await event.reply(f"❌ Error: {e}")
        return
    
    # ===== .sudo / .addsudo =====
    if cmd in ["sudo", "addsudo"]:
        if user_id != OWNER_ID:
            await event.reply("❌ Sirf owner!")
            return
        target_id, target_user = await resolve_target(event, args)
        if not target_id:
            await event.reply("❌ Usage: `.sudo @username`")
            return
        
        if target_id in SUDO_USERS:
            await event.reply("❌ Already sudo!")
            return
        
        SUDO_USERS.append(target_id)
        await event.reply(f"✅ Sudo added! User can now use bot commands.")
        return
    
    if cmd == "remsudo":
        if user_id != OWNER_ID:
            await event.reply("❌ Sirf owner!")
            return
        target_id, target_user = await resolve_target(event, args)
        if not target_id:
            await event.reply("❌ Usage: `.remsudo @username`")
            return
        
        if target_id in SUDO_USERS:
            SUDO_USERS.remove(target_id)
            await event.reply(f"✅ Sudo removed!")
        else:
            await event.reply("❌ Not a sudo user!")
        return
    
    if cmd == "sudolist":
        text = "🔐 **SUDO USERS**\n\n"
        for sid in SUDO_USERS:
            try:
                u = await bot.get_entity(sid)
                text += f"• {get_mention(u)} - `{sid}`\n"
            except:
                text += f"• `{sid}`\n"
        await event.reply(text)
        return
    
    # ===== RAID COMMANDS =====
    if cmd in ["r", "rr", "rrr"]:
        if raid_active.get(chat_id, False):
            await event.reply("❌ Raid already active! Use `.s` to stop.")
            return
        
        target_id, target_user = await resolve_target(event, args)
        if not target_id:
            await event.reply("❌ Usage: `.r @username`")
            return
        
        speed = 1.5 if cmd == "r" else (0.6 if cmd == "rr" else 0.25)
        raid_speed = speed
        
        mention = get_mention(target_user or await bot.get_entity(target_id))
        
        await event.reply(
            f"⚔️ **RAID STARTED** ⚔️\n"
            f"🎯 Target: {mention}\n"
            f"⚡ Speed: `{speed}s`\n"
            f"🔥 Raid chal raha hai..."
        )
        
        raid_active[chat_id] = True
        
        try:
            while raid_active.get(chat_id, False):
                for line in raid_lines:
                    if not raid_active.get(chat_id, False):
                        break
                    final = line.replace("${USER}", mention) if "${USER}" in line else f"{mention} {line}"
                    try:
                        await bot.send_message(chat_id, final)
                    except: pass
                    await asyncio.sleep(speed)
        except: pass
        
        raid_active[chat_id] = False
        return
    
    # ===== .s - STOP RAID =====
    if cmd == "s":
        if not raid_active.get(chat_id, False):
            await event.reply("❌ No active raid!")
            return
        raid_active[chat_id] = False
        await event.reply(f"🛑 **RAID STOPPED**")
        return
    
    # ===== .addline =====
    if cmd == "addline":
        if not args:
            await event.reply("❌ Usage: `.addline Teri maa ki chut`")
            return
        line = " ".join(args)
        raid_lines.append(line)
        write_json("raid_lines.json", raid_lines)
        await event.reply(f"✅ Line added! Total: `{len(raid_lines)}`")
        return
    
    # ===== .lines =====
    if cmd == "lines":
        if not raid_lines:
            await event.reply("❌ No raid lines! Add with `.addline`")
            return
        text = "📜 **RAID LINES**\n\n"
        for i, line in enumerate(raid_lines[:10], 1):
            text += f"`{i}.` {line[:50]}...\n"
        await event.reply(text)
        return
    
    # ===== .mute =====
    if cmd == "mute":
        target_id, target_user = await resolve_target(event, args)
        if not target_id:
            await event.reply("❌ Usage: `.mute @username`")
            return
        
        cid = str(chat_id)
        if cid not in muted_users:
            muted_users[cid] = []
        if target_id not in muted_users[cid]:
            muted_users[cid].append(target_id)
            write_json("muted_users.json", muted_users)
            await event.reply(f"🔇 User muted!")
        else:
            await event.reply("❌ Already muted!")
        return
    
    # ===== .unmute =====
    if cmd == "unmute":
        target_id, target_user = await resolve_target(event, args)
        if not target_id:
            await event.reply("❌ Usage: `.unmute @username`")
            return
        
        cid = str(chat_id)
        if cid in muted_users and target_id in muted_users[cid]:
            muted_users[cid].remove(target_id)
            if not muted_users[cid]:
                del muted_users[cid]
            write_json("muted_users.json", muted_users)
            await event.reply(f"✅ User unmuted!")
        else:
            await event.reply("❌ User not muted!")
        return
    
    # ===== .shayari =====
    if cmd == "shayari":
        if not args:
            types_text = "\n".join([f"• `{t}`" for t in shayari_data.keys()])
            await event.reply(f"📖 **SHAYARI TYPES**\n\n{types_text}\n\n`.shayari love @user`")
            return
        
        stype = args[0].lower()
        if stype not in shayari_data:
            await event.reply(f"❌ Type not found! Available: {', '.join(shayari_data.keys())}")
            return
        
        if len(args) >= 2 and args[1].startswith("@"):
            try:
                target_id, target_user = await resolve_target(event, [args[1]])
                u = target_user or await bot.get_entity(target_id)
                mention = get_mention(u)
                
                if not shayari_data[stype]:
                    await event.reply(f"❌ No shayari in `{stype}`")
                    return
                
                line = random.choice(shayari_data[stype])
                final = line.replace("${USER}", mention) if "${USER}" in line else f"{mention} {line}"
                await bot.send_message(chat_id, final)
            except Exception as e:
                await event.reply(f"❌ Error: {e}")
        else:
            await event.reply(f"❌ Usage: `.shayari {stype} @user`")
        return
    
    # ===== .broadcast =====
    if cmd == "broadcast":
        if not args:
            await event.reply("❌ Usage: `.broadcast [msg]`")
            return
        bmsg = " ".join(args)
        await update_groups()
        status = await event.reply("📢 Broadcasting...")
        count = 0
        for gid in GROUPS_CACHE:
            try:
                await bot.send_message(gid, f"📢 **BROADCAST**\n\n{bmsg}")
                count += 1
                await asyncio.sleep(0.3)
            except: pass
        await status.edit(f"✅ Broadcast complete! `{count}/{len(GROUPS_CACHE)}` groups")
        return
    
    # ===== .gc =====
    if cmd in ["gc", "groupslist"]:
        await update_groups()
        text = f"📦 **GROUPS:** `{len(GROUPS_CACHE)}`\n\n"
        for gid in GROUPS_CACHE[:20]:
            text += f"• `{gid}`\n"
        await event.reply(text)
        return
    
    # ===== .botstats =====
    if cmd == "botstats":
        await update_groups()
        await event.reply(
            f"📊 **BOT STATS**\n\n"
            f"Status: {'🟢 ONLINE' if bot_status == 'online' else '🔴 OFFLINE'}\n"
            f"Groups: `{len(GROUPS_CACHE)}`\n"
            f"Raid Lines: `{len(raid_lines)}`\n"
            f"Sudo Users: `{len(SUDO_USERS)}`\n"
            f"Muted: `{sum(len(v) for v in muted_users.values())}`\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return
    
    # ===== .restart =====
    if cmd == "restart":
        if user_id != OWNER_ID:
            await event.reply("❌ Owner only!")
            return
        await event.reply("🔄 Restarting...")
        os._exit(0)
    
    # ===== DEFAULT RESPONSE =====
    await event.reply(f"✅ Command `{cmd}` executed! Use `.menu` for all commands.")

# =====================================================================
# 💀 UNAUTHORIZED PUNISHMENT
# =====================================================================
async def punish_unauthorized(event):
    user = await event.get_sender()
    mention = get_mention(user)
    
    lines = [
        f"❌ {mention} You are not authorized to use this bot!\n👑 Contact owner: `{OWNER_ID}`"
    ]
    
    for line in lines:
        try:
            await event.reply(line)
            await asyncio.sleep(0.8)
        except: pass

# =====================================================================
# 🔄 CALLBACK HANDLER
# =====================================================================
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode()
    user_id = event.sender_id
    
    if data == "owner":
        await event.edit(
            f"👑 **BOT OWNER**\n\n"
            f"🆔 ID: `{OWNER_ID}`\n"
            f"📡 Status: {'🟢 ONLINE' if bot_status == 'online' else '🔴 OFFLINE'}",
            buttons=[[Button.inline("⬅️ Back", data="main")]]
        )
    
    elif data == "cmd_list":
        await event.edit(
            "📋 **COMMANDS**\n\n"
            "`.alive` - Start bot\n"
            "`.off` - Stop bot\n"
            "`.r @user` - Raid\n"
            "`.s` - Stop raid\n"
            "`.mute @user` - Mute\n"
            "`.unmute @user` - Unmute\n"
            "`.broadcast [msg]` - Broadcast\n"
            "`.shayari love @user` - Send shayari\n"
            "`.ping` - Check ping\n"
            "`.botstats` - Bot statistics",
            buttons=[[Button.inline("⬅️ Back", data="main")]]
        )
    
    elif data == "main":
        me = await bot.get_me()
        btns = [
            [Button.inline("👤 OWNER", data="owner")],
            [Button.inline("📋 COMMANDS", data="cmd_list")],
            [Button.url("➕ ADD TO GROUP", f"https://t.me/{me.username}?startgroup=true")],
        ]
        await event.edit(
            f"🔥 **ULTIMATE PRO MAX BOT** 🔥\n\n"
            f"⚡ Status: {'🟢 ONLINE' if bot_status == 'online' else '🔴 OFFLINE'}",
            buttons=btns
        )

# =====================================================================
# 📥 INPUT STATE HANDLER
# =====================================================================
@bot.on(events.NewMessage(incoming=True))
async def input_state_handler(event):
    user_id = event.sender_id
    if user_id not in USER_STATES:
        return
    
    state = USER_STATES[user_id]
    text = event.text.strip()
    
    if state == "AWAITING_PHOTO":
        del USER_STATES[user_id]
        settings["photo_url"] = text
        write_json("settings.json", settings)
        await event.reply(f"✅ Photo updated!")

# =====================================================================
# 📦 AUTO GROUP TRACK
# =====================================================================
@bot.on(events.ChatAction)
async def chat_action(event):
    if event.user_added:
        me = await bot.get_me()
        for u in event.users:
            if u.id == me.id:
                await event.reply(
                    f"🔥 **BOT ADDED** 🔥\n\n"
                    f"Thanks for adding me!\n"
                    f"👑 Owner: `{OWNER_ID}`\n"
                    f"📋 /menu for commands"
                )
                await update_groups()

# =====================================================================
# 🚀 START
# =====================================================================
async def main():
    await update_groups()
    me = await bot.get_me()
    print(f"""
╔══════════════════════════════╗
   🔥 BOT STARTED SUCCESSFULLY 🔥
╚══════════════════════════════╝
  🤖 Bot: @{me.username}
  👑 Owner: {OWNER_ID}
  📦 Groups: {len(GROUPS_CACHE)}
  📜 Lines: {len(raid_lines)}
  🔑 Sudo: {len(SUDO_USERS)}
  ✅ BOT IS READY!
""")

if __name__ == "__main__":
    print("Starting bot...")
    bot.loop.run_until_complete(main())
    print("Bot is running...")
    bot.run_until_disconnected()
