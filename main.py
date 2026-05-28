import os
import logging
import random
from datetime import datetime, timedelta
from collections import defaultdict

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from openai import AsyncOpenAI

import db
from constants import (
    OWNER_USERNAMES, BOT_USERNAME, GROUP_LINK, ITEMS,
    STICKER_PACK_NAMES,
    BOUNTY_PER_KILL_NORMAL, BOUNTY_PER_KILL_PREMIUM,
    KILL_BALANCE_MIN_NORMAL, KILL_BALANCE_MAX_NORMAL,
    KILL_BALANCE_MIN_PREMIUM, KILL_BALANCE_MAX_PREMIUM,
    DAILY_BALANCE_NORMAL, DAILY_BALANCE_PREMIUM,
    ROB_MAX_NORMAL, ROB_MAX_DAILY_NORMAL,
    SYSTEM_PROMPT
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

# ── Sticker cache ──────────────────────────────────────────────────────────────
cached_sticker_file_ids: list[str] = []

# ── AI conversation history ────────────────────────────────────────────────────
conv_history: dict[int, list[dict]] = defaultdict(list)
MAX_HISTORY = 20

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_owner(username: str | None) -> bool:
    return bool(username and username.lower() in OWNER_USERNAMES)


def is_group(update: Update) -> bool:
    return update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def should_respond_in_group(update: Update) -> bool:
    msg = update.message
    if not msg:
        return False
    text = msg.text or ""
    if "nami" in text.lower():
        return True
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username == BOT_USERNAME:
            return True
    if msg.entities:
        for e in msg.entities:
            if e.type == "mention" and text[e.offset:e.offset + e.length] == f"@{BOT_USERNAME}":
                return True
    return False


def get_random_sticker() -> str | None:
    if not cached_sticker_file_ids:
        return None
    return random.choice(cached_sticker_file_ids)


async def load_sticker_packs(app: Application):
    for pack_name in STICKER_PACK_NAMES:
        try:
            pack = await app.bot.get_sticker_set(pack_name)
            for s in pack.stickers:
                cached_sticker_file_ids.append(s.file_id)
        except Exception as e:
            logger.warning(f"Failed to load sticker pack {pack_name}: {e}")
    logger.info(f"Sticker cache loaded: {len(cached_sticker_file_ids)} stickers")


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await db.get_or_create_user(u.id, u.first_name, u.username)

    args = ctx.args
    start_param = args[0] if args else None

    if start_param and start_param.startswith("join_"):
        code = start_param[5:]
        ship = await db.get_ship_by_code(code)
        if ship:
            bal = await db.get_ship_balance(ship["id"])
            members = await db.get_ship_member_count(ship["id"])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("⚓ Join Ship", callback_data=f"join_ship_{ship['id']}")
            ]])
            await update.message.reply_text(
                f"⛵ *{ship['name']}* [{ship['code']}]\n"
                f"💰 Balance: ${bal:,}\n👥 Members: {members}\n\nJoin this ship?",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb
            )
            return

    NAMI_PHOTO_URL = "https://files.catbox.moe/vremhb.png"
    caption = f"Hey {u.first_name}!\nI'm Nami 🍊\nso Enjoy fresh content, new games, and ongoing feature enhancements"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("L ɪ ɢ ʜ ᴛ ✦", callback_data="show_owners")],
        [InlineKeyboardButton("🌊 Group", url=GROUP_LINK)],
        [InlineKeyboardButton("➕ Add me to your group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")],
        [InlineKeyboardButton("⚔️ Select Job", callback_data="select_job")],
    ])
    try:
        await update.message.reply_photo(NAMI_PHOTO_URL, caption=caption, reply_markup=kb)
    except Exception:
        await update.message.reply_text(caption, reply_markup=kb)


# ── Callback queries ───────────────────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    u = query.from_user

    if data == "show_owners":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("𝑨𝒖𝒓𝒂 ✘", url="https://t.me/light_speedi"),
                InlineKeyboardButton("L ɪ ɢ ʜ ᴛ", url="https://t.me/light_speedy"),
            ],
            [InlineKeyboardButton("◀ Back", callback_data="back_start")],
        ])
        await query.edit_message_reply_markup(kb)
        await query.answer()

    elif data == "back_start":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("L ɪ ɢ ʜ ᴛ ✦", callback_data="show_owners")],
            [InlineKeyboardButton("🌊 Group", url=GROUP_LINK)],
            [InlineKeyboardButton("➕ Add me to your group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")],
            [InlineKeyboardButton("⚔️ Select Job", callback_data="select_job")],
        ])
        await query.edit_message_reply_markup(kb)
        await query.answer()

    elif data == "select_job":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚔️ Bounty Hunter", callback_data="job_bounty"),
                InlineKeyboardButton("🏴‍☠️ Become Pirate", callback_data="job_pirate"),
            ],
            [InlineKeyboardButton("◀ Back", callback_data="back_start")],
        ])
        await query.edit_message_reply_markup(kb)
        await query.answer()

    elif data == "job_bounty":
        await db.update_user(u.id, job="bounty_hunter")
        top_ships = await db.get_top_ships(30)
        buttons = [
            [InlineKeyboardButton(
                f"{i+1}. {s['name']} [{s['code']}] — ${s['ship_balance']:,}",
                callback_data=f"ship_info_{s['id']}"
            )]
            for i, s in enumerate(top_ships)
        ]
        buttons.append([InlineKeyboardButton("◀ Back", callback_data="select_job")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
        await query.answer("✅ You are now a Bounty Hunter!")
        await query.message.reply_text(
            "⚔️ *Your job selected!*\n\nYou are now a *Bounty Hunter*\nThese are top ships — click to check ships 🚢",
            parse_mode=ParseMode.MARKDOWN
        )

    elif data == "job_pirate":
        await db.update_user(u.id, job="pirate")
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚓ Join Crew Ships", callback_data="pirate_join_list"),
                InlineKeyboardButton("🚢 Make Own Ship", callback_data="pirate_make"),
            ],
            [InlineKeyboardButton("◀ Back", callback_data="select_job")],
        ])
        await query.edit_message_reply_markup(kb)
        await query.answer("🏴‍☠️ You are now a Pirate!")

    elif data == "pirate_join_list":
        top_ships = await db.get_top_ships(30)
        if not top_ships:
            await query.answer("No ships yet! Create one with /newship")
            return
        buttons = [
            [InlineKeyboardButton(
                f"{i+1}. {s['name']} [{s['code']}] — ${s['ship_balance']:,}",
                callback_data=f"ship_info_{s['id']}"
            )]
            for i, s in enumerate(top_ships)
        ]
        buttons.append([InlineKeyboardButton("◀ Back", callback_data="job_pirate")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
        await query.answer()

    elif data == "pirate_make":
        await query.answer()
        await query.message.reply_text("🚢 Use `/newship <ship name>` command to create your own ship!", parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("ship_info_"):
        ship_id = int(data[10:])
        ship = await db.get_ship_by_id(ship_id)
        if not ship:
            await query.answer("Ship not found")
            return
        bal = await db.get_ship_balance(ship_id)
        members = await db.get_ship_member_count(ship_id)
        await query.answer()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚓ Join Ship", callback_data=f"join_ship_{ship_id}")]])
        await query.message.reply_text(
            f"⛵ *{ship['name']}* [{ship['code']}]\n💰 Balance: ${bal:,}\n👥 Members: {members}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )

    elif data.startswith("join_ship_"):
        ship_id = int(data[10:])
        user = await db.get_or_create_user(u.id, u.first_name, u.username)
        if user.get("ship_id"):
            await query.answer("❌ You're already in a ship! /leaveship first.")
            return
        ship = await db.get_ship_by_id(ship_id)
        if not ship:
            await query.answer("Ship not found")
            return
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE game_users SET ship_id = $1 WHERE telegram_id = $2", ship_id, u.id)
            await conn.execute("INSERT INTO ship_members (ship_id, user_id, role) VALUES ($1, $2, 'member')", ship_id, u.id)
        await query.answer(f"✅ Joined {ship['name']}!")
        await query.message.reply_text(f"⚓ You've joined ship *{ship['name']}* [{ship['code']}]!", parse_mode=ParseMode.MARKDOWN)

    else:
        await query.answer()


# ── Game Commands ──────────────────────────────────────────────────────────────

async def cmd_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Bounty Hunter", callback_data="job_bounty"),
        InlineKeyboardButton("🏴‍☠️ Become Pirate", callback_data="job_pirate"),
    ]])
    await update.message.reply_text(
        "⚔️ <b>Select your Job</b>\n\nKoi ek job chuno:",
        parse_mode=ParseMode.HTML,
        reply_to_message_id=update.message.message_id,
        reply_markup=kb
    )


async def cmd_leavejob(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_or_create_user(update.effective_user.id, update.effective_user.first_name, update.effective_user.username)
    if not user.get("job"):
        return await update.message.reply_text("❌ Aapne koi job select hi nahi ki hai!", reply_to_message_id=update.message.message_id)
    old_job = "⚔️ Bounty Hunter" if user["job"] == "bounty_hunter" else "🏴‍☠️ Pirate"
    await db.update_user(update.effective_user.id, job=None)
    await update.message.reply_text(
        f"✅ Aapne <b>{old_job}</b> job leave kar di! /select se naya job chuno.",
        parse_mode=ParseMode.HTML, reply_to_message_id=update.message.message_id
    )


async def cmd_bal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        ru = msg.reply_to_message.from_user
        target = await db.get_or_create_user(ru.id, ru.first_name, ru.username)
    else:
        u = update.effective_user
        target = await db.get_or_create_user(u.id, u.first_name, u.username)

    rank = await db.get_global_rank(target["telegram_id"], target["balance"])
    kill_rank = await db.get_kill_rank(target["telegram_id"])
    tag = db.get_kill_tag(target["kills"], kill_rank)
    ship = await db.get_user_ship(target.get("ship_id"))
    best_item = await db.get_most_expensive_item(target["telegram_id"])
    job_display = "⚔️ Bounty Hunter" if target.get("job") == "bounty_hunter" else "🏴‍☠️ Pirate" if target.get("job") == "pirate" else "None"
    premium_badge = " ⭐" if db.is_premium_active(target) else ""
    prefix = "💓 " if db.is_premium_active(target) else "👤 "

    text = (
        f"{prefix}**Name:** {target['first_name']}{tag}{premium_badge}\n"
        f"💰 **Balance:** ${target['balance']:,}\n"
        f"🏆 **Global Rank:** #{rank}\n"
        f"❤️ **Job:** {job_display}\n"
        f"⛵️ **Ship:** {f\"{ship['name']} [{ship['code']}]\" if ship else 'None'}\n"
        f"⚔️ **Kills:** {target['kills']}\n"
        f"💸 **Bounty:** ${target['bounty_amount']:,}\n"
        f"🎁 **Items:** {best_item or 'None'}"
    )
    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_kill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Reply karo jise kill karna hai!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    if target_user.id == update.effective_user.id:
        return await msg.reply_text("❌ Khud ko kill nahi kar sakte 😆", reply_to_message_id=msg.message_id)

    killer = await db.get_or_create_user(update.effective_user.id, update.effective_user.first_name, update.effective_user.username)
    victim = await db.get_or_create_user(target_user.id, target_user.first_name, target_user.username)

    if db.is_protected(victim):
        return await msg.reply_text(f"🛡 *{target_user.first_name}* is protected! Kill nahi kar sakte.", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)

    premium = db.is_premium_active(killer)
    bal_gain = db.rand(
        KILL_BALANCE_MIN_PREMIUM if premium else KILL_BALANCE_MIN_NORMAL,
        KILL_BALANCE_MAX_PREMIUM if premium else KILL_BALANCE_MAX_NORMAL
    )
    bounty_gain = BOUNTY_PER_KILL_PREMIUM if premium else BOUNTY_PER_KILL_NORMAL
    victim_bounty = victim["bounty_amount"]
    total_gain = bal_gain + victim_bounty

    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE game_users SET kills = kills + 1, balance = balance + $1, bounty_amount = bounty_amount + $2 WHERE telegram_id = $3",
            total_gain, bounty_gain, killer["telegram_id"]
        )
        await conn.execute("UPDATE game_users SET bounty_amount = 0 WHERE telegram_id = $1", victim["telegram_id"])

    text = (
        f"⚔️ *{killer['first_name']}* killed *{target_user.first_name}*!\n"
        f"💰 +${bal_gain:,} kill reward\n"
        + (f"💸 +${victim_bounty:,} bounty claimed\n" if victim_bounty > 0 else "")
        + f"📈 Total gained: ${total_gain:,}\n"
        f"🎯 Bounty +${bounty_gain}"
    )
    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_rob(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    args = ctx.args
    if not args or not args[0].isdigit():
        return await msg.reply_text("❌ Usage: /rob <amount> (reply to someone)", reply_to_message_id=msg.message_id)
    amount = int(args[0])
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Usage: /rob <amount> (reply to someone)", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    if target_user.id == update.effective_user.id:
        return await msg.reply_text("❌ Khud ko rob nahi kar sakte!", reply_to_message_id=msg.message_id)

    robber = await db.get_or_create_user(update.effective_user.id, update.effective_user.first_name, update.effective_user.username)
    victim = await db.get_or_create_user(target_user.id, target_user.first_name, target_user.username)

    if db.is_protected(victim):
        return await msg.reply_text(f"🛡 *{target_user.first_name}* is protected!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)

    premium = db.is_premium_active(robber)
    if not premium and amount > ROB_MAX_NORMAL:
        return await msg.reply_text(f"❌ Normal user ek baar mein max ${ROB_MAX_NORMAL:,} rob kar sakta hai!", reply_to_message_id=msg.message_id)

    today = db.today_date()
    rob_count = robber["rob_count_today"] if robber.get("rob_date") == today else 0
    if not premium and rob_count >= ROB_MAX_DAILY_NORMAL:
        return await msg.reply_text("❌ Aaj ka rob limit khatam! Kal dobara aana 😅", reply_to_message_id=msg.message_id)

    if victim["balance"] < amount:
        return await msg.reply_text(f"❌ {target_user.first_name} ke paas sirf ${victim['balance']:,} hai!", reply_to_message_id=msg.message_id)

    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE game_users SET balance = balance + $1, rob_count_today = $2, rob_date = $3 WHERE telegram_id = $4",
            amount, rob_count + 1, today, robber["telegram_id"]
        )
        await conn.execute("UPDATE game_users SET balance = balance - $1 WHERE telegram_id = $2", amount, victim["telegram_id"])

    await msg.reply_text(
        f"🥷 *{robber['first_name']}* ne *{target_user.first_name}* se ${amount:,} rob kiya!",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


async def cmd_protect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    args = ctx.args
    if not args or args[0] not in ("1d", "2d"):
        return await msg.reply_text("❌ Usage: /protect 1d  or  /protect 2d (2d is premium)", reply_to_message_id=msg.message_id)
    arg = args[0]
    user = await db.get_or_create_user(update.effective_user.id, update.effective_user.first_name, update.effective_user.username)
    if arg == "2d" and not db.is_premium_active(user):
        return await msg.reply_text("❌ 2-day protection sirf premium users ke liye hai!", reply_to_message_id=msg.message_id)
    if db.is_protected(user):
        return await msg.reply_text(f"🛡 Aapki protection already active hai — {user['protection_until'].strftime('%Y-%m-%d') if user.get('protection_until') else 'N/A'} tak", reply_to_message_id=msg.message_id)
    days = 2 if arg == "2d" else 1
    until = datetime.utcnow() + timedelta(days=days)
    await db.update_user(update.effective_user.id, protection_until=until)
    await msg.reply_text(f"🛡 Protection active! {until.strftime('%Y-%m-%d')} tak aap safe ho.", reply_to_message_id=msg.message_id)


async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if is_group(update):
        return await msg.reply_text("❌ Daily reward sirf DM (private chat) mein mil sakta hai! Bot ko DM karo.", reply_to_message_id=msg.message_id)
    u = update.effective_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    now = datetime.utcnow()
    daily_last = user.get("daily_last")
    if daily_last and (now - daily_last).total_seconds() < 86400:
        next_time = daily_last + timedelta(hours=24)
        remaining = next_time - now
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return await msg.reply_text(f"⏰ Daily already liya hai! {hours}h {minutes}m mein wapas aao.", reply_to_message_id=msg.message_id)
    premium = db.is_premium_active(user)
    reward = DAILY_BALANCE_PREMIUM if premium else DAILY_BALANCE_NORMAL
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE game_users SET balance = balance + $1, daily_last = $2 WHERE telegram_id = $3",
            reward, now, u.id
        )
    badge = " ⭐ Premium" if premium else ""
    await msg.reply_text(
        f"🎁 Daily reward: *+${reward:,}*{badge}!\nKal dobara aana 🌊",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


# ── Ships ──────────────────────────────────────────────────────────────────────

async def cmd_newship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    name = " ".join(ctx.args).strip() if ctx.args else ""
    if not name:
        return await msg.reply_text("❌ Usage: /newship <ship name>", reply_to_message_id=msg.message_id)
    u = update.effective_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    if user.get("ship_id"):
        return await msg.reply_text("❌ Aap pehle se ek ship mein ho! /leaveship karo pehle.", reply_to_message_id=msg.message_id)
    existing = await db.get_ship_by_name(name)
    if existing:
        return await msg.reply_text("❌ Is naam ki ship pehle se exist karti hai!", reply_to_message_id=msg.message_id)
    code = await db.generate_unique_ship_code()
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO ships (name, code, captain_id) VALUES ($1, $2, $3) RETURNING id",
            name, code, u.id
        )
        ship_id = row["id"]
        await conn.execute("UPDATE game_users SET ship_id = $1 WHERE telegram_id = $2", ship_id, u.id)
        await conn.execute("INSERT INTO ship_members (ship_id, user_id, role) VALUES ($1, $2, 'captain')", ship_id, u.id)
    await msg.reply_text(
        f"⛵ Ship *{name}* created! Code: `{code}`\nShare link: https://t.me/{BOT_USERNAME}?start=join_{code}",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


async def cmd_joinship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    code = ctx.args[0].strip() if ctx.args else ""
    if not code or len(code) != 4 or not code.isdigit():
        return await msg.reply_text("❌ Usage: /joinship <4-digit code>\nExample: /joinship 1234", reply_to_message_id=msg.message_id)
    u = update.effective_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    if user.get("ship_id"):
        return await msg.reply_text("❌ Aap pehle se ek ship mein ho! /leaveship karo pehle.", reply_to_message_id=msg.message_id)
    ship = await db.get_ship_by_code(code)
    if not ship:
        return await msg.reply_text("❌ Ye code kisi ship ka nahi hai! Code dobara check karo.", reply_to_message_id=msg.message_id)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE game_users SET ship_id = $1 WHERE telegram_id = $2", ship["id"], u.id)
        await conn.execute("INSERT INTO ship_members (ship_id, user_id, role) VALUES ($1, $2, 'member')", ship["id"], u.id)
    bal = await db.get_ship_balance(ship["id"])
    members = await db.get_ship_member_count(ship["id"])
    await msg.reply_text(
        f"⚓ *{u.first_name}* joined ship *{ship['name']}* [{ship['code']}]!\n💰 Ship Balance: ${bal:,}\n👥 Members: {members}",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


async def cmd_leaveship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    if not user.get("ship_id"):
        return await update.message.reply_text("❌ Aap kisi ship mein nahi ho!", reply_to_message_id=update.message.message_id)
    ship = await db.get_ship_by_id(user["ship_id"])
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ship_members WHERE ship_id = $1 AND user_id = $2", user["ship_id"], u.id)
        await conn.execute("UPDATE game_users SET ship_id = NULL WHERE telegram_id = $1", u.id)
    await update.message.reply_text(f"✅ Aapne ship *{ship['name'] if ship else '?'}* leave kar di!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


async def cmd_ship(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    query = " ".join(ctx.args).strip() if ctx.args else ""
    if not query:
        u = update.effective_user
        user = await db.get_or_create_user(u.id, u.first_name, u.username)
        if not user.get("ship_id"):
            return await msg.reply_text("❌ Aap kisi ship mein nahi ho! /newship ya /joinship karo.", reply_to_message_id=msg.message_id)
        ship = await db.get_ship_by_id(user["ship_id"])
    elif query.isdigit() and len(query) == 4:
        ship = await db.get_ship_by_code(query)
    else:
        ship = await db.get_ship_by_name(query)
    if not ship:
        return await msg.reply_text("❌ Ship nahi mila!", reply_to_message_id=msg.message_id)
    bal = await db.get_ship_balance(ship["id"])
    members = await db.get_ship_member_count(ship["id"])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚓ Join Ship", callback_data=f"join_ship_{ship['id']}")]])
    await msg.reply_text(
        f"⛵ *{ship['name']}* [{ship['code']}]\n💰 Balance: ${bal:,}\n👥 Members: {members}",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb, reply_to_message_id=msg.message_id
    )


# ── Leaderboards ───────────────────────────────────────────────────────────────

async def cmd_toprich(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = await db.get_top_rich(10)
    text = "💰 *Top 10 Richest*\n\n"
    for i, u in enumerate(users, 1):
        prefix = "💓 " if db.is_premium_active(u) else "👤 "
        text += f"{i}. {prefix}{u['first_name']} — ${u['balance']:,}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


async def cmd_topkills(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = await db.get_top_killers(10)
    text = "⚔️ *Top 10 Killers*\n\n"
    for i, u in enumerate(users, 1):
        tag = db.get_kill_tag(u["kills"], i)
        text += f"{i}. {u['first_name']}{tag} — {u['kills']} kills\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


async def cmd_topbounty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = await db.get_top_bounty(10)
    text = "💸 *Top 10 Bounty*\n\n"
    for i, u in enumerate(users, 1):
        text += f"{i}. {u['first_name']} — ${u['bounty_amount']:,}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


async def cmd_topships(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ships = await db.get_top_ships(20)
    if not ships:
        return await update.message.reply_text("❌ Abhi koi ship nahi hai!", reply_to_message_id=update.message.message_id)
    text = "⛵ *Top 20 Ships*\n\n"
    for i, s in enumerate(ships, 1):
        text += f"{i}. *{s['name']}* [{s['code']}] — ${s['ship_balance']:,} ({s['member_count']} members)\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


# ── Items ──────────────────────────────────────────────────────────────────────

async def cmd_items(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = "🎒 *Available Items*\n\n"
    for item in ITEMS:
        text += f"{item['emoji']} *{item['name']}* — ${item['price']:,}\n"
    text += "\nUse /purchase <item name> to buy!"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


async def cmd_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        ru = msg.reply_to_message.from_user
        target = await db.get_or_create_user(ru.id, ru.first_name, ru.username)
        name = ru.first_name
    else:
        u = update.effective_user
        target = await db.get_or_create_user(u.id, u.first_name, u.username)
        name = u.first_name
    owned = await db.get_user_items(target["telegram_id"])
    if not owned:
        return await msg.reply_text(f"🎒 {name} ke paas koi item nahi hai!", reply_to_message_id=msg.message_id)
    item_strs = []
    for item in ITEMS:
        if item["name"] in owned:
            item_strs.append(f"{item['emoji']} {item['name']}")
    await msg.reply_text(f"🎒 *{name} ke items:*\n" + "\n".join(item_strs), parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_purchase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    item_name = " ".join(ctx.args).strip().lower() if ctx.args else ""
    if not item_name:
        return await msg.reply_text("❌ Usage: /purchase <item name>", reply_to_message_id=msg.message_id)
    item = next((i for i in ITEMS if i["name"] == item_name), None)
    if not item:
        return await msg.reply_text(f"❌ '{item_name}' naam ka koi item nahi hai! /items se list dekho.", reply_to_message_id=msg.message_id)
    u = update.effective_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    owned = await db.get_user_items(u.id)
    if item_name in owned:
        return await msg.reply_text(f"❌ Tumhare paas ye item pehle se hai!", reply_to_message_id=msg.message_id)
    if user["balance"] < item["price"]:
        return await msg.reply_text(f"❌ Tumhare paas itne paise nahi hain! Chahiye: ${item['price']:,}, Tumhare paas: ${user['balance']:,}", reply_to_message_id=msg.message_id)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE game_users SET balance = balance - $1 WHERE telegram_id = $2", item["price"], u.id)
        await conn.execute("INSERT INTO user_items (user_id, item_name) VALUES ($1, $2)", u.id, item_name)
    await msg.reply_text(f"✅ {item['emoji']} *{item_name}* khareed liya! ${item['price']:,} kharcha hua.", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_gift(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    item_name = " ".join(ctx.args).strip().lower() if ctx.args else ""
    if not item_name or not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Usage: /gift <item name> (reply to someone)", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    item = next((i for i in ITEMS if i["name"] == item_name), None)
    if not item:
        return await msg.reply_text(f"❌ '{item_name}' naam ka koi item nahi!", reply_to_message_id=msg.message_id)
    u = update.effective_user
    owned = await db.get_user_items(u.id)
    if item_name not in owned:
        return await msg.reply_text(f"❌ Tumhare paas ye item nahi hai!", reply_to_message_id=msg.message_id)
    target_owned = await db.get_user_items(target_user.id)
    if item_name in target_owned:
        return await msg.reply_text(f"❌ {target_user.first_name} ke paas ye item pehle se hai!", reply_to_message_id=msg.message_id)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM user_items WHERE user_id = $1 AND item_name = $2 AND id = (SELECT id FROM user_items WHERE user_id = $1 AND item_name = $2 LIMIT 1)", u.id, item_name)
        await conn.execute("INSERT INTO user_items (user_id, item_name) VALUES ($1, $2)", target_user.id, item_name)
    await msg.reply_text(f"🎁 {item['emoji']} *{item_name}* gift kar diya *{target_user.first_name}* ko!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


# ── Codes ──────────────────────────────────────────────────────────────────────

async def cmd_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    code = ctx.args[0].strip() if ctx.args else ""
    if not code:
        return await msg.reply_text("❌ Usage: /redeem <code>", reply_to_message_id=msg.message_id)
    amount = await db.redeem_balance_code(code)
    if amount is None:
        return await msg.reply_text("❌ Invalid ya already redeemed code!", reply_to_message_id=msg.message_id)
    u = update.effective_user
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE game_users SET balance = balance + $1 WHERE telegram_id = $2", amount, u.id)
    await msg.reply_text(f"✅ Code redeemed! *+${amount:,}* balance mila!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_redbounty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    code = ctx.args[0].strip() if ctx.args else ""
    if not code:
        return await msg.reply_text("❌ Usage: /redbounty <code>", reply_to_message_id=msg.message_id)
    amount = await db.redeem_bounty_code(code)
    if amount is None:
        return await msg.reply_text("❌ Invalid ya already redeemed code!", reply_to_message_id=msg.message_id)
    u = update.effective_user
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE game_users SET bounty_amount = bounty_amount + $1 WHERE telegram_id = $2", amount, u.id)
    await msg.reply_text(f"✅ Bounty code redeemed! *+${amount:,}* bounty mila!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


# ── Premium ────────────────────────────────────────────────────────────────────

async def cmd_pay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_group(update):
        return await update.message.reply_text("❌ /pay sirf DM mein kaam karta hai! Bot ko DM karo.", reply_to_message_id=update.message.message_id)
    await update.message.reply_text(
        "💎 *Premium Features:*\n\n"
        "• ⭐ Special badge\n"
        "• 💰 Higher daily: $5,000 (normal: $2,000)\n"
        "• ⚔️ Higher kill rewards: $700-800\n"
        "• 🛡 2-day protection (/protect 2d)\n"
        "• 💸 Unlimited rob amount\n"
        "• 🎯 Higher bounty per kill: $400\n\n"
        "Contact @light_speedy to get premium! 👑",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id
    )


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        ru = msg.reply_to_message.from_user
        target = await db.get_or_create_user(ru.id, ru.first_name, ru.username)
        name = ru.first_name
    else:
        u = update.effective_user
        target = await db.get_or_create_user(u.id, u.first_name, u.username)
        name = u.first_name
    premium_status = "✅ Active" if db.is_premium_active(target) else "❌ Inactive"
    protection_status = f"✅ Until {target['protection_until'].strftime('%Y-%m-%d')}" if db.is_protected(target) else "❌ No protection"
    await msg.reply_text(
        f"👤 *{name}*\n💎 Premium: {premium_status}\n🛡 Protection: {protection_status}",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


async def cmd_setemoji(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    emoji = " ".join(ctx.args).strip() if ctx.args else ""
    if not emoji:
        return await msg.reply_text("❌ Usage: /setemoji <emoji>", reply_to_message_id=msg.message_id)
    await db.update_user(update.effective_user.id, custom_emoji=emoji)
    await msg.reply_text(f"✅ Emoji set to: {emoji}", reply_to_message_id=msg.message_id)


# ── Ship roles ─────────────────────────────────────────────────────────────────

async def _appoint_role(update: Update, ctx: ContextTypes.DEFAULT_TYPE, role: str):
    msg = update.message
    u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Reply karo jise role dena hai!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    if not user.get("ship_id"):
        return await msg.reply_text("❌ Aap kisi ship mein nahi ho!", reply_to_message_id=msg.message_id)
    my_role = await db.get_ship_member_role(user["ship_id"], u.id)
    if my_role != "captain" and not is_owner(u.username):
        return await msg.reply_text("❌ Sirf captain roles appoint kar sakta hai!", reply_to_message_id=msg.message_id)
    target_role = await db.get_ship_member_role(user["ship_id"], target_user.id)
    if not target_role:
        return await msg.reply_text("❌ Ye banda aapki ship mein nahi hai!", reply_to_message_id=msg.message_id)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ship_members SET role = $1 WHERE ship_id = $2 AND user_id = $3", role, user["ship_id"], target_user.id)
    await msg.reply_text(f"✅ *{target_user.first_name}* is now *{role.replace('_', ' ').title()}*!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_appointvicecaptain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _appoint_role(update, ctx, "vice_captain")


async def cmd_appointnavigator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _appoint_role(update, ctx, "navigator")


async def cmd_appointofficer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _appoint_role(update, ctx, "officer")


async def cmd_transferleadership(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Reply karo jise captain banana hai!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    user = await db.get_or_create_user(u.id, u.first_name, u.username)
    if not user.get("ship_id"):
        return await msg.reply_text("❌ Aap kisi ship mein nahi ho!", reply_to_message_id=msg.message_id)
    my_role = await db.get_ship_member_role(user["ship_id"], u.id)
    if my_role != "captain":
        return await msg.reply_text("❌ Sirf captain leadership transfer kar sakta hai!", reply_to_message_id=msg.message_id)
    target_role = await db.get_ship_member_role(user["ship_id"], target_user.id)
    if not target_role:
        return await msg.reply_text("❌ Ye banda aapki ship mein nahi hai!", reply_to_message_id=msg.message_id)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ship_members SET role = 'member' WHERE ship_id = $1 AND user_id = $2", user["ship_id"], u.id)
        await conn.execute("UPDATE ship_members SET role = 'captain' WHERE ship_id = $1 AND user_id = $2", user["ship_id"], target_user.id)
        await conn.execute("UPDATE ships SET captain_id = $1 WHERE id = $2", target_user.id, user["ship_id"])
    await msg.reply_text(f"⚓ Leadership transferred! *{target_user.first_name}* is the new Captain!", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


# ── Admin Commands ─────────────────────────────────────────────────────────────

async def cmd_givepremium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_owner(update.effective_user.username):
        return await msg.reply_text("❌ Owner only command!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Usage: /givepremium <days> (reply to user)", reply_to_message_id=msg.message_id)
    if not ctx.args or not ctx.args[0].isdigit():
        return await msg.reply_text("❌ Usage: /givepremium <days> (reply to user)", reply_to_message_id=msg.message_id)
    days = int(ctx.args[0])
    target_user = msg.reply_to_message.from_user
    expires = datetime.utcnow() + timedelta(days=days)
    await db.update_user(target_user.id, premium=True, premium_expires=expires)
    await msg.reply_text(f"✅ *{target_user.first_name}* ko {days} day premium diya gaya! (Until {expires.strftime('%Y-%m-%d')})", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_cancelpremium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_owner(update.effective_user.username):
        return await msg.reply_text("❌ Owner only command!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Reply karo jiska premium cancel karna hai!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    await db.update_user(target_user.id, premium=False, premium_expires=None)
    await msg.reply_text(f"✅ *{target_user.first_name}* ka premium cancel kiya gaya.", parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id)


async def cmd_setbal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_owner(update.effective_user.username):
        return await msg.reply_text("❌ Owner only command!", reply_to_message_id=msg.message_id)
    if not ctx.args or not ctx.args[0].lstrip("-").isdigit():
        return await msg.reply_text("❌ Usage: /setbal <amount>", reply_to_message_id=msg.message_id)
    amount = int(ctx.args[0])
    await db.update_user(update.effective_user.id, balance=amount)
    await msg.reply_text(f"✅ Balance set to ${amount:,}", reply_to_message_id=msg.message_id)


async def cmd_gen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_owner(update.effective_user.username):
        return await msg.reply_text("❌ Owner only command!", reply_to_message_id=msg.message_id)
    if not ctx.args or not ctx.args[0].isdigit():
        return await msg.reply_text("❌ Usage: /gen <amount>", reply_to_message_id=msg.message_id)
    amount = int(ctx.args[0])
    if amount <= 0:
        return await msg.reply_text("❌ Usage: /gen <amount>", reply_to_message_id=msg.message_id)
    code = await db.generate_balance_code(amount)
    await msg.reply_text(
        f"✅ Balance code generated:\n`{code}`\n\nAmount: ${amount:,}\nUse: /redeem {code}",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


async def cmd_bounty_gen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_owner(update.effective_user.username):
        return await msg.reply_text("❌ Owner only command!", reply_to_message_id=msg.message_id)
    if not ctx.args or not ctx.args[0].isdigit():
        return await msg.reply_text("❌ Usage: /bounty <amount>", reply_to_message_id=msg.message_id)
    amount = int(ctx.args[0])
    code = await db.generate_bounty_code(amount)
    await msg.reply_text(
        f"✅ Bounty code generated:\n`{code}`\n\nAmount: ${amount:,}\nUse: /redbounty {code}",
        parse_mode=ParseMode.MARKDOWN, reply_to_message_id=msg.message_id
    )


# ── Group Management ───────────────────────────────────────────────────────────

PROMOTE_RIGHTS = {
    1: dict(can_manage_chat=True, can_change_info=True, can_delete_messages=True,
            can_manage_video_chats=True, can_invite_users=True, can_pin_messages=True,
            can_restrict_members=False, can_promote_members=False, can_be_anonymous=False),
    2: dict(can_manage_chat=True, can_change_info=True, can_delete_messages=True,
            can_manage_video_chats=True, can_invite_users=True, can_pin_messages=True,
            can_restrict_members=True, can_promote_members=False, can_be_anonymous=False),
    3: dict(can_manage_chat=True, can_change_info=True, can_delete_messages=True,
            can_manage_video_chats=True, can_invite_users=True, can_pin_messages=True,
            can_restrict_members=True, can_promote_members=True, can_be_anonymous=False),
}
PROMOTE_MSG = {1: "⭐ Level 1 Promoted", 2: "🌟 Level 2 Promoted", 3: "👑 Promoted Full Rights"}


async def _check_group_perm(update: Update, perm: str) -> bool:
    if not is_group(update):
        return False
    if is_owner(update.effective_user.username):
        return True
    try:
        member = await update.effective_chat.get_member(update.effective_user.id)
        if member.status == "creator":
            return True
        if member.status == "administrator":
            if perm == "promote":
                return getattr(member, "can_promote_members", False)
            if perm == "restrict":
                return getattr(member, "can_restrict_members", False)
            if perm == "pin":
                return getattr(member, "can_pin_messages", False)
    except Exception:
        pass
    return False


async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "promote"):
        return await msg.reply_text("❌ Tumhare paas promote karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko promote karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    if not ctx.args or not ctx.args[0].isdigit() or int(ctx.args[0]) not in (1, 2, 3):
        return await msg.reply_text("❌ Level 1, 2, ya 3 dalo!\nExample: /promote 2 (reply karke)", reply_to_message_id=msg.message_id)
    level = int(ctx.args[0])
    target_user = msg.reply_to_message.from_user
    try:
        await update.effective_chat.promote_member(target_user.id, **PROMOTE_RIGHTS[level])
        await msg.reply_text(f"✅ <b>{target_user.first_name}</b> — {PROMOTE_MSG[level]}", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Promote nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


async def cmd_demote(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "promote"):
        return await msg.reply_text("❌ Tumhare paas demote karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko demote karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    try:
        await update.effective_chat.promote_member(
            target_user.id,
            can_manage_chat=False, can_change_info=False, can_delete_messages=False,
            can_manage_video_chats=False, can_invite_users=False, can_pin_messages=False,
            can_restrict_members=False, can_promote_members=False, can_be_anonymous=False
        )
        await msg.reply_text(f"⬇️ <b>{target_user.first_name}</b> ko demote kar diya gaya!", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Demote nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


async def cmd_pin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "pin"):
        return await msg.reply_text("❌ Tumhare paas pin karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message:
        return await msg.reply_text("❌ Jo message pin karna hai usse reply karo!", reply_to_message_id=msg.message_id)
    try:
        await update.effective_chat.pin_message(msg.reply_to_message.message_id)
        await msg.reply_text("📌 Message pin ho gaya!", reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Pin nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


async def cmd_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "restrict"):
        return await msg.reply_text("❌ Tumhare paas warn karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko warn karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    if is_owner(target_user.username):
        return await msg.reply_text("❌ Bot owner ko warn nahi kar sakte!", reply_to_message_id=msg.message_id)
    group_id = update.effective_chat.id
    warn_count = await db.add_warn(group_id, target_user.id)
    if warn_count >= 5:
        try:
            await update.effective_chat.ban_member(target_user.id)
            await db.reset_warns(group_id, target_user.id)
            await msg.reply_text(f"🔨 <b>{target_user.first_name}</b> ko 5/5 warns ke baad <b>ban</b> kar diya gaya!", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
        except TelegramError as e:
            await msg.reply_text(f"⚠️ 5/5 warns! Ban failed: {e.message}", reply_to_message_id=msg.message_id)
    else:
        await msg.reply_text(
            f"⚠️ <b>{target_user.first_name}</b> ko warn mila!\nWarns: <b>{warn_count}/5</b> — {5 - warn_count} aur milenge toh ban!",
            parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id
        )


async def cmd_unwarn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "restrict"):
        return await msg.reply_text("❌ Tumhare paas unwarn karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko unwarn karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    warn_count = await db.remove_warn(update.effective_chat.id, target_user.id)
    await msg.reply_text(f"✅ <b>{target_user.first_name}</b> ka ek warn hata diya! Ab warns: <b>{warn_count}/5</b>", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)


async def cmd_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "restrict"):
        return await msg.reply_text("❌ Tumhare paas mute karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko mute karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    if is_owner(target_user.username):
        return await msg.reply_text("❌ Bot owner ko mute nahi kar sakte!", reply_to_message_id=msg.message_id)
    try:
        await update.effective_chat.restrict_member(target_user.id, ChatPermissions())
        await msg.reply_text(f"🔇 <b>{target_user.first_name}</b> muted! /unmute se wapas de sakte ho.", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Mute nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


async def cmd_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "restrict"):
        return await msg.reply_text("❌ Tumhare paas unmute karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko unmute karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    try:
        await update.effective_chat.restrict_member(
            target_user.id,
            ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                can_add_web_page_previews=True, can_invite_users=True,
            )
        )
        await msg.reply_text(f"🔊 <b>{target_user.first_name}</b> unmuted!", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Unmute nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not await _check_group_perm(update, "restrict"):
        return await msg.reply_text("❌ Tumhare paas kick karne ke rights nahi hain!", reply_to_message_id=msg.message_id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("❌ Jis bande ko kick karna hai uske message ko reply karo!", reply_to_message_id=msg.message_id)
    target_user = msg.reply_to_message.from_user
    if is_owner(target_user.username):
        return await msg.reply_text("❌ Bot owner ko kick nahi kar sakte!", reply_to_message_id=msg.message_id)
    try:
        await update.effective_chat.ban_member(target_user.id)
        await update.effective_chat.unban_member(target_user.id)
        await msg.reply_text(f"👟 <b>{target_user.first_name}</b> kick ho gaya! (Wapas join kar sakta hai)", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Kick nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


async def cmd_promoteme(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not is_group(update):
        return await msg.reply_text("❌ Ye command sirf groups mein kaam karta hai.")
    if not is_owner(update.effective_user.username):
        return
    if not ctx.args or not ctx.args[0].isdigit() or int(ctx.args[0]) not in (1, 2, 3):
        return await msg.reply_text("❌ Level 1, 2, ya 3 dalo! Example: /promoteme 3", reply_to_message_id=msg.message_id)
    level = int(ctx.args[0])
    try:
        await update.effective_chat.promote_member(update.effective_user.id, **PROMOTE_RIGHTS[level])
        await msg.reply_text(f"✅ Khud ko promote kar liya — {PROMOTE_MSG[level]} 👑", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Promote nahi ho saka: {e.message}", reply_to_message_id=msg.message_id)


# ── Help ───────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 *Nami Bot — Command List*

*👤 Profile*
/bal — Balance & stats check
/daily — Daily $2000 reward (DM only)
/select — Job select karo (Bounty Hunter / Pirate)
/leavejob — Current job leave karo

*⚔️ Combat*
/kill — Kill someone (reply)
/rob <amount> — Rob someone (reply)
/protect 1d/2d — Protection (2d = premium)

*🏆 Leaderboards*
/toprich — Top 10 richest
/topkills — Top 10 killers
/topbounty — Top 10 bounty
/topships — Top 20 ships

*🎒 Items*
/items — View available items
/item — Check someone's items (reply)
/purchase <item name> — Buy item
/gift <item name> — Gift item (reply)

*⛵ Ships*
/newship <name> — Create ship
/joinship <code> — Join ship by code
/ship <code/name> — Ship info
/leaveship — Leave your ship
/appointvicecaptain — Appoint vice captain (reply)
/appointnavigator — Appoint navigator (reply)
/appointofficer — Appoint officer (reply)
/transferleadership — Transfer captain (reply)

*💰 Codes*
/redeem <code> — Redeem balance code
/redbounty <code> — Redeem bounty code

*💎 Premium*
/pay — Buy premium (DM only)
/check — Check protection/premium status
/setemoji <emoji> — Set custom emoji

*🛡 Group Management*
/promote 1/2/3 — Promote user (reply) [admin]
/demote — Demote user (reply) [admin]
/pin — Pin message (reply) [admin]
/warn — Warn user, 5 warns = ban (reply) [admin]
/unwarn — Remove a warn (reply) [admin]
/mute — Mute user (reply) [admin]
/unmute — Unmute user (reply) [admin]
/kick — Kick user (reply) [admin]
/promoteme 1/2/3 — Self promote [owner only]

*👑 Owner Only*
/givepremium <days> — Give premium (reply)
/cancelpremium — Cancel premium (reply)
/setbal <amount> — Set balance
/gen <amount> — Generate balance code
/bounty <amount> — Generate bounty code
""".strip()
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)


# ── Media handlers ─────────────────────────────────────────────────────────────

async def handle_sticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_group(update) and not should_respond_in_group(update):
        return
    sticker = get_random_sticker()
    if sticker:
        await update.message.reply_sticker(sticker, reply_to_message_id=update.message.message_id)
    else:
        await update.message.reply_text("😄", reply_to_message_id=update.message.message_id)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_group(update) and not should_respond_in_group(update):
        return
    replies = ["Wow kya photo hai! 😍", "Nice pic! 🔥", "Sahi hai yaar! 😄", "Waah waah! 👌"]
    await update.message.reply_text(random.choice(replies), reply_to_message_id=update.message.message_id)


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_group(update) and not should_respond_in_group(update):
        return
    replies = ["Bhai voice message mat bhejo 😭", "Sunne ka mann nahi 😜", "Text kar yaar 😂"]
    await update.message.reply_text(random.choice(replies), reply_to_message_id=update.message.message_id)


# ── AI text handler ────────────────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_group(update) and not should_respond_in_group(update):
        return
    msg = update.message
    text = msg.text or ""
    if not text:
        return

    user_id = update.effective_user.id
    history = conv_history[user_id]
    history.append({"role": "user", "content": text})
    if len(history) > MAX_HISTORY:
        del history[:len(history) - MAX_HISTORY]

    try:
        await update.effective_chat.send_action("typing")
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_completion_tokens=400,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        )
        reply = response.choices[0].message.content
        if not reply:
            return
        history.append({"role": "assistant", "content": reply})
        await msg.reply_text(reply, reply_to_message_id=msg.message_id)
    except Exception as e:
        logger.error(f"AI error: {e}")
        await msg.reply_text("Thodi si problem aa gayi, ek second ruko! 😬", reply_to_message_id=msg.message_id)


# ── Bot setup ──────────────────────────────────────────────────────────────────

async def post_init(app: Application):
    await db.init_db()
    await load_sticker_packs(app)
    logger.info("Nami bot ready!")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("bal", cmd_bal))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CommandHandler("rob", cmd_rob))
    app.add_handler(CommandHandler("protect", cmd_protect))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("select", cmd_select))
    app.add_handler(CommandHandler("leavejob", cmd_leavejob))
    app.add_handler(CommandHandler("newship", cmd_newship))
    app.add_handler(CommandHandler("joinship", cmd_joinship))
    app.add_handler(CommandHandler("leaveship", cmd_leaveship))
    app.add_handler(CommandHandler("ship", cmd_ship))
    app.add_handler(CommandHandler("toprich", cmd_toprich))
    app.add_handler(CommandHandler("topkills", cmd_topkills))
    app.add_handler(CommandHandler("topbounty", cmd_topbounty))
    app.add_handler(CommandHandler("topships", cmd_topships))
    app.add_handler(CommandHandler("items", cmd_items))
    app.add_handler(CommandHandler("item", cmd_item))
    app.add_handler(CommandHandler("purchase", cmd_purchase))
    app.add_handler(CommandHandler("gift", cmd_gift))
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("redbounty", cmd_redbounty))
    app.add_handler(CommandHandler("pay", cmd_pay))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("setemoji", cmd_setemoji))
    app.add_handler(CommandHandler("appointvicecaptain", cmd_appointvicecaptain))
    app.add_handler(CommandHandler("appointnavigator", cmd_appointnavigator))
    app.add_handler(CommandHandler("appointofficer", cmd_appointofficer))
    app.add_handler(CommandHandler("transferleadership", cmd_transferleadership))
    app.add_handler(CommandHandler("givepremium", cmd_givepremium))
    app.add_handler(CommandHandler("cancelpremium", cmd_cancelpremium))
    app.add_handler(CommandHandler("setbal", cmd_setbal))
    app.add_handler(CommandHandler("gen", cmd_gen))
    app.add_handler(CommandHandler("bounty", cmd_bounty_gen))
    app.add_handler(CommandHandler("promote", cmd_promote))
    app.add_handler(CommandHandler("demote", cmd_demote))
    app.add_handler(CommandHandler("pin", cmd_pin))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("unwarn", cmd_unwarn))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("promoteme", cmd_promoteme))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting Nami bot (long polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
