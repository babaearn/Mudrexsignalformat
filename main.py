"""
🚀 MUDREX TRADING SIGNAL BOT v2.1
==================================
Complete Telegram bot for posting crypto trading signals
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import Conflict, NetworkError

# ============== CONFIGURATION ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1002163454656")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]

# URLs
DEFAULT_TRADE_URL_BASE = os.environ.get("TRADE_URL_BASE", "https://mudrex.com/trade/")
LEADERBOARD_URL = os.environ.get("LEADERBOARD_URL", "https://t.me/officialmudrex/98446/99620")
CHALLENGE_URL = os.environ.get("CHALLENGE_URL", "https://t.me/officialmudrex/98446/98616")

# Railway URL for click tracking
RAILWAY_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", os.environ.get("RAILWAY_STATIC_URL", ""))
PORT = int(os.environ.get("PORT", 8080))

# Database file path
DB_PATH = Path("/app/data/database.json") if os.path.exists("/app") else Path("database.json")

# Logging - Only show warnings and errors, not info
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

# Conversation states
WAITING_FOR_CREATIVE = 1
WAITING_FOR_CONFIRM = 2
WAITING_FOR_FIX_CREATIVE = 3
WAITING_FOR_FORMAT = 4

# IST Timezone
IST = ZoneInfo("Asia/Kolkata")

# ============== DATABASE ==============
DEFAULT_DB = {
    "creatives": {},
    "deeplinks": {},
    "signals": {},
    "clicks": {},
    "post_clicks": {},
    "last_signal": None,
    "signal_counter": 0,
    "stats": {
        "total_signals": 0,
        "first_signal_date": None,
        "last_signal_date": None
    },
    "settings": {
        "click_tracking": False,
        "signal_format": None
    }
}

def load_db():
    """Load database from JSON file"""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DB_PATH.exists():
            with open(DB_PATH, 'r') as f:
                db = json.load(f)
                for key in DEFAULT_DB:
                    if key not in db:
                        db[key] = DEFAULT_DB[key]
                return db
    except Exception as e:
        logger.error(f"DB load error: {e}")
    return DEFAULT_DB.copy()

def save_db(db):
    """Save database to JSON file"""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DB_PATH, 'w') as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        logger.error(f"DB save error: {e}")

# Global database
db = load_db()

# Pending signals storage
pending_signals = {}

# ============== DEFAULT SIGNAL FORMAT ==============
DEFAULT_FORMAT = """🏆 <a href="{challenge_url}">EXCLUSIVE TG TRADE CHALLENGE</a>

🚨 NEW CRYPTO TRADE ALERT {direction_emoji}🔥

🔹 TRADE: {ticker} {direction}
🔹 Pair: {ticker}/USDT
🔹 Risk: HIGH
🔹 Leverage: {leverage}x
🔹 Risk Reward Ratio: 1:2

🕰️ Holding time: {holding_time}

🔸 Entry 1: ${entry1}
🔸 Entry 2: ${entry2}

🎯 Take Profit (TP) 1: ${tp1}
🎯 Take Profit (TP) 2: ${tp2}

🛑 Stop Loss (SL): ${sl}

⚠️ Disclaimer: Crypto assets are unregulated and extremely volatile. Losses are possible, and no regulatory recourse is available. Always DYOR before taking any trade.

<a href="{leaderboard_url}">CHECK THE LEADERBOARD 🚀</a>"""


# ============== HELPER FUNCTIONS ==============

def get_ist_timestamp() -> str:
    now = datetime.now(IST)
    return now.strftime("%d %b %Y, %I:%M %p")

def get_ist_date() -> str:
    now = datetime.now(IST)
    return now.strftime("%d %b %Y")

def get_month_key() -> str:
    now = datetime.now(IST)
    return now.strftime("%Y-%m")

def get_signal_number() -> str:
    global db
    db["signal_counter"] = db.get("signal_counter", 0) + 1
    save_db(db)
    return f"{db['signal_counter']:03d}"

def format_price(price: float) -> str:
    if price >= 1000:
        return f"{price:.2f}"
    elif price >= 100:
        return f"{price:.2f}"
    elif price >= 10:
        return f"{price:.4f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.5f}"
    else:
        return f"{price:.8f}".rstrip('0').rstrip('.')

def calculate_signal(ticker: str, entry1: float, sl: float, leverage: int = None) -> dict:
    direction = "LONG" if sl < entry1 else "SHORT"
    direction_emoji = "📈" if direction == "LONG" else "📉"
    
    entry2 = (entry1 + sl) / 2
    avg_entry = (entry1 + entry2) / 2
    risk = abs(avg_entry - sl)
    
    if direction == "LONG":
        tp1 = avg_entry + risk
        tp2 = avg_entry + (2 * risk)
    else:
        tp1 = avg_entry - risk
        tp2 = avg_entry - (2 * risk)
    
    sl_percent = (risk / avg_entry) * 100
    
    if leverage is None:
        if sl_percent > 30:
            leverage = 2
        elif sl_percent < 10:
            leverage = 5
        elif sl_percent >= 20:
            leverage = 3
        else:
            leverage = 4
    
    if sl_percent <= 5:
        holding_time = "1–2 days"
    elif sl_percent <= 8:
        holding_time = "2–3 days"
    else:
        holding_time = "5–7 days"
    
    if direction == "LONG":
        potential_profit = ((tp2 - avg_entry) / avg_entry) * 100 * leverage
    else:
        potential_profit = ((avg_entry - tp2) / avg_entry) * 100 * leverage
    
    return {
        "ticker": ticker.upper(),
        "direction": direction,
        "direction_emoji": direction_emoji,
        "entry1": format_price(entry1),
        "entry2": format_price(entry2),
        "avg_entry": format_price(avg_entry),
        "tp1": format_price(tp1),
        "tp2": format_price(tp2),
        "sl": format_price(sl),
        "leverage": leverage,
        "holding_time": holding_time,
        "potential_profit": f"{potential_profit:.2f}%",
        "challenge_url": CHALLENGE_URL,
        "leaderboard_url": LEADERBOARD_URL,
        "raw_entry1": entry1,
        "raw_entry2": entry2,
        "raw_avg_entry": avg_entry,
        "raw_tp1": tp1,
        "raw_tp2": tp2,
        "raw_sl": sl,
    }

def generate_signal_text(signal_data: dict) -> str:
    template = db["settings"].get("signal_format") or DEFAULT_FORMAT
    return template.format(**signal_data)

def generate_figma_prompt(signal_data: dict) -> str:
    timestamp = get_ist_timestamp()
    
    return f"""```
📋 FIGMA AGENT INSTRUCTIONS

Within the selected frame in Figma, update the following text fields using the provided input data.
Do not alter any design, style, font, alignment, colors, sizing, or auto-layout settings—change only the text content.

Asset Name: {signal_data['ticker']}
Direction: {signal_data['direction']}
Leverage: {signal_data['leverage']}x
Entry Price: ${signal_data['entry1']} – ${signal_data['entry2']}
TP1: ${signal_data['tp1']}
TP2: ${signal_data['tp2']}
SL: ${signal_data['sl']}
Profit: {signal_data['potential_profit']}
Published On: {timestamp}

Instructions:
• For each field above, locate the corresponding text box in the selected frame and replace its content with the provided value.
• Do not modify any visual design or layout properties.
• Review and confirm all updates before saving.
```"""

def generate_summary_box(signal_data: dict) -> str:
    timestamp = get_ist_timestamp()
    
    return f"""```
📊 SUMMARY BOX

Entry 1: ${signal_data['entry1']}
Entry 2: ${signal_data['entry2']}
Average Entry: ${signal_data['avg_entry']}
TP1: ${signal_data['tp1']}
TP2: ${signal_data['tp2']}
SL: ${signal_data['sl']}
⏰ Published On: {timestamp}
Potential Profit: {signal_data['potential_profit']}
```"""

def get_trade_url(ticker: str, signal_id: str, custom_url: str = None) -> str:
    global db
    
    if custom_url:
        actual_url = custom_url
        db["deeplinks"][ticker.upper()] = custom_url
        save_db(db)
    elif ticker.upper() in db["deeplinks"]:
        actual_url = db["deeplinks"][ticker.upper()]
    else:
        actual_url = f"{DEFAULT_TRADE_URL_BASE}{ticker.upper()}-USDT"
    
    if db["settings"].get("click_tracking") and RAILWAY_URL:
        return f"https://{RAILWAY_URL}/track/{signal_id}"
    
    return actual_url

def record_signal(signal_id: str, ticker: str, direction: str, message_id: int):
    global db
    
    month_key = get_month_key()
    date_str = get_ist_date()
    timestamp = datetime.now(IST).isoformat()
    
    if month_key not in db["signals"]:
        db["signals"][month_key] = []
    
    signal_record = {
        "signal_id": signal_id,
        "ticker": ticker,
        "direction": direction,
        "date": date_str,
        "message_id": message_id,
        "timestamp": timestamp
    }
    
    db["signals"][month_key].append(signal_record)
    db["stats"]["total_signals"] += 1
    db["stats"]["last_signal_date"] = date_str
    
    if not db["stats"]["first_signal_date"]:
        db["stats"]["first_signal_date"] = date_str
    
    db["last_signal"] = {
        "signal_id": signal_id,
        "message_id": message_id,
        "ticker": ticker,
        "direction": direction,
        "date": date_str
    }
    
    db["post_clicks"][signal_id] = {
        "ticker": ticker,
        "direction": direction,
        "date": date_str,
        "clicks": 0
    }
    
    save_db(db)

def record_click(signal_id: str):
    global db
    
    now = datetime.now(IST)
    date_key = now.strftime("%Y-%m-%d")
    
    if signal_id in db["post_clicks"]:
        db["post_clicks"][signal_id]["clicks"] += 1
        ticker = db["post_clicks"][signal_id]["ticker"]
    else:
        ticker = signal_id
    
    if "clicks" not in db:
        db["clicks"] = {}
    
    if ticker not in db["clicks"]:
        db["clicks"][ticker] = {}
    
    if date_key not in db["clicks"][ticker]:
        db["clicks"][ticker][date_key] = 0
    
    db["clicks"][ticker][date_key] += 1
    save_db(db)

def get_click_stats(ticker: str = None, period: str = None) -> dict:
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    three_months_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    six_months_ago = (now - timedelta(days=180)).strftime("%Y-%m-%d")
    year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    
    stats = {
        "total": 0, "today": 0, "week": 0, "month": 0,
        "3month": 0, "6month": 0, "year": 0, "by_ticker": {}
    }
    
    clicks_data = db.get("clicks", {})
    
    for t, dates in clicks_data.items():
        if ticker and t != ticker.upper():
            continue
            
        ticker_total = 0
        for date_key, count in dates.items():
            ticker_total += count
            stats["total"] += count
            
            if date_key >= today:
                stats["today"] += count
            if date_key >= week_ago:
                stats["week"] += count
            if date_key >= month_ago:
                stats["month"] += count
            if date_key >= three_months_ago:
                stats["3month"] += count
            if date_key >= six_months_ago:
                stats["6month"] += count
            if date_key >= year_ago:
                stats["year"] += count
        
        if not ticker:
            stats["by_ticker"][t] = ticker_total
    
    return stats

def get_post_click_stats(limit: int = 10, ticker_filter: str = None) -> dict:
    posts = []
    total_clicks = 0
    
    for signal_id, data in db.get("post_clicks", {}).items():
        if ticker_filter and data.get("ticker") != ticker_filter.upper():
            continue
        
        posts.append({
            "signal_id": signal_id,
            "ticker": data.get("ticker", "N/A"),
            "direction": data.get("direction", "N/A"),
            "date": data.get("date", "N/A"),
            "clicks": data.get("clicks", 0)
        })
        total_clicks += data.get("clicks", 0)
    
    posts.sort(key=lambda x: x["signal_id"], reverse=True)
    avg_clicks = total_clicks / len(posts) if posts else 0
    
    return {
        "posts": posts[:limit],
        "total_posts": len(posts),
        "total_clicks": total_clicks,
        "avg_clicks": avg_clicks
    }

def parse_month(text: str) -> str:
    months = {
        "jan": "01", "january": "01", "feb": "02", "february": "02",
        "mar": "03", "march": "03", "apr": "04", "april": "04",
        "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
        "aug": "08", "august": "08", "sep": "09", "september": "09",
        "oct": "10", "october": "10", "nov": "11", "november": "11",
        "dec": "12", "december": "12"
    }
    
    text_lower = text.lower().strip()
    if text_lower in months:
        year = datetime.now(IST).year
        month = months[text_lower]
        current_month = datetime.now(IST).month
        if int(month) > current_month:
            year -= 1
        return f"{year}-{month}"
    return None

def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


# ============== ERROR HANDLER ==============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors - suppress common deployment conflicts"""
    if isinstance(context.error, Conflict):
        # Normal during deployment - ignore
        return
    if isinstance(context.error, NetworkError):
        # Network hiccup - ignore
        return
    logger.error(f"Error: {context.error}")


# ============== COMMAND HANDLERS ==============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """🚀 <b>MUDREX SIGNAL BOT v2.1</b>

<b>━━━━ SIGNALS ━━━━</b>
<code>signal [TICKER] [ENTRY] [SL] [LEV] [link]</code>
Example: <code>signal SOL 125 115 3x</code>

<code>delete</code> - Delete last signal

<b>━━━━ CREATIVES ━━━━</b>
<code>fix1</code>, <code>fix2</code>... - Save creative
<code>list</code> - Show saved creatives
<code>clearfix 1</code> / <code>clearfix all</code>

<b>━━━━ DEEPLINKS ━━━━</b>
<code>links</code> - Show saved links
<code>clearlink SOL</code> / <code>clearlink all</code>

<b>━━━━ CLICK TRACKING ━━━━</b>
<code>clickon</code> / <code>clickoff</code> - Toggle tracking
<code>clicks</code> - Overall stats
<code>clicks SOL</code> - Ticker stats
<code>clicks today/week/month</code>
<code>clicks 3month/6month/year</code>

<b>━━━━ POST ANALYTICS ━━━━</b>
<code>postclicks</code> - Clicks per post
<code>postclicks 20</code> - Last 20 posts
<code>postclicks SOL</code> - Filter by ticker

<b>━━━━ SIGNAL ANALYTICS ━━━━</b>
<code>stats</code> - Overall statistics
<code>jan/feb/mar...</code> - Monthly stats

<b>━━━━ OTHER ━━━━</b>
<code>format</code> - Change template
<code>help</code> - This guide
<code>cancel</code> - Cancel operation

<i>💡 Commands work with or without /</i>"""
    
    await update.message.reply_text(help_text, parse_mode="HTML")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_signals
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    
    text = update.message.text
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    if len(parts) < 5:
        await update.message.reply_text(
            "❌ Invalid format!\n\n"
            "Use: <code>signal TICKER ENTRY SL LEVERAGE [link]</code>\n"
            "Example: <code>signal SOL 125 115 3x</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    try:
        ticker = parts[1].upper()
        entry1 = float(parts[2])
        sl = float(parts[3])
        leverage = int(parts[4].lower().replace('x', ''))
        
        custom_url = None
        if len(parts) >= 6 and parts[5].startswith('http'):
            custom_url = parts[5]
        
        signal_id = get_signal_number()
        
        signal_data = calculate_signal(ticker, entry1, sl, leverage)
        signal_data['signal_id'] = signal_id
        signal_data['trade_url'] = get_trade_url(ticker, signal_id, custom_url)
        
        pending_signals[user_id] = {
            "signal_data": signal_data,
            "custom_url": custom_url,
            "signal_id": signal_id
        }
        
        saved_link_msg = ""
        if not custom_url and ticker in db["deeplinks"]:
            saved_link_msg = f"\n🔗 Using saved link for {ticker}"
        elif custom_url:
            saved_link_msg = f"\n💾 Deeplink saved for {ticker}"
        
        creative_list = ""
        if db["creatives"]:
            creative_list = "\n\n📁 Saved: " + ", ".join(sorted(db["creatives"].keys()))
        
        await update.message.reply_text(
            f"📊 <b>Signal #{signal_id}</b>\n\n"
            f"• Ticker: {signal_data['ticker']} {signal_data['direction']}\n"
            f"• Entry1: ${signal_data['entry1']}\n"
            f"• Entry2: ${signal_data['entry2']}\n"
            f"• TP1: ${signal_data['tp1']}\n"
            f"• TP2: ${signal_data['tp2']}\n"
            f"• SL: ${signal_data['sl']}\n"
            f"• Leverage: {signal_data['leverage']}x"
            f"{saved_link_msg}\n\n"
            f"🖼️ Drop creative or type <code>use fix1</code>"
            f"{creative_list}",
            parse_mode="HTML"
        )
        
        return WAITING_FOR_CREATIVE
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Signal error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def receive_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_signals
    
    user_id = update.effective_user.id
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal. Use <code>signal</code> first.", parse_mode="HTML")
        return ConversationHandler.END
    
    if update.message.text:
        text = update.message.text.lower().strip()
        if text.startswith("use fix"):
            fix_key = text.replace("use ", "")
            if fix_key in db["creatives"]:
                pending_signals[user_id]["creative_file_id"] = db["creatives"][fix_key]
            else:
                await update.message.reply_text(f"❌ '{fix_key}' not found.", parse_mode="HTML")
                return WAITING_FOR_CREATIVE
        else:
            await update.message.reply_text("❌ Send image or type <code>use fix1</code>", parse_mode="HTML")
            return WAITING_FOR_CREATIVE
    elif update.message.photo:
        pending_signals[user_id]["creative_file_id"] = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("❌ Send image or type <code>use fix1</code>", parse_mode="HTML")
        return WAITING_FOR_CREATIVE
    
    signal_data = pending_signals[user_id]["signal_data"]
    signal_text = generate_signal_text(signal_data)
    creative_file_id = pending_signals[user_id]["creative_file_id"]
    
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=signal_data['trade_url'])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(f"📊 <b>PREVIEW - Signal #{signal_data['signal_id']}</b>", parse_mode="HTML")
    
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=creative_file_id,
        caption=signal_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    await update.message.reply_text(
        "Type <code>send now</code> to post or <code>cancel</code>",
        parse_mode="HTML"
    )
    
    return WAITING_FOR_CONFIRM

async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_signals, db
    
    user_id = update.effective_user.id
    text = update.message.text.lower().strip()
    
    if text == "cancel":
        pending_signals.pop(user_id, None)
        await update.message.reply_text("❌ Cancelled.")
        return ConversationHandler.END
    
    if text != "send now":
        await update.message.reply_text("Type <code>send now</code> or <code>cancel</code>", parse_mode="HTML")
        return WAITING_FOR_CONFIRM
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal.")
        return ConversationHandler.END
    
    signal_data = pending_signals[user_id]["signal_data"]
    creative_file_id = pending_signals[user_id]["creative_file_id"]
    signal_id = pending_signals[user_id]["signal_id"]
    signal_text = generate_signal_text(signal_data)
    
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=signal_data['trade_url'])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        sent_message = await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=creative_file_id,
            caption=signal_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        record_signal(signal_id, signal_data['ticker'], signal_data['direction'], sent_message.message_id)
        
        await update.message.reply_text(f"✅ <b>Signal #{signal_id} posted!</b>", parse_mode="HTML")
        
        figma_prompt = generate_figma_prompt(signal_data)
        await update.message.reply_text(figma_prompt, parse_mode="Markdown")
        
        summary = generate_summary_box(signal_data)
        await update.message.reply_text(summary, parse_mode="Markdown")
        
        pending_signals.pop(user_id, None)
        
        logger.info(f"Signal #{signal_id} posted: {signal_data['ticker']} {signal_data['direction']}")
        
    except Exception as e:
        logger.error(f"Post error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
    
    return ConversationHandler.END

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    if not db.get("last_signal"):
        await update.message.reply_text("❌ No signal to delete.")
        return
    
    try:
        await context.bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=db["last_signal"]["message_id"]
        )
        
        signal_id = db["last_signal"].get("signal_id", "N/A")
        ticker = db["last_signal"]["ticker"]
        db["last_signal"] = None
        db["stats"]["total_signals"] = max(0, db["stats"]["total_signals"] - 1)
        save_db(db)
        
        await update.message.reply_text(f"✅ Deleted Signal #{signal_id} ({ticker})")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    fix_key = text
    context.user_data["pending_fix_key"] = fix_key
    
    await update.message.reply_text(f"🖼️ Drop image to save as <code>{fix_key}</code>", parse_mode="HTML")
    return WAITING_FOR_FIX_CREATIVE

async def receive_fix_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not update.message.photo:
        await update.message.reply_text("❌ Send an image.")
        return WAITING_FOR_FIX_CREATIVE
    
    fix_key = context.user_data.get("pending_fix_key", "fix1")
    db["creatives"][fix_key] = update.message.photo[-1].file_id
    save_db(db)
    
    await update.message.reply_text(f"✅ Saved as <code>{fix_key}</code>", parse_mode="HTML")
    return ConversationHandler.END

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db["creatives"]:
        await update.message.reply_text("📭 No saved creatives.", parse_mode="HTML")
        return
    
    creative_list = "\n".join([f"  • {k}" for k in sorted(db["creatives"].keys())])
    await update.message.reply_text(
        f"🖼️ <b>Saved Creatives</b>\n\n{creative_list}\n\nTotal: {len(db['creatives'])}",
        parse_mode="HTML"
    )

async def clearfix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    if len(parts) < 2:
        await update.message.reply_text("Use: <code>clearfix 1</code> or <code>clearfix all</code>", parse_mode="HTML")
        return
    
    target = parts[1]
    
    if target == "all":
        count = len(db["creatives"])
        db["creatives"] = {}
        save_db(db)
        await update.message.reply_text(f"✅ Deleted {count} creatives.")
    else:
        fix_key = f"fix{target}"
        if fix_key in db["creatives"]:
            del db["creatives"][fix_key]
            save_db(db)
            await update.message.reply_text(f"✅ Deleted {fix_key}")
        else:
            await update.message.reply_text(f"❌ {fix_key} not found.")

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db["deeplinks"]:
        await update.message.reply_text("📭 No saved deeplinks.", parse_mode="HTML")
        return
    
    links_list = "\n".join([f"  • <b>{k}</b> → {v}" for k, v in sorted(db["deeplinks"].items())])
    await update.message.reply_text(
        f"🔗 <b>Saved Deeplinks</b>\n\n{links_list}\n\nTotal: {len(db['deeplinks'])}",
        parse_mode="HTML"
    )

async def clearlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    if len(parts) < 2:
        await update.message.reply_text("Use: <code>clearlink SOL</code> or <code>clearlink all</code>", parse_mode="HTML")
        return
    
    target = parts[1].upper()
    
    if target == "ALL":
        count = len(db["deeplinks"])
        db["deeplinks"] = {}
        save_db(db)
        await update.message.reply_text(f"✅ Deleted {count} deeplinks.")
    else:
        if target in db["deeplinks"]:
            del db["deeplinks"][target]
            save_db(db)
            await update.message.reply_text(f"✅ Deleted {target}")
        else:
            await update.message.reply_text(f"❌ {target} not found.")

async def clickon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    if not RAILWAY_URL:
        await update.message.reply_text(
            "❌ Click tracking requires domain.\n\nRailway → Settings → Networking → Generate Domain",
            parse_mode="HTML"
        )
        return
    
    db["settings"]["click_tracking"] = True
    save_db(db)
    await update.message.reply_text("✅ Click tracking <b>ON</b>", parse_mode="HTML")

async def clickoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    db["settings"]["click_tracking"] = False
    save_db(db)
    await update.message.reply_text("✅ Click tracking <b>OFF</b>", parse_mode="HTML")

async def clicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    ticker = None
    period = None
    
    if len(parts) >= 2:
        arg = parts[1].lower()
        if arg in ["today", "week", "month", "3month", "6month", "year"]:
            period = arg
        else:
            ticker = arg.upper()
    
    stats = get_click_stats(ticker)
    tracking_status = "✅ ON" if db["settings"].get("click_tracking") else "❌ OFF"
    
    if ticker:
        await update.message.reply_text(
            f"📊 <b>{ticker} Clicks</b>\n\n"
            f"Total: {stats['total']}\n\n"
            f"Today: {stats['today']}\n"
            f"Week: {stats['week']}\n"
            f"Month: {stats['month']}\n"
            f"3 Months: {stats['3month']}\n"
            f"6 Months: {stats['6month']}\n"
            f"Year: {stats['year']}\n\n"
            f"Tracking: {tracking_status}",
            parse_mode="HTML"
        )
    elif period:
        period_names = {
            "today": "Today", "week": "This Week", "month": "This Month",
            "3month": "3 Months", "6month": "6 Months", "year": "1 Year"
        }
        await update.message.reply_text(
            f"📊 <b>{period_names[period]} Clicks</b>\n\nTotal: {stats[period]}\n\nTracking: {tracking_status}",
            parse_mode="HTML"
        )
    else:
        top_tickers = sorted(stats["by_ticker"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_list = "\n".join([f"  {i+1}. {t} — {c}" for i, (t, c) in enumerate(top_tickers)]) or "  No data"
        
        await update.message.reply_text(
            f"📊 <b>Click Statistics</b>\n\n"
            f"Total: {stats['total']}\n\n"
            f"Today: {stats['today']}\n"
            f"Week: {stats['week']}\n"
            f"Month: {stats['month']}\n"
            f"3 Months: {stats['3month']}\n"
            f"6 Months: {stats['6month']}\n"
            f"Year: {stats['year']}\n\n"
            f"<b>Top Tickers</b>\n{top_list}\n\n"
            f"Tracking: {tracking_status}",
            parse_mode="HTML"
        )

async def postclicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    limit = 10
    ticker_filter = None
    
    if len(parts) >= 2:
        arg = parts[1]
        if arg.isdigit():
            limit = int(arg)
        else:
            ticker_filter = arg.upper()
    
    stats = get_post_click_stats(limit, ticker_filter)
    tracking_status = "✅ ON" if db["settings"].get("click_tracking") else "❌ OFF"
    
    if not stats["posts"]:
        await update.message.reply_text("📭 No post data yet.", parse_mode="HTML")
        return
    
    post_lines = []
    for post in stats["posts"]:
        post_lines.append(
            f"  #{post['signal_id']} {post['ticker']} {post['direction']}\n"
            f"      {post['date']} — <b>{post['clicks']} clicks</b>"
        )
    
    post_list = "\n\n".join(post_lines)
    title = f"Post Clicks" if not ticker_filter else f"{ticker_filter} Posts"
    
    await update.message.reply_text(
        f"📊 <b>{title}</b>\n\n"
        f"{post_list}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Total Posts: {stats['total_posts']}\n"
        f"Total Clicks: {stats['total_clicks']}\n"
        f"Avg per Post: {stats['avg_clicks']:.1f}\n\n"
        f"Tracking: {tracking_status}",
        parse_mode="HTML"
    )

async def clearclicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    db["clicks"] = {}
    db["post_clicks"] = {}
    save_db(db)
    await update.message.reply_text("✅ All click data cleared.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = db["stats"]["total_signals"]
    first_date = db["stats"]["first_signal_date"] or "N/A"
    last_date = db["stats"]["last_signal_date"] or "N/A"
    
    long_count = 0
    short_count = 0
    ticker_counts = {}
    
    for month, signals in db["signals"].items():
        for signal in signals:
            if signal["direction"] == "LONG":
                long_count += 1
            else:
                short_count += 1
            ticker = signal["ticker"]
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    
    long_pct = (long_count / total * 100) if total > 0 else 0
    short_pct = (short_count / total * 100) if total > 0 else 0
    
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_list = "\n".join([f"  {i+1}. {t} — {c} signals" for i, (t, c) in enumerate(top_tickers)]) or "  No data"
    
    await update.message.reply_text(
        f"📊 <b>Signal Statistics</b>\n\n"
        f"Total: {total}\n"
        f"🟢 LONG: {long_count} ({long_pct:.1f}%)\n"
        f"🔴 SHORT: {short_count} ({short_pct:.1f}%)\n\n"
        f"Started: {first_date}\n"
        f"Last: {last_date}\n\n"
        f"<b>Top Tickers</b>\n{top_list}",
        parse_mode="HTML"
    )

async def month_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    month_key = parse_month(text)
    
    if not month_key:
        await update.message.reply_text("❌ Invalid month.")
        return
    
    signals = db["signals"].get(month_key, [])
    total = len(signals)
    
    if total == 0:
        await update.message.reply_text(f"📭 No signals for {text.upper()}.")
        return
    
    long_count = sum(1 for s in signals if s["direction"] == "LONG")
    short_count = total - long_count
    long_pct = (long_count / total * 100) if total > 0 else 0
    short_pct = (short_count / total * 100) if total > 0 else 0
    
    ticker_counts = {}
    for signal in signals:
        ticker = signal["ticker"]
        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_list = "\n".join([f"  {i+1}. {t} — {c}" for i, (t, c) in enumerate(top_tickers)])
    
    month_name = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
    
    await update.message.reply_text(
        f"📊 <b>{month_name}</b>\n\n"
        f"Total: {total}\n"
        f"🟢 LONG: {long_count} ({long_pct:.1f}%)\n"
        f"🔴 SHORT: {short_count} ({short_pct:.1f}%)\n\n"
        f"<b>Top Tickers</b>\n{top_list}",
        parse_mode="HTML"
    )

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 <b>Send new format template</b>\n\n"
        "Placeholders: {ticker}, {direction}, {direction_emoji}, "
        "{leverage}, {holding_time}, {entry1}, {entry2}, {tp1}, {tp2}, "
        "{sl}, {avg_entry}, {potential_profit}, {challenge_url}, {leaderboard_url}\n\n"
        "Send <code>reset</code> for default.",
        parse_mode="HTML"
    )
    return WAITING_FOR_FORMAT

async def receive_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db
    
    text = update.message.text
    
    if text.lower().strip() == "reset":
        db["settings"]["signal_format"] = None
        save_db(db)
        await update.message.reply_text("✅ Format reset!")
    else:
        db["settings"]["signal_format"] = text
        save_db(db)
        await update.message.reply_text("✅ Format saved!")
    
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_signals
    user_id = update.effective_user.id
    pending_signals.pop(user_id, None)
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    
    if text.startswith("signal "):
        return await signal_command(update, context)
    elif text == "delete":
        return await delete_command(update, context)
    elif text.startswith("fix") and len(text) > 3 and text[3:].isdigit():
        return await fix_command(update, context)
    elif text == "list":
        return await list_command(update, context)
    elif text.startswith("clearfix"):
        return await clearfix_command(update, context)
    elif text == "links":
        return await links_command(update, context)
    elif text.startswith("clearlink"):
        return await clearlink_command(update, context)
    elif text == "clickon":
        return await clickon_command(update, context)
    elif text == "clickoff":
        return await clickoff_command(update, context)
    elif text.startswith("clicks"):
        return await clicks_command(update, context)
    elif text.startswith("postclicks"):
        return await postclicks_command(update, context)
    elif text == "clearclicks":
        return await clearclicks_command(update, context)
    elif text == "stats":
        return await stats_command(update, context)
    elif text == "format":
        return await format_command(update, context)
    elif text in ["help", "start"]:
        return await help_command(update, context)
    elif text == "cancel":
        return await cancel_command(update, context)
    elif parse_month(text):
        return await month_stats_command(update, context)


# ============== WEB SERVER FOR CLICK TRACKING ==============

async def handle_track(request):
    signal_id = request.match_info.get('signal_id', '').upper()
    
    record_click(signal_id)
    
    if signal_id in db.get("post_clicks", {}):
        ticker = db["post_clicks"][signal_id].get("ticker", "")
        if ticker in db["deeplinks"]:
            redirect_url = db["deeplinks"][ticker]
        else:
            redirect_url = f"{DEFAULT_TRADE_URL_BASE}{ticker}-USDT"
    else:
        ticker = signal_id
        if ticker in db["deeplinks"]:
            redirect_url = db["deeplinks"][ticker]
        else:
            redirect_url = f"{DEFAULT_TRADE_URL_BASE}{ticker}-USDT"
    
    # Use HTML page redirect instead of server redirect
    # This preserves deep link functionality for mobile apps
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="0;url={redirect_url}">
    <title>Redirecting...</title>
    <script>
        window.location.href = "{redirect_url}";
    </script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .loader {{
            text-align: center;
        }}
        .spinner {{
            width: 40px;
            height: 40px;
            border: 4px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="loader">
        <div class="spinner"></div>
        <p>Opening Mudrex...</p>
    </div>
</body>
</html>'''
    
    return web.Response(text=html, content_type='text/html')

async def handle_health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/track/{signal_id}', handle_track)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/', handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Web server on port {PORT}")


# ============== MAIN ==============

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Signal conversation
    signal_conv = ConversationHandler(
        entry_points=[
            CommandHandler("signal", signal_command),
            MessageHandler(filters.Regex(r'(?i)^signal\s'), signal_command),
        ],
        states={
            WAITING_FOR_CREATIVE: [
                MessageHandler(filters.PHOTO, receive_creative),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_creative),
            ],
            WAITING_FOR_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_send),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'(?i)^cancel$'), cancel_command),
        ],
    )
    
    # Fix conversation
    fix_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r'(?i)^/?fix\d+$'), fix_command),
        ],
        states={
            WAITING_FOR_FIX_CREATIVE: [MessageHandler(filters.PHOTO, receive_fix_creative)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'(?i)^cancel$'), cancel_command),
        ],
    )
    
    # Format conversation
    format_conv = ConversationHandler(
        entry_points=[
            CommandHandler("format", format_command),
            MessageHandler(filters.Regex(r'(?i)^format$'), format_command),
        ],
        states={
            WAITING_FOR_FORMAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_format)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'(?i)^cancel$'), cancel_command),
        ],
    )
    
    application.add_handler(signal_conv)
    application.add_handler(fix_conv)
    application.add_handler(format_conv)
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("clearfix", clearfix_command))
    application.add_handler(CommandHandler("links", links_command))
    application.add_handler(CommandHandler("clearlink", clearlink_command))
    application.add_handler(CommandHandler("clickon", clickon_command))
    application.add_handler(CommandHandler("clickoff", clickoff_command))
    application.add_handler(CommandHandler("clicks", clicks_command))
    application.add_handler(CommandHandler("postclicks", postclicks_command))
    application.add_handler(CommandHandler("clearclicks", clearclicks_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    for month in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                  "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"]:
        application.add_handler(CommandHandler(month, month_stats_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_web_server())
    
    logger.info("🚀 Mudrex Signal Bot v2.1 started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
