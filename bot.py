import logging
import json
import os
import re
import smtplib
import requests
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import hashlib

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN       = "8984000441:AAHZMzhK5sfvtf6rYDWy-KPlQMe9QDIlS30"
GNEWS_API_KEY   = "4d141e6ed9c1c94559d66c74380ba60f"
SENDER_EMAIL    = "srv19246@gmail.com"
SENDER_PASSWORD = "epsy okyw jyqr ztcs"
RECIPIENTS      = ["ranveersingh8823@gmail.com", "amitindia0001@yahoo.com"]
USERS_FILE      = "users.json"
SCHEDULE_FILE   = "schedules.json"
WAITING_FILE    = "waiting.json"
ALERTED_FILE    = "alerted.json"

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

ETF_ALERTED = {}

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
# ETF LISTS
# ============================================================
INDIAN_ETFS = {
    "Nifty BeES":       "NIFTYBEES.NS",
    "Bank BeES":        "BANKBEES.NS",
    "Gold BeES":        "GOLDBEES.NS",
    "IT BeES":          "ITBEES.NS",
    "PSU Bank BeES":    "PSUBNKBEES.NS",
    "Midcap 150":       "MID150BEES.NS",
    "Pharma BeES":      "PHARMABEES.NS",
    "CPSE ETF":         "CPSEETF.NS",
    "Bharat Bond 2030": "EBBETF0430.NS",
    "Nifty Next 50":    "JUNIORBEES.NS",
}

INTL_ETFS = {
    "SPDR S&P 500 (SPY)":     "SPY",
    "Nasdaq 100 (QQQ)":       "QQQ",
    "Emerging Markets (EEM)": "EEM",
    "Vanguard EM (VWO)":      "VWO",
    "ARK Innovation (ARKK)":  "ARKK",
    "Gold ETF (GLD)":         "GLD",
    "20yr Treasury (TLT)":    "TLT",
    "Russell 2000 (IWM)":     "IWM",
    "Dow Jones (DIA)":        "DIA",
    "Financials (XLF)":       "XLF",
}

# ============================================================
# FETCH ETF LOSERS — top 5
# ============================================================
def fetch_etf_losers(symbols_dict):
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for name, symbol in symbols_dict.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            res = requests.get(url, headers=headers, timeout=10).json()
            meta     = res["chart"]["result"][0]["meta"]
            price    = meta["regularMarketPrice"]
            prev     = meta["previousClose"]
            change   = round(price - prev, 2)
            pct      = round((change / prev) * 100, 2)
            currency = "₹" if ".NS" in symbol else "$"
            results.append({"name": name, "symbol": symbol, "price": price,
                            "change": change, "pct": pct, "currency": currency})
        except Exception as e:
            logger.error(f"ETF fetch error {name}: {e}")
    results.sort(key=lambda x: x["pct"])
    return results[:5]

# ============================================================
# ETF 3% DROP — EMAIL ALERT ONLY
# ============================================================
def job_etf_alerts():
    global ETF_ALERTED
    today_key = datetime.now().strftime("%Y-%m-%d")
    headers   = {"User-Agent": "Mozilla/5.0"}
    all_etfs  = {**INDIAN_ETFS, **INTL_ETFS}
    alerts    = []

    for name, symbol in all_etfs.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            res = requests.get(url, headers=headers, timeout=10).json()
            meta      = res["chart"]["result"][0]["meta"]
            price     = meta["regularMarketPrice"]
            prev      = meta["previousClose"]
            pct       = round(((price - prev) / prev) * 100, 2)
            currency  = "₹" if ".NS" in symbol else "$"
            alert_key = f"{symbol}_{today_key}"
            flag      = "🇮🇳" if ".NS" in symbol else "🌍"

            if pct <= -3.0 and not ETF_ALERTED.get(alert_key):
                alerts.append({
                    "name": name, "symbol": symbol,
                    "price": price, "pct": pct,
                    "currency": currency, "flag": flag,
                    "change": round(price - prev, 2)
                })
                ETF_ALERTED[alert_key] = True

        except Exception as e:
            logger.error(f"ETF alert check error {name}: {e}")

    if alerts:
        send_etf_alert_email(alerts)

def send_etf_alert_email(alerts):
    try:
        date = datetime.now().strftime("%d %b %Y %I:%M %p")

        def rows(etfs):
            html = ""
            for i, e in enumerate(etfs, 1):
                bg = "#fff5f5" if i % 2 == 0 else "#ffffff"
                html += f"""
                <tr style="background:{bg}">
                    <td style="padding:12px 10px;font-size:18px">{e['flag']}</td>
                    <td style="padding:12px 10px">
                        <b style="color:#2c3e50">{e['name']}</b><br>
                        <span style="font-size:11px;color:#aaa">{e['symbol']}</span>
                    </td>
                    <td style="padding:12px 10px;font-weight:600">{e['currency']}{e['price']:,.2f}</td>
                    <td style="padding:12px 10px;color:#e74c3c;font-weight:700;font-size:15px">▼ {abs(e['pct'])}%</td>
                    <td style="padding:12px 10px;color:#e74c3c">{e['currency']}{abs(e['change']):,.2f}</td>
                </tr>"""
            return html

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:Arial,sans-serif;background:#f4f6f9;margin:0;padding:20px}}
.container{{max-width:650px;margin:auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1)}}
.header{{background:linear-gradient(135deg,#7b0000,#c0392b);color:white;padding:30px;text-align:center}}
.header h1{{margin:0;font-size:24px}}
.header p{{margin:8px 0 0;opacity:.85;font-size:14px}}
.alert-box{{background:#fff5f5;border:2px solid #e74c3c;border-radius:8px;padding:15px;margin:20px 25px;text-align:center}}
.alert-box p{{margin:0;color:#c0392b;font-weight:600;font-size:14px}}
.section{{padding:0 25px 25px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#f8f9fa;padding:10px;text-align:left;font-size:11px;color:#666;border-bottom:2px solid #eee;text-transform:uppercase;letter-spacing:0.5px}}
.footer{{background:#f8f9fa;padding:20px;text-align:center;font-size:12px;color:#888;border-top:1px solid #eee}}
</style></head><body>
<div class="container">

<div class="header">
  <h1>🚨 ETF Drop Alert!</h1>
  <p>One or more ETFs have dropped <b>3% or more</b></p>
  <p style="margin-top:6px">⏰ {date} IST</p>
</div>

<div class="alert-box">
  <p>⚠️ Amit Sir, immediate attention may be required on the following ETFs</p>
</div>

<div class="section">
  <table>
    <thead><tr>
      <th></th>
      <th>ETF Name</th>
      <th>Current Price</th>
      <th>Drop %</th>
      <th>Drop Amount</th>
    </tr></thead>
    <tbody>{rows(alerts)}</tbody>
  </table>
</div>

<div class="footer">
  <p>🤖 <b>AmitDailyUpdatesBot</b> · Automated ETF Alert System</p>
  <p style="color:#aaa;font-size:11px;margin-top:4px">
    Each ETF alerts only <b>once per day</b> · Checks every 5 minutes · Data from Yahoo Finance
  </p>
</div>

</div></body></html>"""

        msg            = MIMEMultipart("alternative")
        msg["Subject"] = f"🚨 ETF Drop Alert (-3%+) — {datetime.now().strftime('%d %b %Y %I:%M %p')}"
        msg["From"]    = SENDER_EMAIL
        msg["To"]      = ", ".join(RECIPIENTS)
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

        logger.info(f"✅ ETF alert email sent for {len(alerts)} ETFs!")
    except Exception as e:
        logger.error(f"ETF alert email error: {e}")

# ============================================================
# ETF TELEGRAM REPORT — 6AM and 3:30PM
# ============================================================
async def send_etf_telegram(bot, chat_id, label=""):
    try:
        indian = fetch_etf_losers(INDIAN_ETFS)
        intl   = fetch_etf_losers(INTL_ETFS)

        indian_lines = "\n".join([
            f"<b>{i}.</b> {e['name']}\n"
            f"    🔴 {abs(e['pct'])}% &nbsp;|&nbsp; {e['currency']}{e['price']:,.2f}"
            for i, e in enumerate(indian, 1)
        ])
        intl_lines = "\n".join([
            f"<b>{i}.</b> {e['name']}\n"
            f"    🔴 {abs(e['pct'])}% &nbsp;|&nbsp; {e['currency']}{e['price']:,.2f}"
            for i, e in enumerate(intl, 1)
        ])

        await bot.send_message(
            chat_id=chat_id,
            parse_mode="HTML",
            text=(
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📉 <b>TOP ETF LOSERS{' — ' + label if label else ''}</b>\n"
                f"📅 {datetime.now().strftime('%d %b %Y')}\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"🇮🇳 <b>Indian ETFs — Biggest Losers</b>\n\n"
                f"{indian_lines}\n\n"
                f"🌍 <b>International ETFs — Biggest Losers</b>\n\n"
                f"{intl_lines}\n\n"
                f"<i>📧 You'll get an email alert if any ETF drops 3%+</i>"
            )
        )
    except Exception as e:
        logger.error(f"ETF Telegram error: {e}")

# ============================================================
# DAILY ETF EMAIL — 6AM
# ============================================================
def build_email_html(indian, intl):
    date = datetime.now().strftime("%d %b %Y")

    def rows(etfs):
        html = ""
        for i, e in enumerate(etfs, 1):
            bg    = "#fff5f5" if i % 2 == 0 else "#ffffff"
            color = "#e74c3c" if e['pct'] < 0 else "#27ae60"
            arrow = "▼" if e['pct'] < 0 else "▲"
            html += f"""
            <tr style="background:{bg}">
                <td style="padding:12px 10px;font-weight:600;color:#666">{i}</td>
                <td style="padding:12px 10px"><b style="color:#2c3e50">{e['name']}</b><br>
                    <span style="font-size:11px;color:#aaa">{e['symbol']}</span></td>
                <td style="padding:12px 10px;font-weight:600">{e['currency']}{e['price']:,.2f}</td>
                <td style="padding:12px 10px;color:{color};font-weight:700">{arrow} {abs(e['pct'])}%</td>
                <td style="padding:12px 10px;color:{color}">{e['currency']}{abs(e['change']):,.2f}</td>
            </tr>"""
        return html

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:Arial,sans-serif;background:#f4f6f9;margin:0;padding:20px}}
.container{{max-width:650px;margin:auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1)}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:30px;text-align:center}}
.header h1{{margin:0;font-size:22px}}
.header p{{margin:8px 0 0;opacity:.8;font-size:14px}}
.section{{padding:25px}}
.section-title{{font-size:15px;font-weight:700;margin-bottom:15px;padding:10px 15px;border-radius:8px}}
.indian{{background:#fff0f0;color:#c0392b;border-left:4px solid #e74c3c}}
.intl{{background:#f0f4ff;color:#2c3e8c;border-left:4px solid #3498db}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#f8f9fa;padding:10px;text-align:left;font-size:12px;color:#666;border-bottom:2px solid #eee;text-transform:uppercase}}
.footer{{background:#f8f9fa;padding:20px;text-align:center;font-size:12px;color:#888;border-top:1px solid #eee}}
</style></head><body>
<div class="container">
<div class="header">
  <h1>📉 Daily ETF Losers Report</h1>
  <p>📅 {date} · Top 5 Worst Performing ETFs</p>
  <p style="margin-top:6px">Good Morning, Amit Sir! 👋</p>
</div>
<div class="section">
  <div class="section-title indian">🇮🇳 Top 5 Indian ETFs — Biggest Losers Today</div>
  <table><thead><tr>
    <th>#</th><th>ETF Name</th><th>Price</th><th>Change %</th><th>Drop ₹</th>
  </tr></thead><tbody>{rows(indian)}</tbody></table>
</div>
<div class="section" style="padding-top:0">
  <div class="section-title intl">🌍 Top 5 International ETFs — Biggest Losers Today</div>
  <table><thead><tr>
    <th>#</th><th>ETF Name</th><th>Price</th><th>Change %</th><th>Drop $</th>
  </tr></thead><tbody>{rows(intl)}</tbody></table>
</div>
<div class="footer">
  <p>🤖 Powered by <b>AmitDailyUpdatesBot</b></p>
  <p style="margin-top:4px">Built by <b>Ranveer Singh</b> · Runs 24/7 on cloud</p>
  <p style="margin-top:8px;color:#aaa;font-size:11px">Live data from Yahoo Finance · Auto sent every day at 6:00 AM IST</p>
</div>
</div></body></html>"""

def send_etf_email():
    try:
        logger.info("Sending daily ETF email...")
        indian = fetch_etf_losers(INDIAN_ETFS)
        intl   = fetch_etf_losers(INTL_ETFS)
        html   = build_email_html(indian, intl)
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = f"📉 Daily ETF Losers Report — {datetime.now().strftime('%d %b %Y')}"
        msg["From"]    = SENDER_EMAIL
        msg["To"]      = ", ".join(RECIPIENTS)
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
        logger.info("✅ Daily ETF email sent!")
    except Exception as e:
        logger.error(f"Email error: {e}")

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
        return "\n\n".join([
            f"<b>{i}.</b> {a['title']}\n    <i>— {a.get('source',{}).get('name','')}</i>"
            for i, a in enumerate(articles[:count], 1)
        ])
    except Exception as e:
        return f"Could not fetch news: {e}"

def get_tech_news(count=5):
    try:
        url = f"https://gnews.io/api/v4/top-headlines?topic=technology&lang=en&max={count}&apikey={GNEWS_API_KEY}"
        res = requests.get(url, timeout=10).json()
        articles = res.get("articles", [])
        if not articles: return "No tech news found."
        return "\n\n".join([
            f"<b>{i}.</b> {a['title']}\n    <i>— {a.get('source',{}).get('name','')}</i>"
            for i, a in enumerate(articles[:count], 1)
        ])
    except Exception as e:
        return f"Could not fetch tech news: {e}"

def get_business_news(count=5):
    try:
        url = f"https://gnews.io/api/v4/top-headlines?topic=business&lang=en&max={count}&apikey={GNEWS_API_KEY}"
        res = requests.get(url, timeout=10).json()
        articles = res.get("articles", [])
        if not articles: return "No business news found."
        return "\n\n".join([
            f"<b>{i}.</b> {a['title']}\n    <i>— {a.get('source',{}).get('name','')}</i>"
            for i, a in enumerate(articles[:count], 1)
        ])
    except Exception as e:
        return f"Could not fetch business news: {e}"

def get_gold_silver():
    try:
        url      = "https://api.coinbase.com/v2/exchange-rates?currency=XAU"
        res      = requests.get(url, timeout=10).json()
        gold_10g = round(float(res["data"]["rates"]["INR"]) / 3.215, 2)
        url2     = "https://api.coinbase.com/v2/exchange-rates?currency=XAG"
        res2     = requests.get(url2, timeout=10).json()
        silver_kg = round(float(res2["data"]["rates"]["INR"]) * 32.15, 2)
        return f"🥇 <b>Gold:</b> ₹{gold_10g:,} / 10g\n🥈 <b>Silver:</b> ₹{silver_kg:,} / kg"
    except Exception as e:
        return f"Could not fetch gold/silver: {e}"

def get_market():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        s = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EBSESN?interval=1d&range=1d", headers=headers, timeout=10).json()
        n = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1d&range=1d",  headers=headers, timeout=10).json()
        sensex  = s["chart"]["result"][0]["meta"]["regularMarketPrice"]
        s_prev  = s["chart"]["result"][0]["meta"]["previousClose"]
        s_chg   = round(sensex - s_prev, 2)
        s_pct   = round((s_chg / s_prev) * 100, 2)
        nifty   = n["chart"]["result"][0]["meta"]["regularMarketPrice"]
        n_prev  = n["chart"]["result"][0]["meta"]["previousClose"]
        n_chg   = round(nifty - n_prev, 2)
        n_pct   = round((n_chg / n_prev) * 100, 2)
        return (
            f"📊 <b>Sensex:</b> {sensex:,.2f} {'▲' if s_chg>=0 else '▼'} {abs(s_chg)} ({abs(s_pct)}%)\n"
            f"📈 <b>Nifty:</b>  {nifty:,.2f} {'▲' if n_chg>=0 else '▼'} {abs(n_chg)} ({abs(n_pct)}%)"
        )
    except Exception as e:
        return f"Could not fetch market data: {e}"

# ============================================================
# PARSE SCHEDULE
# ============================================================
def parse_schedule_text(text):
    tasks   = []
    pattern = re.compile(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)|\d{1,2}\s*(?:AM|PM|am|pm))\s*[-–:]?\s*(.+)', re.IGNORECASE)
    for line in text.strip().split("\n"):
        line  = line.strip()
        if not line: continue
        match = pattern.search(line)
        if match:
            raw_time = match.group(1).strip().upper().replace(" ","")
            task_str = match.group(2).strip()
            try:
                t = datetime.strptime(raw_time, "%I:%M%p") if ":" in raw_time else datetime.strptime(raw_time, "%I%p")
                tasks.append({"time": t.strftime("%I:%M %p"), "task": task_str})
            except:
                parts = line.split(" ", 3)
                if len(parts) >= 3:
                    tasks.append({"time": f"{parts[0]} {parts[1]}", "task": " ".join(parts[2:])})
    return tasks

# ============================================================
# SEND HELPERS
# ============================================================
_app = None
def set_app(app): global _app; _app = app

def send_message_sync(chat_id, text):
    if _app is None: return
    asyncio.run_coroutine_threadsafe(
        _app.bot.send_message(chat_id=int(chat_id), text=text, parse_mode="HTML"), _app.loop)

def send_to_all_sync(text):
    for chat_id in load_json(USERS_FILE):
        try: send_message_sync(chat_id, text)
        except Exception as e: logger.error(f"Send error: {e}")

# ============================================================
# MORNING BRIEFING
# ============================================================
async def send_morning_briefing(bot, chat_id):
    name = load_json(USERS_FILE).get(str(chat_id), {}).get("name", "Sir")
    date = datetime.now().strftime('%d %b %Y')
    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        f"━━━━━━━━━━━━━━━━━━━\n🌅 <b>Good Morning, {name}!</b>\n📅 {date}\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"📰 <b>TOP 10 INDIA NEWS</b>\n\n{get_news('India', 10)}"
    ))
    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        f"━━━━━━━━━━━━━━━━━━━\n💹 <b>MARKET & PRICES</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_market()}\n\n{get_gold_silver()}"
    ))
    tech = get_tech_news(5); biz = get_business_news(5)
    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        f"━━━━━━━━━━━━━━━━━━━\n💻 <b>TECH NEWS</b>\n━━━━━━━━━━━━━━━━━━━\n\n{tech}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n💼 <b>BUSINESS NEWS</b>\n━━━━━━━━━━━━━━━━━━━\n\n{biz}"
    ))
    await send_etf_telegram(bot, chat_id, "Morning")
    await bot.send_message(chat_id=chat_id, parse_mode="HTML", text=(
        "━━━━━━━━━━━━━━━━━━━\n📅 <b>TODAY'S SCHEDULE</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        "What's your schedule for today?\n\n"
        "<b>Option 1 — Type it:</b>\n"
        "<code>9:00 AM Team meeting\n2:00 PM Client call\n5:00 PM Report</code>\n\n"
        "<b>Option 2 — Upload a .txt file</b>\n\n"
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
    for chat_id in load_json(USERS_FILE):
        try:
            asyncio.run_coroutine_threadsafe(
                send_morning_briefing(_app.bot, int(chat_id)), _app.loop)
        except Exception as e:
            logger.error(f"Morning job error: {e}")
    send_etf_email()

def job_market_open():
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n📈 <b>MARKET OPEN — 9:15 AM</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_market()}\n\n{get_gold_silver()}"
    )

def job_afternoon():
    tech = get_tech_news(5); biz = get_business_news(5)
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n☀️ <b>AFTERNOON UPDATE — 1:00 PM</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"💻 <b>Tech:</b>\n\n{tech}\n\n💼 <b>Business:</b>\n\n{biz}"
    )

def job_market_close():
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n🔔 <b>MARKET CLOSED — 3:30 PM</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_market()}\n\n{get_gold_silver()}"
    )
    for chat_id in load_json(USERS_FILE):
        try:
            asyncio.run_coroutine_threadsafe(
                send_etf_telegram(_app.bot, int(chat_id), "Market Close"), _app.loop)
        except Exception as e:
            logger.error(f"ETF close error: {e}")

def job_evening_news():
    send_to_all_sync(
        f"━━━━━━━━━━━━━━━━━━━\n🌍 <b>EVENING WORLD NEWS</b>\n"
        f"📅 {datetime.now().strftime('%d %b %Y')}\n━━━━━━━━━━━━━━━━━━━\n\n"
        f"{get_news('world', 10)}"
    )

def job_price_alerts():
    try:
        gs = get_gold_silver(); market = get_market()
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
                + "\n\n".join(alerts))
    except Exception as e:
        logger.error(f"Alert error: {e}")

def job_reminders():
    schedules = load_json(SCHEDULE_FILE); alerted = load_json(ALERTED_FILE)
    now = datetime.now(); today_key = now.strftime("%Y-%m-%d"); changed = False
    for chat_id, tasks in schedules.items():
        for task in tasks:
            try:
                task_time = datetime.strptime(task["time"], "%I:%M %p").replace(
                    year=now.year, month=now.month, day=now.day)
                alert_key = f"{chat_id}_{today_key}_{task['time']}_{task['task']}"
                if alerted.get(alert_key) or now >= task_time: continue
                mins_left = (task_time - now).total_seconds() / 60
                if mins_left <= 30:
                    send_message_sync(chat_id,
                        f"━━━━━━━━━━━━━━━━━━━\n⏰ <b>REMINDER!</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📌 <b>{task['task']}</b>\n🕐 At <b>{task['time']}</b>\n⏳ In <b>{int(mins_left)} minutes</b>")
                    alerted[alert_key] = True; changed = True
            except Exception as e:
                logger.error(f"Reminder error: {e}")
    if changed: save_json(ALERTED_FILE, alerted)

# ============================================================
# SAVE SCHEDULE
# ============================================================
async def save_and_confirm_schedule(update, chat_id, tasks):
    schedules = load_json(SCHEDULE_FILE); alerted = load_json(ALERTED_FILE)
    now = datetime.now(); today_key = now.strftime("%Y-%m-%d")
    schedules[chat_id] = tasks; save_json(SCHEDULE_FILE, schedules)
    lines_out = []; remind_msgs = []
    for t in tasks:
        lines_out.append(f"✅ <b>{t['time']}</b> — {t['task']}")
        try:
            task_time = datetime.strptime(t["time"], "%I:%M %p").replace(year=now.year, month=now.month, day=now.day)
            mins_left = (task_time - now).total_seconds() / 60
            alert_key = f"{chat_id}_{today_key}_{t['time']}_{t['task']}"
            if 0 < mins_left <= 30 and not alerted.get(alert_key):
                remind_msgs.append((t, int(mins_left), alert_key))
        except: pass
    await update.message.reply_text(
        f"📅 <b>Schedule saved!</b>\n\n" + "\n".join(lines_out) +
        "\n\n⏰ I'll remind you when each task is within 30 minutes!\nHave a productive day! 💪",
        parse_mode="HTML")
    for t, mins_left, alert_key in remind_msgs:
        await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━\n⚡ <b>IMMEDIATE REMINDER!</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <b>{t['task']}</b>\n🕐 At <b>{t['time']}</b>\n⏳ Only <b>{mins_left} minutes</b> away!",
            parse_mode="HTML")
        alerted[alert_key] = True
    save_json(ALERTED_FILE, alerted)
    waiting = load_json(WAITING_FILE); waiting.pop(chat_id, None); save_json(WAITING_FILE, waiting)

# ============================================================
# COMMANDS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    name    = update.effective_chat.first_name or "Sir"
    users   = load_json(USERS_FILE)
    users[chat_id] = {"name": name, "joined": str(datetime.now())}
    save_json(USERS_FILE, users)
    await update.message.reply_text(
        f"👋 <b>Welcome, {name}!</b>\n\nFetching your complete briefing now...",
        parse_mode="HTML")
    await send_morning_briefing(context.bot, int(chat_id))

async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    waiting = load_json(WAITING_FILE); waiting[chat_id] = True; save_json(WAITING_FILE, waiting)
    await update.message.reply_text(
        "📅 <b>Set your schedule</b>\n\n<b>Option 1 — Type it:</b>\n"
        "<code>9:00 AM Team meeting\n2:00 PM Client call\n5:00 PM Report</code>\n\n"
        "<b>Option 2 — Upload a .txt file</b>\n\n⏰ I'll remind you within <b>30 minutes</b>!",
        parse_mode="HTML")

async def cmd_view_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    tasks   = load_json(SCHEDULE_FILE).get(chat_id, [])
    if not tasks:
        await update.message.reply_text("No schedule saved. Use /schedule to set one."); return
    await update.message.reply_text(
        f"📅 <b>Your Schedule Today</b>\n\n" +
        "\n".join([f"⏰ <b>{t['time']}</b> — {t['task']}" for t in tasks]),
        parse_mode="HTML")

async def cmd_clear_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id   = str(update.effective_chat.id)
    schedules = load_json(SCHEDULE_FILE); alerted = load_json(ALERTED_FILE)
    schedules.pop(chat_id, None); save_json(SCHEDULE_FILE, schedules)
    today_key = datetime.now().strftime("%Y-%m-%d")
    for k in [k for k in alerted if k.startswith(f"{chat_id}_{today_key}")]: alerted.pop(k, None)
    save_json(ALERTED_FILE, alerted)
    await update.message.reply_text("✅ Schedule cleared!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text    = update.message.text.strip()
    waiting = load_json(WAITING_FILE)
    if waiting.get(chat_id):
        if text.lower() == "skip":
            waiting.pop(chat_id, None); save_json(WAITING_FILE, waiting)
            await update.message.reply_text("✅ No problem! See you tomorrow at 6 AM. Have a great day! 😊"); return
        tasks = parse_schedule_text(text)
        if tasks:
            await save_and_confirm_schedule(update, chat_id, tasks)
        else:
            await update.message.reply_text(
                "Could not read schedule. Use:\n\n"
                "<code>9:00 AM Team meeting\n2:00 PM Client call</code>\n\n"
                "Or type <b>skip</b>.", parse_mode="HTML")
        return
    await update.message.reply_text(
        "I send updates automatically every day at 6 AM! 😊\n\nUse /schedule to set today's reminders.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id  = str(update.effective_chat.id)
    document = update.message.document
    if not document: return
    if not (document.file_name or "").endswith(".txt"):
        await update.message.reply_text("⚠️ Please upload a <b>.txt</b> file only.", parse_mode="HTML"); return
    await update.message.reply_text("📂 Reading your schedule file...")
    try:
        file    = await context.bot.get_file(document.file_id)
        content = await file.download_as_bytearray()
        text    = content.decode("utf-8", errors="ignore")
        tasks   = parse_schedule_text(text)
        if tasks:
            waiting = load_json(WAITING_FILE); waiting[chat_id] = True; save_json(WAITING_FILE, waiting)
            await save_and_confirm_schedule(update, chat_id, tasks)
        else:
            await update.message.reply_text(
                "⚠️ Could not read tasks. Format:\n<code>9:00 AM Meeting</code>", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

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
    scheduler.add_job(job_morning,      "cron",     hour=6,  minute=0)
    scheduler.add_job(job_market_open,  "cron",     hour=9,  minute=15)
    scheduler.add_job(job_afternoon,    "cron",     hour=13, minute=0)
    scheduler.add_job(job_market_close, "cron",     hour=15, minute=30)
    scheduler.add_job(job_evening_news, "cron",     hour=19, minute=0)
    scheduler.add_job(job_price_alerts, "interval", minutes=5)
    scheduler.add_job(job_etf_alerts,   "interval", minutes=5)
    scheduler.add_job(job_reminders,    "interval", minutes=1)
    scheduler.start()

    logger.info("✅ Bot is running!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

# ============================================================
# REAL-TIME NEWS ALERTS — Google News RSS every 10 seconds
# ============================================================
import hashlib

# Keywords to monitor — add or remove as needed
NEWS_KEYWORDS = [
    "NSE block deal",
    "RBI repo rate",
    "ETF India",
    "Sensex crash",
    "Nifty fall",
    "gold price India",
    "real estate India",
    "home loan rate",
    "RERA India",
    "property prices Noida",
    "stock market crash India",
    "mutual fund India",
]

SENT_NEWS_FILE = "sent_news.json"

def load_sent_news():
    if os.path.exists(SENT_NEWS_FILE):
        with open(SENT_NEWS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_sent_news(data):
    with open(SENT_NEWS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_news_hash(title, link):
    return hashlib.md5(f"{title}{link}".encode()).hexdigest()

def fetch_google_news_rss(keyword):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        query   = requests.utils.quote(keyword)
        url     = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=5&enableFuzzyQuery=false"
        res     = requests.get(url, headers=headers, timeout=10).json()
        news    = res.get("news", [])
        result  = []
        for a in news:
            result.append({
                "title":     a.get("title", ""),
                "link":      a.get("link", ""),
                "published": str(a.get("providerPublishTime", "")),
                "source":    a.get("publisher", "Yahoo Finance"),
                "keyword":   keyword
            })
        return result
    except Exception as e:
        logger.error(f"News fetch error for {keyword}: {e}")
        return []

def send_news_alert_email(articles):
    try:
        date = datetime.now().strftime("%d %b %Y %I:%M %p")

        def rows():
            html = ""
            for a in articles:
                html += f"""
                <tr>
                    <td style="padding:12px 10px;border-bottom:0.5px solid #eee">
                        <b style="color:#1a1a2e;font-size:13px">{a['title']}</b><br>
                        <span style="font-size:11px;color:#888">{a['source']} · {a['published'][:20] if a['published'] else ''}</span><br>
                        <span style="font-size:11px;background:#fff0f0;color:#c0392b;padding:2px 8px;border-radius:4px;display:inline-block;margin-top:4px">🔍 Keyword: {a['keyword']}</span><br>
                        <a href="{a['link']}" style="font-size:12px;color:#3498db;margin-top:4px;display:inline-block">Read full article →</a>
                    </td>
                </tr>"""
            return html

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:Arial,sans-serif;background:#f4f6f9;margin:0;padding:20px}}
.container{{max-width:650px;margin:auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1)}}
.header{{background:linear-gradient(135deg,#c0392b,#e74c3c);color:white;padding:25px;text-align:center}}
.header h1{{margin:0;font-size:20px}}
.header p{{margin:6px 0 0;opacity:.85;font-size:13px}}
.section{{padding:20px}}
table{{width:100%;border-collapse:collapse}}
.footer{{background:#f8f9fa;padding:16px;text-align:center;font-size:11px;color:#888;border-top:1px solid #eee}}
</style></head><body>
<div class="container">
<div class="header">
  <h1>🔴 Breaking News Alert</h1>
  <p>⏰ {date} IST · Real-time keyword match detected</p>
</div>
<div class="section">
  <table><tbody>{rows()}</tbody></table>
</div>
<div class="footer">
  <p>🤖 <b>AmitDailyUpdatesBot</b> · Real-time news monitoring · Checks every 10 seconds</p>
</div>
</div></body></html>"""

        msg            = MIMEMultipart("alternative")
        msg["Subject"] = f"🔴 Breaking News Alert — {articles[0]['keyword']} — {datetime.now().strftime('%d %b %Y %I:%M %p')}"
        msg["From"]    = SENDER_EMAIL
        msg["To"]      = ", ".join(RECIPIENTS)
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

        logger.info(f"✅ News alert email sent for: {articles[0]['keyword']}")
    except Exception as e:
        logger.error(f"News alert email error: {e}")

def job_realtime_news():
    sent_news = {}  # TEST MODE
    new_articles = []

    for keyword in NEWS_KEYWORDS:
        articles = fetch_google_news_rss(keyword)
        for article in articles:
            news_hash = get_news_hash(article["title"], article["link"])
            if not sent_news.get(news_hash):
                new_articles.append(article)
                sent_news[news_hash] = True

                # Send Telegram alert immediately
                msg = (
                    f"🔴 <b>BREAKING NEWS ALERT!</b>\n"
                    f"🔍 Keyword: <b>{keyword}</b>\n\n"
                    f"<b>{article['title']}</b>\n\n"
                    f"<i>— {article['source']}</i>\n\n"
                    f"<a href='{article['link']}'>Read full article →</a>"
                )
                send_to_all_sync(msg)

    if new_articles:
        save_sent_news(sent_news)
        # Send one combined email for all new articles
        send_news_alert_email(new_articles)

    # Clean old entries — keep only last 1000 to prevent file bloat
    if len(sent_news) > 1000:
        keys = list(sent_news.keys())
        trimmed = {k: sent_news[k] for k in keys[-1000:]}
        save_sent_news(trimmed)
