import os, sqlite3, logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ChatMemberStatus

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL = os.getenv("CHANNEL_USERNAME", "@xpoallkanda")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MIN_WITHDRAW = float(os.getenv("MIN_WITHDRAW", "10"))
REFERRAL_REWARD = float(os.getenv("REFERRAL_REWARD", "0.01"))

DB = "referrals.db"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, username TEXT, referrer INTEGER,
        referrals INTEGER DEFAULT 0, balance REAL DEFAULT 0,
        joined INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        amount REAL, method TEXT, details TEXT,
        status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.commit(); c.close()

def add_user(uid, username, referrer=None):
    c=db()
    row=c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        if referrer == uid: referrer=None
        c.execute("INSERT INTO users(id,username,referrer) VALUES(?,?,?)",
                  (uid, username or "", referrer))
        if referrer:
            c.execute(
                "UPDATE users SET referrals=referrals+1, balance=balance+? WHERE id=?",
                (REFERRAL_REWARD, referrer)
            )
    else:
        c.execute("UPDATE users SET username=? WHERE id=?", (username or "", uid))
    c.commit(); c.close()

def user(uid):
    c=db(); r=c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); c.close(); return r

def set_joined(uid, value):
    c=db(); c.execute("UPDATE users SET joined=? WHERE id=?", (uid and int(value), uid)); c.commit(); c.close()

def ref_link(uid, bot_username):
    return f"https://t.me/{bot_username}?start={uid}"

async def is_member(context, uid):
    try:
        m=await context.bot.get_chat_member(CHANNEL, uid)
        return m.status in {
            ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        }
    except Exception as e:
        log.warning("Membership check failed: %s", e)
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    ref=None
    if context.args:
        try: ref=int(context.args[0])
        except: pass
    add_user(uid, update.effective_user.username, ref)
    joined=await is_member(context, uid)
    set_joined(uid, joined)
    if not joined:
        kb=[[InlineKeyboardButton("📢 Join XPO Channel", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton("✅ Verify Join", callback_data="verify")]]
        await update.message.reply_text(
            "👋 Welcome to XPO Referral!\n\nFirst join our channel, then tap Verify Join.",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    await update.message.reply_text(
        "✅ You are verified!\n\nUse /referral to get your referral link.")

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=q.from_user.id
    if await is_member(context, uid):
        set_joined(uid, True)
        await q.edit_message_text("✅ Verified! You can now use /referral.")
    else:
        await q.edit_message_text("❌ Please join @xpoallkanda first, then tap Verify.")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    add_user(uid, update.effective_user.username)
    joined=await is_member(context, uid); set_joined(uid, joined)
    if not joined:
        await update.message.reply_text("❌ Join @xpoallkanda first. Use /start.")
        return
    me=await context.bot.get_me()
    r=user(uid)
    await update.message.reply_text(
        f"👥 Referrals: {r['referrals']}\n"
        f"💰 Balance: Rs. {r['balance']:.2f}\n\n"
        f"🔗 Your referral link:\n{ref_link(uid, me.username)}\n\n"
        "Share this link with friends. A referral counts when the new user joins the channel and verifies."
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r=user(update.effective_user.id)
    if not r:
        await update.message.reply_text("Use /start first."); return
    await update.message.reply_text(f"👥 Referrals: {r['referrals']}\n💰 Balance: Rs. {r['balance']:.2f}")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    r=user(uid)
    if not r: await update.message.reply_text("Use /start first."); return
    if r["balance"] < MIN_WITHDRAW:
        await update.message.reply_text(f"Minimum withdrawal is Rs. {MIN_WITHDRAW:.0f}. Your balance: Rs. {r['balance']:.2f}")
        return
    await update.message.reply_text(
        "Withdrawal request format:\n\n"
        "/withdraw_request eSewa 100 98XXXXXXXX\n\n"
        "Example above means method=eSewa, amount=100, details=your number.")

async def withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    r=user(uid)
    if not r: await update.message.reply_text("Use /start first."); return
    if len(context.args)<3:
        await update.message.reply_text("Usage: /withdraw_request METHOD AMOUNT DETAILS")
        return
    method=context.args[0]
    try: amount=float(context.args[1])
    except:
        await update.message.reply_text("Invalid amount."); return
    details=" ".join(context.args[2:])
    if amount < MIN_WITHDRAW or amount > r["balance"]:
        await update.message.reply_text("Invalid amount or insufficient balance."); return
    c=db()
    c.execute("INSERT INTO withdrawals(user_id,amount,method,details) VALUES(?,?,?,?)",
              (uid,amount,method,details))
    c.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount,uid))
    wid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit(); c.close()
    await update.message.reply_text(f"✅ Withdrawal #{wid} submitted. Admin will review it.")
    if ADMIN_ID:
        await context.bot.send_message(ADMIN_ID,
            f"💸 Withdrawal #{wid}\nUser: {uid}\nAmount: Rs. {amount:.2f}\nMethod: {method}\nDetails: {details}")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    c=db()
    users=c.execute("SELECT COUNT(*) n, COALESCE(SUM(referrals),0) refs, COALESCE(SUM(balance),0) bal FROM users").fetchone()
    pending=c.execute("SELECT COUNT(*) n FROM withdrawals WHERE status='pending'").fetchone()["n"]
    c.close()
    await update.message.reply_text(
        f"📊 XPO Referral Stats\nUsers: {users['n']}\nReferrals: {users['refs']}\nBalances: Rs. {users['bal']:.2f}\nPending withdrawals: {pending}")

async def addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args)!=2:
        await update.message.reply_text("Usage: /addbalance USER_ID AMOUNT"); return
    uid=int(context.args[0]); amount=float(context.args[1])
    c=db(); c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount,uid)); c.commit(); c.close()
    await update.message.reply_text("✅ Balance updated.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - verify and register\n/referral - referral link\n/balance - balance\n"
        "/withdraw - withdrawal instructions\n"
        "/withdraw_request METHOD AMOUNT DETAILS - request withdrawal")

async def main():
    if not BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN environment variable.")
    init_db()
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("withdraw_request", withdraw_request))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("addbalance", addbalance))
    app.add_handler(CommandHandler("help", help_cmd))
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(verify, pattern="^verify$"))
    await app.run_polling()

if __name__=="__main__":
    import asyncio
    asyncio.run(main())
