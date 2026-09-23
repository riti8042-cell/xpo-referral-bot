import os
import sqlite3
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL = os.getenv("CHANNEL_USERNAME", "@xpoallkanda").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MIN_WITHDRAW = float(os.getenv("MIN_WITHDRAW", "10"))
REFERRAL_REWARD = float(os.getenv("REFERRAL_REWARD", "0.01"))

DB = "referrals.db"

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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            referrer INTEGER,
            referrals INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            joined INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            method TEXT,
            details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


def get_user(uid):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    return row


def add_user(uid, username, referrer=None):
    """
    Creates the user if they do not exist.
    The referral reward is NOT given here.
    Reward is given only after the referred user is verified as a channel member.
    """
    conn = db()

    row = conn.execute(
        "SELECT id FROM users WHERE id = ?", (uid,)
    ).fetchone()

    if not row:
        if referrer == uid:
            referrer = None

        conn.execute(
            """
            INSERT INTO users (id, username, referrer)
            VALUES (?, ?, ?)
            """,
            (uid, username or "", referrer),
        )
    else:
        conn.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (username or "", uid),
        )

    conn.commit()
    conn.close()


def mark_joined_and_reward(uid):
    """
    Marks user as verified.
    If this is the first successful verification and the user has a valid
    referrer, credit the referrer exactly once.
    """
    conn = db()

    row = conn.execute(
        "SELECT joined, referrer FROM users WHERE id = ?",
        (uid,),
    ).fetchone()

    if not row:
        conn.close()
        return False

    if int(row["joined"]) == 1:
        conn.close()
        return False

    conn.execute(
        "UPDATE users SET joined = 1 WHERE id = ?",
        (uid,),
    )

    referrer = row["referrer"]

    if referrer and referrer != uid:
        ref_exists = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (referrer,),
        ).fetchone()

        if ref_exists:
            conn.execute(
                """
                UPDATE users
                SET referrals = referrals + 1,
                    balance = balance + ?
                WHERE id = ?
                """,
                (REFERRAL_REWARD, referrer),
            )

    conn.commit()
    conn.close()
    return True


def set_joined(uid, value):
    conn = db()
    conn.execute(
        "UPDATE users SET joined = ? WHERE id = ?",
        (int(bool(value)), uid),
    )
    conn.commit()
    conn.close()


def referral_link(uid, bot_username):
    return f"https://t.me/{bot_username}?start={uid}"


async def is_member(context: ContextTypes.DEFAULT_TYPE, uid: int):
    try:
        member = await context.bot.get_chat_member(CHANNEL, uid)

        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }

    except Exception as exc:
        log.warning("Membership check failed for %s: %s", uid, exc)
        return False


def join_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Join XPO Channel",
                    url=f"https://t.me/{CHANNEL.lstrip('@')}",
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Verify Join",
                    callback_data="verify",
                )
            ],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    uid = update.effective_user.id

    referrer = None

    if context.args:
        try:
            referrer = int(context.args[0])
        except (ValueError, TypeError):
            referrer = None

    add_user(uid, update.effective_user.username, referrer)

    joined = await is_member(context, uid)

    if not joined:
        set_joined(uid, False)

        await update.message.reply_text(
            "👋 Welcome to XPO Referral!\n\n"
            "1️⃣ Join our XPO channel\n"
            "2️⃣ Tap Verify Join\n\n"
            f"💰 Referral reward: {REFERRAL_REWARD:.2f} USDT",
            reply_markup=join_keyboard(),
        )
        return

    mark_joined_and_reward(uid)

    await update.message.reply_text(
        "✅ You are verified!\n\n"
        "Use /referral to get your referral link."
    )


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    uid = query.from_user.id

    if await is_member(context, uid):
        mark_joined_and_reward(uid)

        await query.edit_message_text(
            "✅ Verification successful!\n\n"
            "Use /referral to get your referral link."
        )
    else:
        await query.edit_message_text(
            "❌ You have not joined the channel yet.\n\n"
            "Join @xpoallkanda first, then tap Verify Join again.",
            reply_markup=join_keyboard(),
        )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    uid = update.effective_user.id

    add_user(uid, update.effective_user.username)

    joined = await is_member(context, uid)

    if not joined:
        await update.message.reply_text(
            "❌ Please join @xpoallkanda first, then use /start."
        )
        return

    mark_joined_and_reward(uid)

    bot_info = await context.bot.get_me()
    row = get_user(uid)

    await update.message.reply_text(
        f"👥 Successful referrals: {row['referrals']}\n"
        f"💰 Balance: {row['balance']:.2f} USDT\n\n"
        f"🔗 Your referral link:\n"
        f"{referral_link(uid, bot_info.username)}\n\n"
        f"🎁 You earn {REFERRAL_REWARD:.2f} USDT per successful referral.\n"
        "A referral is counted after the new user joins the channel and verifies."
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    row = get_user(update.effective_user.id)

    if not row:
        await update.message.reply_text("Use /start first.")
        return

    await update.message.reply_text(
        f"👥 Successful referrals: {row['referrals']}\n"
        f"💰 Balance: {row['balance']:.2f} USDT\n"
        f"💵 Minimum withdrawal: {MIN_WITHDRAW:.2f} USDT"
    )


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    row = get_user(update.effective_user.id)

    if not row:
        await update.message.reply_text("Use /start first.")
        return

    if row["balance"] < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimum withdrawal is {MIN_WITHDRAW:.2f} USDT.\n"
            f"Your balance: {row['balance']:.2f} USDT"
        )
        return

    await update.message.reply_text(
        "Withdrawal request format:\n\n"
        "/withdraw_request METHOD AMOUNT DETAILS\n\n"
        "Example:\n"
        "/withdraw_request USDT 10 TRC20:YOUR_WALLET_ADDRESS"
    )


async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    uid = update.effective_user.id
    row = get_user(uid)

    if not row:
        await update.message.reply_text("Use /start first.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage:\n"
            "/withdraw_request METHOD AMOUNT DETAILS\n\n"
            "Example:\n"
            "/withdraw_request USDT 10 TRC20:YOUR_WALLET_ADDRESS"
        )
        return

    method = context.args[0]

    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return

    details = " ".join(context.args[2:])

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimum withdrawal is {MIN_WITHDRAW:.2f} USDT."
        )
        return

    if amount > row["balance"]:
        await update.message.reply_text(
            f"❌ Insufficient balance.\n"
            f"Your balance: {row['balance']:.2f} USDT"
        )
        return

    conn = db()

    cursor = conn.execute(
        """
        INSERT INTO withdrawals (user_id, amount, method, details)
        VALUES (?, ?, ?, ?)
        """,
        (uid, amount, method, details),
    )

    withdrawal_id = cursor.lastrowid

    conn.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ?",
        (amount, uid),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Withdrawal #{withdrawal_id} submitted.\n"
        "Admin will review and process it manually."
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 New Withdrawal #{withdrawal_id}\n\n"
                f"User ID: {uid}\n"
                f"Amount: {amount:.2f} USDT\n"
                f"Method: {method}\n"
                f"Details: {details}",
            )
        except Exception as exc:
            log.warning("Could not notify admin: %s", exc)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()

    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS users,
            COALESCE(SUM(referrals), 0) AS referrals,
            COALESCE(SUM(balance), 0) AS balance
        FROM users
        """
    ).fetchone()

    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM withdrawals WHERE status = 'pending'"
    ).fetchone()["n"]

    conn.close()

    await update.message.reply_text(
        "📊 XPO Referral Stats\n\n"
        f"Users: {stats['users']}\n"
        f"Successful referrals: {stats['referrals']}\n"
        f"Outstanding balance: {stats['balance']:.2f} USDT\n"
        f"Pending withdrawals: {pending}"
    )


async def addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage:\n/addbalance USER_ID AMOUNT"
        )
        return

    try:
        uid = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID or amount.")
        return

    conn = db()

    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE id = ?",
        (amount, uid),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text("✅ Balance updated.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🤖 XPO Referral Bot\n\n"
        "/start - Register and verify channel join\n"
        "/referral - Get referral link\n"
        "/balance - Check balance\n"
        "/withdraw - Withdrawal instructions\n"
        "/withdraw_request METHOD AMOUNT DETAILS - Submit withdrawal\n"
        "/help - Show this help"
    )


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN environment variable is missing.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("withdraw_request", withdraw_request))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("addbalance", addbalance))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(
        CallbackQueryHandler(verify, pattern="^verify$")
    )

    # python-telegram-bot manages its own asyncio event loop here.
    # Do NOT wrap app.run_polling() inside asyncio.run().
    app.run_polling()


if __name__ == "__main__":
    main()
