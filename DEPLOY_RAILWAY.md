# Deploy to Railway (Free, Always-On)

## What you need first
- A [GitHub](https://github.com) account (free)
- A [Railway](https://railway.app) account — sign up with GitHub (free tier: $5 credit/month, enough for one always-on bot)
- Your `credentials.json` (Google service account file) in this folder

---

## Step 1 — Encode your Google credentials

Run this once on your computer (in the `Business_Tracker_Bot` folder):

```bash
python encode_credentials.py
```

Copy the long base64 string it prints — you'll paste it into Railway in Step 4.

---

## Step 2 — Push code to GitHub

Open a terminal in the `Business_Tracker_Bot` folder and run:

```bash
git init -b main
git add .
git commit -m "Initial commit — expense & sales bot"
```

Then go to https://github.com/new and create a **private** repository named `expense-bot`.

Back in your terminal, connect and push:

```bash
git remote add origin https://github.com/YOUR_USERNAME/expense-bot.git
git push -u origin main
```

---

## Step 3 — Create a Railway project

1. Go to [railway.app](https://railway.app) → **New Project**
2. Choose **Deploy from GitHub repo**
3. Select your `expense-bot` repo
4. Railway detects `nixpacks.toml` automatically — click **Deploy**

---

## Step 4 — Set environment variables

In Railway → your project → **Variables** tab, add these 3 variables:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather (e.g. `1234567890:ABCdef...`) |
| `SPREADSHEET_ID` | Your Google Sheet ID (from its URL: `docs.google.com/spreadsheets/d/THIS_PART/edit`) |
| `GOOGLE_CREDENTIALS_JSON` | The base64 string from Step 1 |

After adding all three, Railway redeploys automatically.

---

## Step 5 — Verify it's running

In Railway → **Deployments** → click the latest deploy → **Logs**

You should see:
```
🤖 Bot started (single-user mode)
```

Then send `/start` to your bot on Telegram — it should reply instantly.

---

## Sales keywords

The bot routes messages to the **Sales sheet** if the text contains:
- `sales` or `sale` (English)
- `مبيعات` (Arabic — sales)
- `بيع` (Arabic — sale/selling)

Examples:
```
sales chicken 500
مبيعات لحم | Customer Name | 300
بيع دجاج 200
```

Everything else goes to the **Expenses sheet**.

---

## Updating the bot

After making changes, just push to GitHub:

```bash
git add .
git commit -m "your change description"
git push
```

Railway auto-redeploys within ~1 minute.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot doesn't reply | Check Railway logs for errors |
| "TELEGRAM_BOT_TOKEN is not set" | Add it in Railway → Variables |
| "Could not connect to sheet" | Check SPREADSHEET_ID and GOOGLE_CREDENTIALS_JSON |
| Sheet not shared with service account | Go to Google Sheet → Share → add the service account email |
