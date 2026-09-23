import os
import sqlite3
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL = os.getenv("CHANNEL_USERNAME", "@xpoallkanda").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MIN_WITHDRAW = float(os.getenv("MIN_WITHDRAW", "10"))
REFERRAL_REWARD = float(os.getenv("REFERRAL_REWARD", "0.01"))
DB = "referrals.db"
BANNER = Path("banner.png")

ASK_AMOUNT, ASK_NETWORK, ASK_WALLET, CONFIRM_WITHDRAW = range(4)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            referrer INTEGER,
            referrals INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            joined INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            network TEXT,
            wallet TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def get_user(uid):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return row


def add_user(uid, username, referrer=None):
    conn = db()
    row = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        if referrer == uid:
            referrer = None
        conn.execute(
            "INSERT INTO users (id, username, referrer) VALUES (?, ?, ?)",
            (uid, username or "", referrer),
        )
    else:
        conn.execute("UPDATE users SET username=? WHERE id=?", (username or "", uid))
    conn.commit()
    conn.close()


def set_joined(uid, value):
    conn = db()
    conn.execute("UPDATE users SET joined=? WHERE id=?", (int(bool(value)), uid))
    conn.commit()
    conn.close()


def mark_joined_and_reward(uid):
    conn = db()
    row = conn.execute(
        "SELECT joined, referrer FROM users WHERE id=?", (uid,)
    ).fetchone()
    if not row or int(row["joined"]) == 1:
        conn.close()
        return False

    conn.execute("UPDATE users SET joined=1 WHERE id=?", (uid,))
    referrer = row["referrer"]
    if referrer and referrer != uid:
        exists = conn.execute("SELECT id FROM users WHERE id=?", (referrer,)).fetchone()
        if exists:
            conn.execute(
                "UPDATE users SET referrals=referrals+1, balance=balance+? WHERE id=?",
                (REFERRAL_REWARD, referrer),
            )
    conn.commit()
    conn.close()
    return True


def referral_link(uid, bot_username):
    return f"https://t.me/{bot_username}?start={uid}"


async def is_member(context, uid):
    try:
        member = await context.bot.get_chat_member(CHANNEL, uid)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception as exc:
        log.warning("Membership check failed: %s", exc)
        return False


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Referral", callback_data="menu_ref"),
         InlineKeyboardButton("💰 Balance", callback_data="menu_bal")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="menu_withdraw"),
         InlineKeyboardButton("📊 My Stats", callback_data="menu_stats")],
        [InlineKeyboardButton("📜 History", callback_data="menu_history"),
         InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")],
    ])


def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join XPO Channel", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton("✅ Verify Join", callback_data="verify")],
    ])


def network_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("TRC20", callback_data="net_TRC20"),
         InlineKeyboardButton("BEP20", callback_data="net_BEP20")],
        [InlineKeyboardButton("ERC20", callback_data="net_ERC20"),
         InlineKeyboardButton("TON", callback_data="net_TON")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdraw")],
    ])


def confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_withdraw"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdraw")],
    ])


def admin_withdraw_keyboard(wid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Paid", callback_data=f"admin_paid_{wid}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{wid}")],
    ])


async def send_welcome(update, context, text):
    if update.message:
        if BANNER.exists():
            with BANNER.open("rb") as photo:
                await update.message.reply_photo(photo=photo, caption=text, reply_markup=main_keyboard())
        else:
            await update.message.reply_text(text, reply_markup=main_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    referrer = None
    if context.args:
        try:
            referrer = int(context.args[0])
        except (ValueError, TypeError):
            pass

    add_user(uid, update.effective_user.username, referrer)

    if not await is_member(context, uid):
        set_joined(uid, False)
        await update.message.reply_text(
            "👋 Welcome to XPO Referral Bot!\n\n"
            "1️⃣ Join our XPO channel\n"
            "2️⃣ Tap Verify Join\n\n"
            f"🎁 Earn {REFERRAL_REWARD:.2f} USDT per successful referral.\n"
            f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT",
            reply_markup=join_keyboard(),
        )
        return

    mark_joined_and_reward(uid)
    await send_welcome(
        update,
        context,
        "🎉 Welcome to XPO Referral Bot!\n\n"
        f"🎁 Earn {REFERRAL_REWARD:.2f} USDT per successful referral.\n"
        f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT\n\n"
        "Invite friends, earn rewards and request withdrawals."
    )


async def verify(update, context):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    uid = q.from_user.id
    if await is_member(context, uid):
        mark_joined_and_reward(uid)
        await q.edit_message_text(
            "✅ Verification successful!\n\nChoose an option below:",
            reply_markup=main_keyboard(),
        )
    else:
        await q.edit_message_text(
            "❌ Channel join not detected.\n\nJoin @xpoallkanda first, then tap Verify Join.",
            reply_markup=join_keyboard(),
        )


async def referral_text(update, context):
    uid = update.effective_user.id
    add_user(uid, update.effective_user.username)
    if not await is_member(context, uid):
        await update.message.reply_text("❌ Join @xpoallkanda first.", reply_markup=join_keyboard())
        return
    mark_joined_and_reward(uid)
    row = get_user(uid)
    me = await context.bot.get_me()
    await update.message.reply_text(
        f"👥 Successful referrals: {row['referrals']}\n"
        f"💰 Balance: {row['balance']:.2f} USDT\n\n"
        f"🎁 Per successful referral: {REFERRAL_REWARD:.2f} USDT\n"
        f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT\n\n"
        f"🔗 Your referral link:\n{referral_link(uid, me.username)}\n\n"
        "Share your link. A referral is counted after the new user joins the channel and verifies.",
        reply_markup=main_keyboard(),
    )


async def balance_text(update, context):
    uid = update.effective_user.id
    row = get_user(uid)
    if not row:
        await update.message.reply_text("Use /start first.")
        return
    await update.message.reply_text(
        f"💰 Balance: {row['balance']:.2f} USDT\n"
        f"👥 Successful referrals: {row['referrals']}\n"
        f"🎁 Per referral: {REFERRAL_REWARD:.2f} USDT\n"
        f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT",
        reply_markup=main_keyboard(),
    )


async def stats_text(update, context):
    uid = update.effective_user.id
    row = get_user(uid)
    if not row:
        await update.message.reply_text("Use /start first.")
        return
    needed = max(0, int((MIN_WITHDRAW / REFERRAL_REWARD) - row['referrals'])) if REFERRAL_REWARD else 0
    await update.message.reply_text(
        f"📊 My Stats\n\n"
        f"👥 Successful referrals: {row['referrals']}\n"
        f"💰 Balance: {row['balance']:.2f} USDT\n"
        f"🎁 Per referral: {REFERRAL_REWARD:.2f} USDT\n"
        f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT\n"
        f"📌 More referrals needed at current rate: {needed}",
        reply_markup=main_keyboard(),
    )


async def history_text(update, context):
    uid = update.effective_user.id
    conn = db()
    rows = conn.execute(
        "SELECT id, amount, network, wallet, status, created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (uid,),
    ).fetchall()
    conn.close()
    if not rows:
        text = "📜 Withdrawal History\n\nNo withdrawals yet."
    else:
        lines = ["📜 Withdrawal History", ""]
        for r in rows:
            lines.append(f"#{r['id']} • {r['amount']:.2f} USDT • {r['network']} • {r['status'].upper()}")
        text = "\n".join(lines)
    if update.message:
        await update.message.reply_text(text, reply_markup=main_keyboard())


async def help_text(update, context):
    text = (
        "ℹ️ XPO Referral Bot\n\n"
        "/start - Start / verify\n"
        "/referral - Referral link and earnings\n"
        "/balance - Balance\n"
        "/stats - Statistics\n"
        "/withdraw - Request withdrawal\n"
        "/history - Withdrawal history\n"
        "/help - Help\n\n"
        f"🎁 Reward: {REFERRAL_REWARD:.2f} USDT per successful referral\n"
        f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT\n\n"
        "Withdrawals are reviewed and paid manually by the admin."
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_keyboard())


async def withdraw_start(update, context):
    uid = update.effective_user.id
    row = get_user(uid)
    if not row:
        await update.message.reply_text("Use /start first.")
        return ConversationHandler.END
    if row['balance'] < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimum withdrawal is {MIN_WITHDRAW:.2f} USDT.\n"
            f"💰 Your balance: {row['balance']:.2f} USDT\n\n"
            "Keep inviting friends to increase your balance.",
            reply_markup=main_keyboard(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"💸 Withdrawal\n\nYour balance: {row['balance']:.2f} USDT\n"
        f"Minimum: {MIN_WITHDRAW:.2f} USDT\n\n"
        "Enter the amount you want to withdraw:",
    )
    return ASK_AMOUNT


async def withdraw_amount(update, context):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number, e.g. 10")
        return ASK_AMOUNT
    row = get_user(update.effective_user.id)
    if amount < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Minimum withdrawal is {MIN_WITHDRAW:.2f} USDT.")
        return ASK_AMOUNT
    if amount > row['balance']:
        await update.message.reply_text(f"❌ Your balance is only {row['balance']:.2f} USDT.")
        return ASK_AMOUNT
    context.user_data['withdraw_amount'] = amount
    await update.message.reply_text("🌐 Select your USDT network:", reply_markup=network_keyboard())
    return ASK_NETWORK


async def withdraw_network(update, context):
    q = update.callback_query
    await q.answer()
    network = q.data.replace("net_", "")
    context.user_data['withdraw_network'] = network
    await q.edit_message_text(f"🌐 Network: {network}\n\nSend your USDT wallet address:")
    return ASK_WALLET


async def withdraw_wallet(update, context):
    wallet = update.message.text.strip()
    if len(wallet) < 10:
        await update.message.reply_text("❌ Wallet address looks too short. Send the correct address.")
        return ASK_WALLET
    context.user_data['withdraw_wallet'] = wallet
    amount = context.user_data['withdraw_amount']
    network = context.user_data['withdraw_network']
    await update.message.reply_text(
        "⚠️ Confirm Withdrawal\n\n"
        f"💰 Amount: {amount:.2f} USDT\n"
        f"🌐 Network: {network}\n"
        f"🏦 Wallet: {wallet}\n\n"
        "Make sure the network and address are correct.",
        reply_markup=confirm_keyboard(),
    )
    return CONFIRM_WITHDRAW


async def confirm_withdraw(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    row = get_user(uid)
    amount = float(context.user_data.get('withdraw_amount', 0))
    network = context.user_data.get('withdraw_network', '')
    wallet = context.user_data.get('withdraw_wallet', '')
    if not row or not amount or not network or not wallet:
        await q.edit_message_text("❌ Withdrawal session expired. Please use /withdraw again.")
        return ConversationHandler.END
    if amount < MIN_WITHDRAW or amount > row['balance']:
        await q.edit_message_text("❌ Balance changed. Please start /withdraw again.")
        return ConversationHandler.END

    conn = db()
    cur = conn.execute(
        "INSERT INTO withdrawals (user_id, amount, network, wallet, status) VALUES (?, ?, ?, ?, 'pending')",
        (uid, amount, network, wallet),
    )
    wid = cur.lastrowid
    conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))
    conn.commit()
    conn.close()

    await q.edit_message_text(
        f"✅ Withdrawal #{wid} submitted!\n\n"
        f"💰 {amount:.2f} USDT\n🌐 {network}\n\n"
        "Admin will review and process the payment manually."
    )

    if ADMIN_ID:
        try:
            username = q.from_user.username or "No username"
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 NEW WITHDRAWAL #{wid}\n\n"
                f"👤 User: @{username}\n"
                f"🆔 ID: {uid}\n"
                f"💰 Amount: {amount:.2f} USDT\n"
                f"🌐 Network: {network}\n"
                f"🏦 Wallet: {wallet}\n\n"
                "Send the payment manually, then tap Paid.",
                reply_markup=admin_withdraw_keyboard(wid),
            )
        except Exception as exc:
            log.warning("Admin notification failed: %s", exc)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_withdraw(update, context):
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("❌ Withdrawal cancelled.", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("❌ Withdrawal cancelled.", reply_markup=main_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


async def admin_withdraw_action(update, context):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.answer("Not authorized.", show_alert=True)
        return
    parts = q.data.split("_")
    action = parts[1]
    wid = int(parts[2])

    conn = db()
    w = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if not w:
        conn.close()
        await q.edit_message_text("❌ Withdrawal not found.")
        return
    if w['status'] != 'pending':
        conn.close()
        await q.edit_message_text(f"ℹ️ Withdrawal #{wid} is already {w['status']}.")
        return

    if action == "paid":
        conn.execute("UPDATE withdrawals SET status='paid' WHERE id=?", (wid,))
        conn.commit()
        conn.close()
        await q.edit_message_text(f"✅ Withdrawal #{wid} marked as PAID.")
        try:
            await context.bot.send_message(w['user_id'], f"✅ Withdrawal #{wid} completed.\n💰 {w['amount']:.2f} USDT was marked as paid.")
        except Exception:
            pass
    else:
        conn.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (w['amount'], w['user_id']))
        conn.commit()
        conn.close()
        await q.edit_message_text(f"❌ Withdrawal #{wid} rejected. Balance refunded.")
        try:
            await context.bot.send_message(w['user_id'], f"❌ Withdrawal #{wid} was rejected.\n💰 {w['amount']:.2f} USDT returned to your balance.")
        except Exception:
            pass


async def menu_callback(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if q.data == "menu_ref":
        row = get_user(uid)
        me = await context.bot.get_me()
        await q.message.reply_text(
            f"👥 Successful referrals: {row['referrals'] if row else 0}\n"
            f"💰 Balance: {row['balance'] if row else 0:.2f} USDT\n\n"
            f"🎁 Per successful referral: {REFERRAL_REWARD:.2f} USDT\n"
            f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT\n\n"
            f"🔗 Your referral link:\n{referral_link(uid, me.username)}",
            reply_markup=main_keyboard(),
        )
    elif q.data == "menu_bal":
        row = get_user(uid)
        await q.message.reply_text(
            f"💰 Balance: {row['balance'] if row else 0:.2f} USDT\n"
            f"👥 Successful referrals: {row['referrals'] if row else 0}\n"
            f"💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT",
            reply_markup=main_keyboard(),
        )
    elif q.data == "menu_stats":
        row = get_user(uid)
        await q.message.reply_text(
            f"📊 My Stats\n\n👥 Referrals: {row['referrals'] if row else 0}\n💰 Balance: {row['balance'] if row else 0:.2f} USDT\n🎁 Per referral: {REFERRAL_REWARD:.2f} USDT\n💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT",
            reply_markup=main_keyboard(),
        )
    elif q.data == "menu_history":
        rows = db().execute("SELECT id, amount, network, status FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
        if rows:
            text = "📜 Withdrawal History\n\n" + "\n".join(f"#{r['id']} • {r['amount']:.2f} USDT • {r['network']} • {r['status'].upper()}" for r in rows)
        else:
            text = "📜 Withdrawal History\n\nNo withdrawals yet."
        await q.message.reply_text(text, reply_markup=main_keyboard())
    elif q.data == "menu_help":
        await q.message.reply_text(
            f"ℹ️ Commands\n\n/start\n/referral\n/balance\n/stats\n/withdraw\n/history\n/help\n\n🎁 {REFERRAL_REWARD:.2f} USDT per successful referral\n💸 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT",
            reply_markup=main_keyboard(),
        )
    elif q.data == "menu_withdraw":
        # Reuse withdrawal conversation by showing the same prompt; user can then type /withdraw.
        row = get_user(uid)
        if not row or row['balance'] < MIN_WITHDRAW:
            await q.message.reply_text(f"❌ Minimum withdrawal is {MIN_WITHDRAW:.2f} USDT.\n💰 Your balance: {row['balance'] if row else 0:.2f} USDT")
        else:
            await q.message.reply_text("💸 To start a withdrawal, send /withdraw.")


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Start / verify"),
        BotCommand("referral", "Get referral link"),
        BotCommand("balance", "Check balance"),
        BotCommand("stats", "View statistics"),
        BotCommand("withdraw", "Request withdrawal"),
        BotCommand("history", "Withdrawal history"),
        BotCommand("help", "Help"),
    ])


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN environment variable is missing.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("referral", referral_text))
    app.add_handler(CommandHandler("balance", balance_text))
    app.add_handler(CommandHandler("stats", stats_text))
    app.add_handler(CommandHandler("history", history_text))
    app.add_handler(CommandHandler("help", help_text))

    withdraw_conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw_start)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            ASK_NETWORK: [CallbackQueryHandler(withdraw_network, pattern=r"^net_")],
            ASK_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_wallet)],
            CONFIRM_WITHDRAW: [CallbackQueryHandler(confirm_withdraw, pattern=r"^confirm_withdraw$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_withdraw, pattern=r"^cancel_withdraw$"), CommandHandler("cancel", cancel_withdraw)],
        allow_reentry=True,
    )
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(verify, pattern=r"^verify$"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu_"))
    app.add_handler(CallbackQueryHandler(withdraw_network, pattern=r"^net_"))
    app.add_handler(CallbackQueryHandler(cancel_withdraw, pattern=r"^cancel_withdraw$"))
    app.add_handler(CallbackQueryHandler(admin_withdraw_action, pattern=r"^admin_(paid|reject)_\d+$"))

    app.run_polling()


if __name__ == "__main__":
    main()
