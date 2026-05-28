# Nami Bot — Railway Deployment Guide

One Piece themed Telegram game bot with kills, ships, balance, items, AI chat, and group management.

## Files

```
main.py         — Bot with all commands and handlers
db.py           — Database functions (PostgreSQL)
constants.py    — Game constants and config
requirements.txt
Procfile        — Railway process config
.env.example    — Environment variables reference
```

## Step-by-Step Railway Deployment

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Nami bot initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/nami-bot.git
git push -u origin main
```

### 2. Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your `nami-bot` repo

### 3. Add PostgreSQL Database

1. In your Railway project, click **+ New**
2. Select **Database** → **Add PostgreSQL**
3. Railway will automatically set `DATABASE_URL` in your service

### 4. Set Environment Variables

In your Railway service settings → **Variables**, add:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your token from @BotFather |
| `OPENAI_API_KEY` | Your OpenAI API key (for AI chat) |

> `DATABASE_URL` is automatically set by Railway when you add PostgreSQL.

### 5. Deploy

Railway will auto-deploy when you push to GitHub. The bot starts automatically.

## Bot Commands

### Game
- `/start` — Start menu
- `/bal` — Check balance & stats
- `/daily` — Daily $2,000 reward (DM only)
- `/kill` — Kill someone (reply to their message)
- `/rob <amount>` — Rob someone (reply to their message)
- `/protect 1d/2d` — Protection shield (2d = premium)

### Ships
- `/newship <name>` — Create your own ship
- `/joinship <code>` — Join a ship by 4-digit code
- `/ship` — View your ship info
- `/leaveship` — Leave current ship

### Leaderboards
- `/toprich` — Top 10 richest players
- `/topkills` — Top 10 killers
- `/topbounty` — Top 10 bounties
- `/topships` — Top 20 ships

### Items
- `/items` — See available items
- `/purchase <item>` — Buy an item
- `/gift <item>` — Gift an item (reply)

### Codes
- `/redeem <code>` — Redeem balance code
- `/redbounty <code>` — Redeem bounty code

### Group Management (admins)
- `/promote 1/2/3` — Promote user
- `/demote` — Demote user
- `/warn` — Warn user (5 warns = auto ban)
- `/mute` / `/unmute` — Mute/unmute user
- `/kick` — Kick user

### Owner Only
- `/givepremium <days>` — Give premium to user
- `/cancelpremium` — Cancel someone's premium
- `/setbal <amount>` — Set your balance
- `/gen <amount>` — Generate balance code
- `/bounty <amount>` — Generate bounty code

## Notes

- The bot uses **long polling** (no webhook needed — works perfectly on Railway worker)
- AI chat works when user mentions "nami", replies to the bot, or messages in DM
- `OPENAI_API_KEY` is optional — without it AI chat won't work but all game commands will
- Tables are created automatically on first run (no manual migrations needed)
