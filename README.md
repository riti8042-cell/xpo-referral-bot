# XPO Telegram Referral Bot

## Features
- Unique referral links
- Channel membership verification
- Referral counting
- Balance and withdrawal requests
- SQLite database
- Admin stats and manual balance control

## Setup
1. Create a bot with @BotFather and copy the token.
2. Add the bot as an administrator of @xpoallkanda.
3. Install Python 3.10+.
4. Run: `pip install -r requirements.txt`
5. Set environment variables from `.env.example`.
6. Run: `python bot.py`

Never publish your BotFather token.

## Important
For reliable channel membership verification, the bot must be an administrator in the channel.
This starter system does NOT automatically pay users. Withdrawal requests are recorded and the admin pays them manually.
