"""
🚀 MUDREX TRADING SIGNAL BOT v2.0
==================================
Complete Telegram bot for posting crypto trading signals

Features:
- Signal posting with preview
- Unlimited creatives (fix1, fix2...)
- Auto-save deeplinks per ticker
- Click tracking with analytics
- Monthly signal statistics
- Persistent JSON database
- Commands work with & without /
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from aiohttp import web
import aiohttp
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

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

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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
    "last_signal": None,
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
                # Merge with defaults for any missing keys
                for key in DEFAULT_DB:
                    if key not in db:
                        db[key] = DEFAULT_DB[key]
                return db
    except Exception as e:
        logger.error(f"Error loading database: {e}")
    return DEFAULT_DB.copy()

def save_db(db):
    """Save database to JSON file"""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DB_PATH, 'w') as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving database: {e}")

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
    """Get current time in IST format"""
    now = datetime.now(IST)
    return now.strftime("%d %b %Y, %I:%M %p")

def get_ist_date() -> str:
    """Get current date in IST"""
    now = datetime.now(IST)
    return now.strftime("%d %b %Y")

def get_month_key() -> str:
    """Get current month key (YYYY-MM)"""
    now = datetime.now(IST)
    return now.strftime("%Y-%m")

def format_price(price: float) -> str:
    """Format price according to TradingView precision rules"""
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
    """Calculate all signal parameters"""
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
    """Generate signal text from template"""
    template = db["settings"].get("signal_format") or DEFAULT_FORMAT
    return template.format(**signal_data)

def generate_figma_prompt(signal_data: dict) -> str:
    """Generate Figma agent instructions - all in one code block"""
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
    """Generate summary box"""
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

def get_trade_url(ticker: str, custom_url: str = None) -> str:
    """Get trade URL - with click tracking if enabled"""
    global db
    
    # Use custom URL if provided
    if custom_url:
        actual_url = custom_url
        # Save deeplink for ticker
        db["deeplinks"][ticker.upper()] = custom_url
        save_db(db)
    elif ticker.upper() in db["deeplinks"]:
        actual_url = db["deeplinks"][ticker.upper()]
    else:
        actual_url = f"{DEFAULT_TRADE_URL_BASE}{ticker.upper()}-USDT"
    
    # If click tracking is ON, wrap with tracker
    if db["settings"].get("click_tracking") and RAILWAY_URL:
        return f"https://{RAILWAY_URL}/track/{ticker.upper()}"
    
    return actual_url

def record_signal(ticker: str, direction: str, message_id: int):
    """Record signal in database"""
    global db
    
    month_key = get_month_key()
    date_str = get_ist_date()
    
    if month_key not in db["signals"]:
        db["signals"][month_key] = []
    
    signal_record = {
        "ticker": ticker,
        "direction": direction,
        "date": date_str,
        "message_id": message_id,
        "timestamp": datetime.now(IST).isoformat()
    }
    
    db["signals"][month_key].append(signal_record)
    db["stats"]["total_signals"] += 1
    db["stats"]["last_signal_date"] = date_str
    
    if not db["stats"]["first_signal_date"]:
        db["stats"]["first_signal_date"] = date_str
    
    db["last_signal"] = {
        "message_id": message_id,
        "ticker": ticker,
        "direction": direction,
        "date": date_str
    }
    
    save_db(db)

def record_click(ticker: str):
    """Record a click in database"""
    global db
    
    now = datetime.now(IST)
    date_key = now.strftime("%Y-%m-%d")
    
    if "clicks" not in db:
        db["clicks"] = {}
    
    if ticker not in db["clicks"]:
        db["clicks"][ticker] = {}
    
    if date_key not in db["clicks"][ticker]:
        db["clicks"][ticker][date_key] = 0
    
    db["clicks"][ticker][date_key] += 1
    save_db(db)

def get_click_stats(ticker: str = None, period: str = None) -> dict:
    """Get click statistics"""
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    
    # Calculate date ranges
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    three_months_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    six_months_ago = (now - timedelta(days=180)).strftime("%Y-%m-%d")
    year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    
    stats = {
        "total": 0,
        "today": 0,
        "week": 0,
        "month": 0,
        "3month": 0,
        "6month": 0,
        "year": 0,
        "by_ticker": {}
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

def parse_month(text: str) -> str:
    """Parse month name to YYYY-MM format"""
    months = {
        "jan": "01", "january": "01",
        "feb": "02", "february": "02",
        "mar": "03", "march": "03",
        "apr": "04", "april": "04",
        "may": "05",
        "jun": "06", "june": "06",
        "jul": "07", "july": "07",
        "aug": "08", "august": "08",
        "sep": "09", "september": "09",
        "oct": "10", "october": "10",
        "nov": "11", "november": "11",
        "dec": "12", "december": "12"
    }
    
    text_lower = text.lower().strip()
    if text_lower in months:
        year = datetime.now(IST).year
        month = months[text_lower]
        # If month is in future, use previous year
        current_month = datetime.now(IST).month
        if int(month) > current_month:
            year -= 1
        return f"{year}-{month}"
    return None

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return not ADMIN_IDS or user_id in ADMIN_IDS


# ============== COMMAND HANDLERS ==============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start/Help command"""
    await help_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command with all commands"""
    help_text = """🚀 <b>MUDREX SIGNAL BOT v2.0</b>

<b>━━━━ SIGNALS ━━━━</b>
<code>signal [TICKER] [ENTRY] [SL] [LEV] [link]</code>
Create and post trading signal
Example: <code>signal SOL 125 115 3x</code>
Example: <code>signal ETH 3450 3300 5x https://...</code>

<code>delete</code> - Delete last signal from channel

<b>━━━━ CREATIVES ━━━━</b>
<code>fix1</code>, <code>fix2</code>, <code>fix3</code>... - Save creative image
<code>list</code> - Show all saved creatives
<code>clearfix [N]</code> - Delete creative (clearfix 1)
<code>clearfix all</code> - Delete all creatives

<b>━━━━ DEEPLINKS ━━━━</b>
<code>links</code> - Show all saved ticker links
<code>clearlink [TICKER]</code> - Delete link (clearlink SOL)
<code>clearlink all</code> - Delete all links

<b>━━━━ CLICK TRACKING ━━━━</b>
<code>clickon</code> - Enable click tracking
<code>clickoff</code> - Disable click tracking
<code>clicks</code> - Overall click statistics
<code>clicks [TICKER]</code> - Ticker click stats (clicks SOL)
<code>clicks today</code> - Today's clicks
<code>clicks week</code> - This week's clicks
<code>clicks month</code> - This month's clicks
<code>clicks 3month</code> - Last 3 months
<code>clicks 6month</code> - Last 6 months
<code>clicks year</code> - Last 1 year
<code>clearclicks</code> - Reset all click data

<b>━━━━ ANALYTICS ━━━━</b>
<code>stats</code> - Overall signal statistics
<code>jan</code>, <code>feb</code>, <code>mar</code>... - Monthly stats

<b>━━━━ OTHER ━━━━</b>
<code>format</code> - Change signal template
<code>cancel</code> - Cancel current operation
<code>help</code> - Show this guide

<i>💡 All commands work with or without /</i>"""
    
    await update.message.reply_text(help_text, parse_mode="HTML")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle signal command"""
    global pending_signals
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You're not authorized.")
        return ConversationHandler.END
    
    # Parse command - handle both /signal and signal
    text = update.message.text
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    if len(parts) < 5:
        await update.message.reply_text(
            "❌ Invalid format!\n\n"
            "Use: <code>signal TICKER ENTRY SL LEVERAGE [link]</code>\n"
            "Example: <code>signal SOL 125 115 3x</code>\n"
            "Example: <code>signal ETH 3450 3300 5x https://...</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    try:
        ticker = parts[1].upper()
        entry1 = float(parts[2])
        sl = float(parts[3])
        leverage = int(parts[4].lower().replace('x', ''))
        
        # Check for custom URL
        custom_url = None
        if len(parts) >= 6 and parts[5].startswith('http'):
            custom_url = parts[5]
        
        # Calculate signal
        signal_data = calculate_signal(ticker, entry1, sl, leverage)
        signal_data['trade_url'] = get_trade_url(ticker, custom_url)
        
        # Store pending signal
        pending_signals[user_id] = {
            "signal_data": signal_data,
            "custom_url": custom_url
        }
        
        # Check for saved deeplink
        saved_link_msg = ""
        if not custom_url and ticker in db["deeplinks"]:
            saved_link_msg = f"\n\n🔗 Using saved link for {ticker}"
        elif custom_url:
            saved_link_msg = f"\n\n💾 Deeplink saved for {ticker}"
        
        # List available creatives
        creative_list = ""
        if db["creatives"]:
            creative_list = "\n\nSaved creatives: " + ", ".join(sorted(db["creatives"].keys()))
        
        await update.message.reply_text(
            f"📊 <b>Signal Calculated:</b>\n"
            f"Ticker: {signal_data['ticker']} {signal_data['direction']}\n"
            f"Entry1: ${signal_data['entry1']}\n"
            f"Entry2: ${signal_data['entry2']}\n"
            f"TP1: ${signal_data['tp1']}\n"
            f"TP2: ${signal_data['tp2']}\n"
            f"SL: ${signal_data['sl']}\n"
            f"Leverage: {signal_data['leverage']}x"
            f"{saved_link_msg}\n\n"
            f"🖼️ Drop creative image or type <code>use fix1</code>, <code>use fix2</code>..."
            f"{creative_list}",
            parse_mode="HTML"
        )
        
        return WAITING_FOR_CREATIVE
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Error parsing values: {e}\n\nMake sure ENTRY, SL are numbers and LEVERAGE is like '3x'")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Signal command error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def receive_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive creative and show preview"""
    global pending_signals
    
    user_id = update.effective_user.id
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal. Use <code>signal</code> first.", parse_mode="HTML")
        return ConversationHandler.END
    
    # Check for "use fixN" text
    if update.message.text:
        text = update.message.text.lower().strip()
        if text.startswith("use fix"):
            fix_key = text.replace("use ", "")
            if fix_key in db["creatives"]:
                pending_signals[user_id]["creative_file_id"] = db["creatives"][fix_key]
            else:
                await update.message.reply_text(f"❌ Creative '{fix_key}' not found. Use <code>list</code> to see saved creatives.", parse_mode="HTML")
                return WAITING_FOR_CREATIVE
        else:
            await update.message.reply_text("❌ Please send an image or type <code>use fix1</code>, <code>use fix2</code>...", parse_mode="HTML")
            return WAITING_FOR_CREATIVE
    elif update.message.photo:
        pending_signals[user_id]["creative_file_id"] = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("❌ Please send an image or type <code>use fix1</code>, <code>use fix2</code>...", parse_mode="HTML")
        return WAITING_FOR_CREATIVE
    
    # Generate preview
    signal_data = pending_signals[user_id]["signal_data"]
    signal_text = generate_signal_text(signal_data)
    creative_file_id = pending_signals[user_id]["creative_file_id"]
    
    # Create button for preview
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=signal_data['trade_url'])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send preview
    await update.message.reply_text("📊 <b>SIGNAL PREVIEW:</b>", parse_mode="HTML")
    
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=creative_file_id,
        caption=signal_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    await update.message.reply_text(
        "👆 This is how it will look in the channel.\n\n"
        "Type <code>send now</code> to post or <code>cancel</code> to abort.",
        parse_mode="HTML"
    )
    
    return WAITING_FOR_CONFIRM

async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and send signal to channel"""
    global pending_signals, db
    
    user_id = update.effective_user.id
    text = update.message.text.lower().strip()
    
    if text == "cancel":
        pending_signals.pop(user_id, None)
        await update.message.reply_text("❌ Signal cancelled.")
        return ConversationHandler.END
    
    if text != "send now":
        await update.message.reply_text("Type <code>send now</code> to post or <code>cancel</code> to abort.", parse_mode="HTML")
        return WAITING_FOR_CONFIRM
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal.")
        return ConversationHandler.END
    
    signal_data = pending_signals[user_id]["signal_data"]
    creative_file_id = pending_signals[user_id]["creative_file_id"]
    signal_text = generate_signal_text(signal_data)
    
    # Create button
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=signal_data['trade_url'])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        # Send to channel
        sent_message = await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=creative_file_id,
            caption=signal_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        # Record signal
        record_signal(signal_data['ticker'], signal_data['direction'], sent_message.message_id)
        
        # Send confirmation
        await update.message.reply_text("✅ <b>Signal posted successfully!</b>", parse_mode="HTML")
        
        # Send Figma prompt
        figma_prompt = generate_figma_prompt(signal_data)
        await update.message.reply_text(figma_prompt, parse_mode="Markdown")
        
        # Send summary
        summary = generate_summary_box(signal_data)
        await update.message.reply_text(summary, parse_mode="Markdown")
        
        # Clear pending
        pending_signals.pop(user_id, None)
        
        logger.info(f"Signal posted: {signal_data['ticker']} {signal_data['direction']}")
        
    except Exception as e:
        logger.error(f"Error posting signal: {e}")
        await update.message.reply_text(f"❌ Error posting to channel: {e}")
    
    return ConversationHandler.END

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete last signal from channel"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
        return
    
    if not db.get("last_signal"):
        await update.message.reply_text("❌ No signal to delete.")
        return
    
    try:
        await context.bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=db["last_signal"]["message_id"]
        )
        
        ticker = db["last_signal"]["ticker"]
        db["last_signal"] = None
        db["stats"]["total_signals"] = max(0, db["stats"]["total_signals"] - 1)
        save_db(db)
        
        await update.message.reply_text(f"✅ Deleted last signal ({ticker})")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error deleting: {e}")

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle fixN command - save creative"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
        return ConversationHandler.END
    
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    # Extract fix number
    fix_key = text  # e.g., "fix1", "fix2"
    
    context.user_data["pending_fix_key"] = fix_key
    
    await update.message.reply_text(f"🖼️ Drop the creative image to save as <code>{fix_key}</code>:", parse_mode="HTML")
    return WAITING_FOR_FIX_CREATIVE

async def receive_fix_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and save fix creative"""
    global db
    
    if not update.message.photo:
        await update.message.reply_text("❌ Please send an image.")
        return WAITING_FOR_FIX_CREATIVE
    
    fix_key = context.user_data.get("pending_fix_key", "fix1")
    db["creatives"][fix_key] = update.message.photo[-1].file_id
    save_db(db)
    
    await update.message.reply_text(f"✅ Creative saved as <code>{fix_key}</code>!\n\nUse <code>use {fix_key}</code> when posting signals.", parse_mode="HTML")
    return ConversationHandler.END

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all saved creatives"""
    if not db["creatives"]:
        await update.message.reply_text("📭 No saved creatives.\n\nUse <code>fix1</code>, <code>fix2</code>... to save creatives.", parse_mode="HTML")
        return
    
    creative_list = "\n".join([f"• <code>{k}</code>" for k in sorted(db["creatives"].keys())])
    await update.message.reply_text(
        f"🖼️ <b>SAVED CREATIVES</b>\n\n{creative_list}\n\n"
        f"Total: {len(db['creatives'])} creatives\n\n"
        f"Use <code>use fix1</code>, <code>use fix2</code>... when posting signals.",
        parse_mode="HTML"
    )

async def clearfix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear saved creative(s)"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
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
        await update.message.reply_text(f"✅ Deleted all {count} creatives.")
    else:
        fix_key = f"fix{target}"
        if fix_key in db["creatives"]:
            del db["creatives"][fix_key]
            save_db(db)
            await update.message.reply_text(f"✅ Deleted <code>{fix_key}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Creative <code>{fix_key}</code> not found.", parse_mode="HTML")

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all saved deeplinks"""
    if not db["deeplinks"]:
        await update.message.reply_text("📭 No saved deeplinks.\n\nDeeplinks are auto-saved when you use them in signals.", parse_mode="HTML")
        return
    
    links_list = "\n".join([f"• <b>{k}</b> → {v}" for k, v in sorted(db["deeplinks"].items())])
    await update.message.reply_text(
        f"🔗 <b>SAVED DEEPLINKS</b>\n\n{links_list}\n\n"
        f"Total: {len(db['deeplinks'])} tickers",
        parse_mode="HTML"
    )

async def clearlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear saved deeplink(s)"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
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
        await update.message.reply_text(f"✅ Deleted all {count} deeplinks.")
    else:
        if target in db["deeplinks"]:
            del db["deeplinks"][target]
            save_db(db)
            await update.message.reply_text(f"✅ Deleted deeplink for <code>{target}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ No deeplink found for <code>{target}</code>", parse_mode="HTML")

async def clickon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable click tracking"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
        return
    
    if not RAILWAY_URL:
        await update.message.reply_text("❌ Click tracking requires RAILWAY_PUBLIC_DOMAIN environment variable.")
        return
    
    db["settings"]["click_tracking"] = True
    save_db(db)
    await update.message.reply_text("✅ Click tracking <b>ENABLED</b>\n\nNew signals will use tracked links.", parse_mode="HTML")

async def clickoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable click tracking"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
        return
    
    db["settings"]["click_tracking"] = False
    save_db(db)
    await update.message.reply_text("✅ Click tracking <b>DISABLED</b>\n\nNew signals will use direct links.", parse_mode="HTML")

async def clicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show click statistics"""
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    parts = text.split()
    
    # Determine what stats to show
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
        # Specific ticker stats
        await update.message.reply_text(
            f"📊 <b>{ticker} CLICK STATS</b>\n\n"
            f"Total (All Time): {stats['total']} clicks\n\n"
            f"📅 Today: {stats['today']}\n"
            f"📅 This Week: {stats['week']}\n"
            f"📅 This Month: {stats['month']}\n"
            f"📅 Last 3 Months: {stats['3month']}\n"
            f"📅 Last 6 Months: {stats['6month']}\n"
            f"📅 Last 1 Year: {stats['year']}\n\n"
            f"Tracking: {tracking_status}",
            parse_mode="HTML"
        )
    elif period:
        # Period-specific stats
        period_names = {
            "today": "TODAY'S",
            "week": "THIS WEEK'S",
            "month": "THIS MONTH'S",
            "3month": "LAST 3 MONTHS",
            "6month": "LAST 6 MONTHS",
            "year": "LAST 1 YEAR"
        }
        
        await update.message.reply_text(
            f"📊 <b>{period_names[period]} CLICKS</b>\n\n"
            f"Total: {stats[period]} clicks\n\n"
            f"Tracking: {tracking_status}",
            parse_mode="HTML"
        )
    else:
        # Overall stats
        top_tickers = sorted(stats["by_ticker"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_list = "\n".join([f"{i+1}. {t} - {c} clicks" for i, (t, c) in enumerate(top_tickers)]) or "No data yet"
        
        await update.message.reply_text(
            f"📊 <b>CLICK STATISTICS</b>\n\n"
            f"Total Clicks (All Time): {stats['total']}\n\n"
            f"📅 Today: {stats['today']}\n"
            f"📅 This Week: {stats['week']}\n"
            f"📅 This Month: {stats['month']}\n"
            f"📅 Last 3 Months: {stats['3month']}\n"
            f"📅 Last 6 Months: {stats['6month']}\n"
            f"📅 Last 1 Year: {stats['year']}\n\n"
            f"<b>TOP TICKERS:</b>\n{top_list}\n\n"
            f"Tracking: {tracking_status}",
            parse_mode="HTML"
        )

async def clearclicks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all click data"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
        return
    
    db["clicks"] = {}
    save_db(db)
    await update.message.reply_text("✅ All click data cleared.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show overall signal statistics"""
    total = db["stats"]["total_signals"]
    first_date = db["stats"]["first_signal_date"] or "N/A"
    last_date = db["stats"]["last_signal_date"] or "N/A"
    
    # Count LONG/SHORT
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
    
    # Calculate percentages
    long_pct = (long_count / total * 100) if total > 0 else 0
    short_pct = (short_count / total * 100) if total > 0 else 0
    
    # Top tickers
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_list = "\n".join([f"{i+1}. {t} - {c} signals" for i, (t, c) in enumerate(top_tickers)]) or "No data yet"
    
    await update.message.reply_text(
        f"📊 <b>OVERALL STATISTICS</b>\n\n"
        f"📈 Total Signals: {total}\n"
        f"🟢 LONG: {long_count} ({long_pct:.1f}%)\n"
        f"🔴 SHORT: {short_count} ({short_pct:.1f}%)\n\n"
        f"📅 Started: {first_date}\n"
        f"📅 Last Signal: {last_date}\n\n"
        f"<b>TOP TICKERS:</b>\n{top_list}",
        parse_mode="HTML"
    )

async def month_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show monthly statistics"""
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    month_key = parse_month(text)
    
    if not month_key:
        await update.message.reply_text("❌ Invalid month. Use: jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec")
        return
    
    signals = db["signals"].get(month_key, [])
    total = len(signals)
    
    if total == 0:
        await update.message.reply_text(f"📭 No signals found for {text.upper()}.")
        return
    
    # Count stats
    long_count = sum(1 for s in signals if s["direction"] == "LONG")
    short_count = total - long_count
    long_pct = (long_count / total * 100) if total > 0 else 0
    short_pct = (short_count / total * 100) if total > 0 else 0
    
    # Ticker counts
    ticker_counts = {}
    for signal in signals:
        ticker = signal["ticker"]
        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_list = "\n".join([f"{i+1}. {t} - {c} signals" for i, (t, c) in enumerate(top_tickers)])
    
    # Format month name
    month_name = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
    
    await update.message.reply_text(
        f"📊 <b>{month_name.upper()} STATISTICS</b>\n\n"
        f"📈 Total Signals: {total}\n"
        f"🟢 LONG: {long_count} ({long_pct:.1f}%)\n"
        f"🔴 SHORT: {short_count} ({short_pct:.1f}%)\n\n"
        f"<b>TOP TICKERS:</b>\n{top_list}",
        parse_mode="HTML"
    )

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change signal format template"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You're not authorized.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 <b>Send your new signal format template</b>\n\n"
        "<b>Available placeholders:</b>\n"
        "<code>{ticker}</code> - ETH, BTC\n"
        "<code>{direction}</code> - LONG/SHORT\n"
        "<code>{direction_emoji}</code> - 📈/📉\n"
        "<code>{leverage}</code> - 3\n"
        "<code>{holding_time}</code> - 2-3 days\n"
        "<code>{entry1}</code>, <code>{entry2}</code> - Entry prices\n"
        "<code>{tp1}</code>, <code>{tp2}</code> - Take profits\n"
        "<code>{sl}</code> - Stop loss\n"
        "<code>{avg_entry}</code> - Average entry\n"
        "<code>{potential_profit}</code> - 23.08%\n"
        "<code>{challenge_url}</code> - Challenge link\n"
        "<code>{leaderboard_url}</code> - Leaderboard link\n\n"
        "Or send <code>reset</code> to use default format.",
        parse_mode="HTML"
    )
    return WAITING_FOR_FORMAT

async def receive_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and save new format"""
    global db
    
    text = update.message.text
    
    if text.lower().strip() == "reset":
        db["settings"]["signal_format"] = None
        save_db(db)
        await update.message.reply_text("✅ Format reset to default!")
    else:
        db["settings"]["signal_format"] = text
        save_db(db)
        await update.message.reply_text("✅ New format saved!")
    
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    global pending_signals
    
    user_id = update.effective_user.id
    pending_signals.pop(user_id, None)
    
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages without / prefix"""
    text = update.message.text.lower().strip()
    
    # Route to appropriate handler
    if text.startswith("signal "):
        return await signal_command(update, context)
    elif text == "delete":
        return await delete_command(update, context)
    elif text.startswith("fix") and text[3:].isdigit():
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
    """Handle click tracking redirect"""
    ticker = request.match_info.get('ticker', '').upper()
    
    # Record click
    record_click(ticker)
    logger.info(f"Click recorded: {ticker}")
    
    # Get actual URL
    if ticker in db["deeplinks"]:
        redirect_url = db["deeplinks"][ticker]
    else:
        redirect_url = f"{DEFAULT_TRADE_URL_BASE}{ticker}-USDT"
    
    # Redirect
    raise web.HTTPFound(location=redirect_url)

async def handle_health(request):
    """Health check endpoint"""
    return web.Response(text="OK")

async def start_web_server():
    """Start web server for click tracking"""
    app = web.Application()
    app.router.add_get('/track/{ticker}', handle_track)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/', handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")


# ============== MAIN ==============

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Signal conversation handler
    signal_conv = ConversationHandler(
        entry_points=[
            CommandHandler("signal", signal_command),
            MessageHandler(filters.Regex(r'^signal\s', re.IGNORECASE), signal_command),
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
            MessageHandler(filters.Regex(r'^cancel$', re.IGNORECASE), cancel_command),
        ],
    )
    
    # Fix conversation handler
    fix_conv = ConversationHandler(
        entry_points=[
            CommandHandler("fix", fix_command, filters=filters.Regex(r'^/fix\d+')),
            MessageHandler(filters.Regex(r'^fix\d+$', re.IGNORECASE), fix_command),
        ],
        states={
            WAITING_FOR_FIX_CREATIVE: [MessageHandler(filters.PHOTO, receive_fix_creative)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'^cancel$', re.IGNORECASE), cancel_command),
        ],
    )
    
    # Format conversation handler
    format_conv = ConversationHandler(
        entry_points=[
            CommandHandler("format", format_command),
            MessageHandler(filters.Regex(r'^format$', re.IGNORECASE), format_command),
        ],
        states={
            WAITING_FOR_FORMAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_format)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'^cancel$', re.IGNORECASE), cancel_command),
        ],
    )
    
    # Add handlers
    application.add_handler(signal_conv)
    application.add_handler(fix_conv)
    application.add_handler(format_conv)
    
    # Command handlers
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
    application.add_handler(CommandHandler("clearclicks", clearclicks_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # Month commands
    for month in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                  "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"]:
        application.add_handler(CommandHandler(month, month_stats_command))
    
    # Text handler for commands without /
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Start web server and bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Start web server
    loop.run_until_complete(start_web_server())
    
    # Start bot
    logger.info("🚀 Mudrex Signal Bot v2.0 is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import re
    main()
