import logging
import json
import os
import re
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN     = "8984000441:AAHZMzhK5sfvtf6rYDWy-KPlQMe9QDIlS30"
GNEWS_API_KEY = "4d141e6ed9c1c94559d66c74380ba60f"
USERS_FILE    = "users.json"
SCHEDULE_FILE = "schedules.json"
WAITING_FILE  = "waiting.json"
ALERTED_FILE  = "alerted.json"

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# HELPERS
# ============================================================
def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

# ============================================================
# PARSE SCHEDULE TEXT — shared by both typing and file upload
# ============================================================
def parse_schedule_text(text):
    tasks = []
    # Match patterns like: 9:00 AM Meeting, 09:00 AM Meeting, 9AM Meeting
    pattern = re.compile(
        r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)|\d{1,2}\s*(?:AM|PM|am|pm))'
        r'\s*[-–:]?\s*(.+)',
        re.IGNORECASE
    )
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = pattern.search(line)
        if match:
            raw_time = match.group(1).strip().upper().replace(" ", "")
            task_str = match.group(2).strip()
            # Normalize time to HH:MM AM/PM
            try:
                if ":" in raw_time:
                    t = datetime.strptime(raw_time, "%I:%M%p")
                else:
                    t = datetime.strptime(raw_time, "%I%p")
                normalized = t.strftime("%I:%M %p")
                tasks.append({"time": normalized, "task": task_str})
            except:
                # fallback — try splitting manually
                parts = line.split(" ", 3)
                if len(parts) >= 3:
                    tasks.append({"time": f"{parts[0]} {parts[1]}", "task": " ".join(parts[2:])})
    return tasks

# ============================================================
# NEWS
# ============================================================
def get_news(topic="India", count=10):
    try:
        url = f"https://gnews.io/api/v4/top-headlines?q={topic}&lang=en&max={count}&apikey={GNEWS_API_KEY}"
        res = requests.get(url, timeout=10).json()
        articles = res.get("articles", [])
        if not articles:
            return "No news found right now."
        lines = []
        for i, a in enumerate(articles[:count], 1):
            title  = a.get("title", "").strip()
            source = a.get("source", {}).get("name", "")
            lines.append(f"<b>{i}.</b> {title}\n    <i>— {source}</i>")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Could not fetch news: {e}"

def get_tech_news(count=5):
    try:
        url = f"https://gnews.io/api/v4/top-headlines?topic=technology&lang=en&max={count}&apikey={GNEWS_API_KEY}"
        res = requests.get(url, timeout=10).json()
        articles = res.get("articles", [])
        if not articles:
            return "No tech news found."
        lines = []
        for i, a in enumerate(articles[:count], 1):
            title  = a.get("title", "").strip()
            source = a.get("source", {}).get("name", "")
            lines.append(f"<b>{i}.</b> {title}\n    <i>— {source}</i>")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Could not fetch tech news: {e}"

def get_business_news(count=5):
    try:
        url = f"https://gnews.io/api/v4/top-headlines?topic=business&lang=en&max={count}&apikey={GNEWS_API_KEY}"
        res = requests.get(url, timeout=10).json()
        articles = res.get("articles", [])
        if not articles:
            return "No business news found."
        lines = []
        for i, a in enumerate(articles[:count], 1):
            title  = a.get("title", "").strip()
            source = a.get("source", {}).get("name", "")
            lines.append(f"<b>{i}.</b> {title}\n    <i>— {source}</i>")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Could not fetch business news: {e}"

# ============================================================
# GOLD & SILVER
# ============================================================
def get_gold_silver():
    try:
        url      = "https://api.coinbase.com/v2/exchange-rates?currency=XAU"
        res      = requests.get(url, timeout=10).json()
        xau_inr  = float(res["data"]["rates"]["INR"])
        gold_10g = round(xau_inr / 3.215, 2)
        url2      = "https://api.coinbase.com/v2/exchange-rates?currency=XAG"
        res2      = requests.get(url2, timeout=10).json()
        xag_inr   = float(res2["data"]["rates"]["INR"])
        silver_kg = round(xag_inr * 32.15, 2)
        return f"🥇 <b>Gold:</b> ₹{gold_10g:,} / 10g\n🥈 <b>Silver:</b> ₹{silver_kg:,} / kg"
    except Exception as e:
        return f"Could not fetch gold/silver: {e}"

# ============================================================
# MARKET
# ============================================================
def get_market():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        s = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EBSESN?interval=1d&range=1d", headers=headers, timeout=10).json()
        n = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1d&range=1d",  headers=headers, timeout=10).json()
        sensex  = s["chart"]["result"][0]["meta"]["regularMarketPrice"]
        s_prev  = s["chart"]["result"][0]["meta"]["previousClose"]
        s_chg   = round(sensex - s_prev, 2)
        s_pct   = round((s_chg / s_prev) * 100, 2)
        s_arrow = "▲" if s_chg >= 0 else "▼"
        nifty   = n["chart"]["result"][0]["meta"]["regularMarketPrice"]
        n_prev  = n["chart"]["result"][0]["meta"]["previousClose"]
        n_chg   = round(nifty - n_prev, 2)
        n_pct   = round((n_chg / n_prev) * 100, 2)
        n_arrow = "▲" if n_chg >= 0 else "▼"
        return (
            f"📊 <b>Sensex:</b> {sensex:,.2f} {s_arrow} {abs(s_chg)} ({abs(s_pct)}%)\n"
            f"📈 <b>Nifty:</b>  {nifty:,.2f} {n_arrow} {abs(n_chg)} ({abs(n_pct)}%)"
        )
    except Exception as e:
        return f"Could not fetch market data: {e}"

# ============================================================
# SEND HELPERS
# ============================================================
_app = None

def set_app(app):
    global _app
    _app = app

def send_message_sync(chat_id, text):
    if _app is None:
        return
    asyncio.run_coroutine_threadsafe(
        _app.bot.send_message(chat_id=int(chat_id), text=text, parse_mode="HTML"),
        _app.loop
    )

def send_to_all_sync(text):
    users = load_json(USERS_FILE)
    for chat_id in users:
        try:
            send_message_sync(chat_id, text)
        except Exception as e:
            logger.error(f"Failed to send to {chat_id}: {e}")

# ============================================================
# SAVE SCHEDULE & FIRE IMMEDIATE REMINDERS
# ============================================================
async def save_and_confirm_schedule(update, chat_id, tasks):
    schedules  = load_json(SCHEDULE_FILE)
    alerted    = load_json(ALERTED_FILE)
    now        = datetime.now()
    today_key  = now.strftime("%Y-%m-%d")

    schedules[chat_id] = tasks
    save_json(SCHEDULE_FILE, schedules)

    lines_out   = []
    remind_msgs = []

    for t in tasks:
        lines_out.append(f"✅ <b>{t['time']}</b> — {t['task']}")
        try:
            task_time = datetime.strptime(t["time"], "%I:%M %p").replace(
                year=now.year, month=now.month, day=now.day
            )
            mins_left = (task_time - now).total_seconds() / 60
            alert_key = f"{chat_id}_{today_key}_{t['time']}_{t['task']}"
            if 0 < mins_left <= 30 and not alerted.get(alert_key):
                remind_msgs.append((t, int(mins_left), alert_key))
        except:
            pass

    await update.message.reply_text(
        f"📅 <b>Schedule saved!</b>\n\n"
        + "\n".join(lines_out)
        + "\n\n⏰ I'll remind you when each task is within 30 minutes!\nHave a productive day! 💪",
        parse_mode="HTML"
    )

    for t, mins_left, alert_key in remind_msgs:
        await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>IMMEDIATE REMINDER!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <b>{t['task']}</b>\n"
            f"🕐 At <b>{t['time']}</b>\n"
            f"⏳ Only <b>{mins_left} minutes</b> away!",
            parse_mode="HTML"
        )
        alerted[alert_key] = True

    save_json(ALERTED_FILE, alerted)

    waiting = load_json(WAITING_FILE)
    waiting.pop(chat_id, None)
    save_json(WAITING_FILE, waiting)

# ============================================================
# MORNING BRIEFING
# ============================================================
async def send_morning_briefing(bot, chat_id):
    name = load_json(USERS_FILE).get(str(chat_id), {}).get("name", "Sir")
    date = datetime.now().strftime('%d %b %Y')

    news = get_news("India", 10)
    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🌅 <b>Good Morning, {name}!</b>\n"
        f"📅 {date}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📰 <b>TOP 10 INDIA NEWS</b>\n\n{news}"
    ))

    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💹 <b>MARKET & PRICES</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_market()}\n\n{get_gold_silver()}"
    ))

    tech = get_tech_news(5)
    biz  = get_business_news(5)
    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💻 <b>TECH NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n{tech}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💼 <b>BUSINESS NEWS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n{biz}"
    ))

    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        "━━━━━━━━━━━━━━━━━━━\n"
        "📅 <b>TODAY'S SCHEDULE</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "What's your schedule for today?\n\n"
        "<b>Option 1 — Type it:</b>\n"
        "<code>9:00 AM Team meeting\n"
        "2:00 PM Client call\n"
        "5:00 PM Report submission</code>\n\n"
        "<b>Option 2 — Upload a file:</b>\n"
        "Send a <b>.txt</b> file with your schedule\n\n"
        "⏰ I'll remind you <b>30 minutes before</b> each task!\n"
        "Type <b>skip</b> if no schedule today."
    ))

    waiting = load_json(WAITING_FILE)
    waiting[str(chat_id)] = True
    save_json(WAITING_FILE, waiting)

# ============================================================
# SCHEDULED JOBS
# ============================================================
def job_morning():
    users = load_json(USERS_FILE)
    for chat_id in users:
        try:
            asyncio.run_coroutine_threadsafe(
                send_morning_briefing(_app.bot, int(chat_id)), _app.loop
            )
        except Exception as e:
            logger.error(f"Morning job error: {e}")

def job_market_open():
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n📈 <b>MARKET OPEN — 9:15 AM</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_market()}\n\n{get_gold_silver()}"
    )

def job_afternoon():
    tech = get_tech_news(5)
    biz  = get_business_news(5)
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n☀️ <b>AFTERNOON UPDATE — 1:00 PM</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"💻 <b>Tech:</b>\n\n{tech}\n\n💼 <b>Business:</b>\n\n{biz}"
    )

def job_market_close():
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n🔔 <b>MARKET CLOSED — 3:30 PM</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_market()}\n\n{get_gold_silver()}"
    )

def job_evening_news():
    news = get_news("world", 10)
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n🌍 <b>EVENING WORLD NEWS</b>\n"
        f"📅 {datetime.now().strftime('%d %b %Y')}\n━━━━━━━━━━━━━━━━━━━\n\n{news}"
    )

def job_price_alerts():
    try:
        gs     = get_gold_silver()
        market = get_market()
        raw_gs = gs.replace("<b>","").replace("</b>","")
        raw_mk = market.replace("<b>","").replace("</b>","")
        gold_val   = float(raw_gs.split("\n")[0].split("₹")[1].split(" ")[0].replace(",",""))
        silver_val = float(raw_gs.split("\n")[1].split("₹")[1].split(" ")[0].replace(",",""))
        sensex_val = float(raw_mk.split("\n")[0].split(":")[1].strip().split(" ")[0].replace(",",""))
        alerts = []
        if gold_val   >= 73000: alerts.append(f"🚨 <b>Gold</b> crossed ₹73,000!\nNow: ₹{gold_val:,}/10g")
        if silver_val >= 90000: alerts.append(f"🚨 <b>Silver</b> crossed ₹90,000!\nNow: ₹{silver_val:,}/kg")
        if sensex_val >= 75000: alerts.append(f"🚨 <b>Sensex</b> crossed 75,000!\nNow: {sensex_val:,}")
        if alerts:
            send_to_all_sync(
                f"━━━━━━━━━━━━━━━━━━━\n⚡ <b>PRICE ALERT!</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
                + "\n\n".join(alerts)
            )
    except Exception as e:
        logger.error(f"Alert error: {e}")

def job_reminders():
    schedules = load_json(SCHEDULE_FILE)
    alerted   = load_json(ALERTED_FILE)
    now       = datetime.now()
    today_key = now.strftime("%Y-%m-%d")
    changed   = False
    for chat_id, tasks in schedules.items():
        for task in tasks:
            try:
                task_time = datetime.strptime(task["time"], "%I:%M %p").replace(
                    year=now.year, month=now.month, day=now.day
                )
                alert_key = f"{chat_id}_{today_key}_{task['time']}_{task['task']}"
                if alerted.get(alert_key):
                    continue
                if now >= task_time:
                    continue
                mins_left = (task_time - now).total_seconds() / 60
                if mins_left <= 30:
                    send_message_sync(chat_id,
                        f"━━━━━━━━━━━━━━━━━━━\n⏰ <b>REMINDER!</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📌 <b>{task['task']}</b>\n"
                        f"🕐 At <b>{task['time']}</b>\n"
                        f"⏳ In <b>{int(mins_left)} minutes</b>"
                    )
                    alerted[alert_key] = True
                    changed = True
            except Exception as e:
                logger.error(f"Reminder error: {e}")
    if changed:
        save_json(ALERTED_FILE, alerted)

# ============================================================
# START
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    name    = update.effective_chat.first_name or "Sir"
    users   = load_json(USERS_FILE)
    users[chat_id] = {"name": name, "joined": str(datetime.now())}
    save_json(USERS_FILE, users)
    await update.message.reply_text(
        f"👋 <b>Welcome, {name}!</b>\n\nFetching your complete briefing now...",
        parse_mode="HTML"
    )
    await send_morning_briefing(context.bot, int(chat_id))

# ============================================================
# COMMANDS
# ============================================================
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    waiting = load_json(WAITING_FILE)
    waiting[chat_id] = True
    save_json(WAITING_FILE, waiting)
    await update.message.reply_text(
        "📅 <b>Set your schedule</b>\n\n"
        "<b>Option 1 — Type it:</b>\n"
        "<code>9:00 AM Team meeting\n2:00 PM Client call\n5:00 PM Report</code>\n\n"
        "<b>Option 2 — Upload a .txt file</b>\n"
        "Same format inside the file\n\n"
        "⏰ I'll remind you within <b>30 minutes</b> of each task!",
        parse_mode="HTML"
    )

async def cmd_view_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id   = str(update.effective_chat.id)
    schedules = load_json(SCHEDULE_FILE)
    tasks     = schedules.get(chat_id, [])
    if not tasks:
        await update.message.reply_text("No schedule saved. Use /schedule to set one.")
        return
    lines = [f"⏰ <b>{t['time']}</b> — {t['task']}" for t in tasks]
    await update.message.reply_text(
        f"📅 <b>Your Schedule Today</b>\n\n" + "\n".join(lines),
        parse_mode="HTML"
    )

async def cmd_clear_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id   = str(update.effective_chat.id)
    schedules = load_json(SCHEDULE_FILE)
    alerted   = load_json(ALERTED_FILE)
    schedules.pop(chat_id, None)
    save_json(SCHEDULE_FILE, schedules)
    today_key = datetime.now().strftime("%Y-%m-%d")
    for k in [k for k in alerted if k.startswith(f"{chat_id}_{today_key}")]:
        alerted.pop(k, None)
    save_json(ALERTED_FILE, alerted)
    await update.message.reply_text("✅ Schedule cleared!")

# ============================================================
# TEXT MESSAGE HANDLER
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text    = update.message.text.strip()
    waiting = load_json(WAITING_FILE)

    if waiting.get(chat_id):
        if text.lower() == "skip":
            waiting.pop(chat_id, None)
            save_json(WAITING_FILE, waiting)
            await update.message.reply_text("✅ No problem! See you tomorrow at 6 AM. Have a great day! 😊")
            return

        tasks = parse_schedule_text(text)
        if tasks:
            await save_and_confirm_schedule(update, chat_id, tasks)
        else:
            await update.message.reply_text(
                "Could not read your schedule. Please use:\n\n"
                "<code>9:00 AM Team meeting\n2:00 PM Client call</code>\n\n"
                "Or upload a <b>.txt file</b> with same format.\n"
                "Or type <b>skip</b> to skip today.",
                parse_mode="HTML"
            )
        return

    await update.message.reply_text(
        "I send updates automatically every day at 6 AM! 😊\n\n"
        "Use /schedule to set today's reminders.\n"
        "Use /viewschedule to see your schedule."
    )

# ============================================================
# FILE UPLOAD HANDLER — .txt files
# ============================================================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id  = str(update.effective_chat.id)
    document = update.message.document

    if not document:
        return

    file_name = document.file_name or ""

    # Only accept .txt files
    if not file_name.endswith(".txt"):
        await update.message.reply_text(
            "⚠️ Please upload a <b>.txt</b> file only.\n\n"
            "Create a text file with your schedule like:\n"
            "<code>9:00 AM Team meeting\n2:00 PM Client call\n5:00 PM Report</code>",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text("📂 Reading your schedule file...")

    try:
        file = await context.bot.get_file(document.file_id)
        content = await file.download_as_bytearray()
        text = content.decode("utf-8", errors="ignore")

        tasks = parse_schedule_text(text)

        if tasks:
            # Mark as waiting so save_and_confirm works
            waiting = load_json(WAITING_FILE)
            waiting[chat_id] = True
            save_json(WAITING_FILE, waiting)
            await save_and_confirm_schedule(update, chat_id, tasks)
        else:
            await update.message.reply_text(
                "⚠️ Could not read tasks from your file.\n\n"
                "Make sure the file contains:\n"
                "<code>9:00 AM Team meeting\n2:00 PM Client call</code>",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"File read error: {e}")
        await update.message.reply_text(f"❌ Error reading file: {e}")

# ============================================================
# MAIN
# ============================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    set_app(app)

    app.add_handler(CommandHandler("start",         start))
    app.add_handler(CommandHandler("schedule",      cmd_schedule))
    app.add_handler(CommandHandler("viewschedule",  cmd_view_schedule))
    app.add_handler(CommandHandler("clearschedule", cmd_clear_schedule))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(job_morning,      "cron", hour=6,  minute=0)
    scheduler.add_job(job_market_open,  "cron", hour=9,  minute=15)
    scheduler.add_job(job_afternoon,    "cron", hour=13, minute=0)
    scheduler.add_job(job_market_close, "cron", hour=15, minute=30)
    scheduler.add_job(job_evening_news, "cron", hour=19, minute=0)
    scheduler.add_job(job_price_alerts, "interval", minutes=5)
    scheduler.add_job(job_reminders,    "interval", minutes=1)
    scheduler.start()

    logger.info("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
