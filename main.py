"""
🚀 MUDREX TRADING SIGNAL BOT v3.0
==================================
Clean, optimized Telegram bot for posting crypto trading signals
Features: Team tracking, Views analytics, Channel stats
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ============== CONFIGURATION ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1002163454656")

# Admin IDs - supports admin_id1, admin_id2, admin_id3, etc.
ADMIN_IDS = []
for key, value in os.environ.items():
    if key.lower().startswith("admin_id") and value.strip():
        try:
            ADMIN_IDS.append(int(value.strip()))
        except ValueError:
            pass

# URLs
DEFAULT_TRADE_URL_BASE = os.environ.get("TRADE_URL_BASE", "https://mudrex.com/trade/")
LEADERBOARD_URL = os.environ.get("LEADERBOARD_URL", "https://t.me/officialmudrex/98446/99620")
CHALLENGE_URL = os.environ.get("CHALLENGE_URL", "https://t.me/officialmudrex/98446/98616")

# Database file path
DB_PATH = Path("/app/data/database.json") if os.path.exists("/app") else Path("database.json")

# Team members
TEAM_MEMBERS = ["rohith", "rajini", "balaji"]

# Logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Conversation states
WAITING_FOR_CREATIVE = 1
WAITING_FOR_CONFIRM = 2
WAITING_FOR_FIX_CREATIVE = 3
WAITING_FOR_FORMAT = 4

# IST Timezone
IST = ZoneInfo("Asia/Kolkata")

# Bot active state
BOT_ACTIVE = False

# ============== DATABASE ==============
DEFAULT_DB = {
    "creatives": {},
    "adjust_links": {},
    "signals": {},
    "signal_counter": 0,
    "views": {},
    "channel_stats": {},
    "last_signal": None,
    "settings": {
        "signal_format": None
    }
}

def load_db():
    """Load database from JSON file"""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DB_PATH.exists():
            with open(DB_PATH, 'r') as f:
                data = json.load(f)
                for key in DEFAULT_DB:
                    if key not in data:
                        data[key] = DEFAULT_DB[key]
                return data
    except Exception as e:
        logger.error(f"DB load error: {e}")
    return DEFAULT_DB.copy()

def save_db(data):
    """Save database to JSON file"""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DB_PATH, 'w') as f:
            json.dump(data, f, indent=2)
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

def get_ist_now():
    return datetime.now(IST)

def get_ist_timestamp() -> str:
    return get_ist_now().strftime("%d %b %Y, %I:%M %p")

def get_ist_date() -> str:
    return get_ist_now().strftime("%d %b %Y")

def get_year() -> str:
    return get_ist_now().strftime("%Y")

def get_month_key() -> str:
    return get_ist_now().strftime("%Y-%m")

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

def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS

def parse_year_range(text: str):
    """Parse year or year range from command like totalsignal2025 or totalsignal20252026"""
    # Extract digits from end of text
    digits = ""
    for char in reversed(text):
        if char.isdigit():
            digits = char + digits
        else:
            break
    
    if not digits:
        return None, None
    
    if len(digits) == 4:
        # Single year: 2025
        return digits, digits
    elif len(digits) == 8:
        # Year range: 20252026
        return digits[:4], digits[4:]
    else:
        return None, None

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
    }

def generate_signal_text(signal_data: dict) -> str:
    template = db["settings"].get("signal_format") or DEFAULT_FORMAT
    return template.format(**signal_data)

def get_adjust_link(ticker: str) -> str:
    """Get adjust link for ticker"""
    ticker = ticker.upper()
    return db.get("adjust_links", {}).get(ticker)

def save_adjust_link(ticker: str, link: str):
    """Save adjust link for ticker"""
    global db
    ticker = ticker.upper()
    if "adjust_links" not in db:
        db["adjust_links"] = {}
    db["adjust_links"][ticker] = link
    save_db(db)

def record_signal(signal_id: str, ticker: str, direction: str, message_id: int, sender: str):
    """Record signal in database with sender info"""
    global db
    
    year = get_year()
    month_key = get_month_key()
    date_str = get_ist_date()
    timestamp = get_ist_now().isoformat()
    
    if "signals" not in db:
        db["signals"] = {}
    
    if year not in db["signals"]:
        db["signals"][year] = {}
    
    if month_key not in db["signals"][year]:
        db["signals"][year][month_key] = []
    
    signal_record = {
        "signal_id": signal_id,
        "ticker": ticker,
        "direction": direction,
        "date": date_str,
        "message_id": message_id,
        "sender": sender.lower(),
        "timestamp": timestamp,
        "views": 0
    }
    
    db["signals"][year][month_key].append(signal_record)
    
    db["last_signal"] = {
        "signal_id": signal_id,
        "message_id": message_id,
        "ticker": ticker,
        "direction": direction,
        "sender": sender,
        "date": date_str,
        "year": year,
        "month_key": month_key
    }
    
    save_db(db)

def get_signal_stats(start_year: str = None, end_year: str = None, sender: str = None) -> dict:
    """Get signal statistics for year range and/or sender"""
    current_year = get_year()
    
    if not start_year:
        start_year = current_year
    if not end_year:
        end_year = start_year
    
    stats = {
        "total": 0,
        "by_month": {},
        "by_sender": {"rohith": 0, "rajini": 0, "balaji": 0},
        "by_direction": {"LONG": 0, "SHORT": 0},
        "by_ticker": {},
        "start_year": start_year,
        "end_year": end_year
    }
    
    signals_data = db.get("signals", {})
    
    for year in range(int(start_year), int(end_year) + 1):
        year_str = str(year)
        if year_str not in signals_data:
            continue
        
        for month_key, signals in signals_data[year_str].items():
            for signal in signals:
                # Filter by sender if specified
                if sender and signal.get("sender", "").lower() != sender.lower():
                    continue
                
                stats["total"] += 1
                
                # By month
                month_name = datetime.strptime(month_key, "%Y-%m").strftime("%b")
                if year_str not in stats["by_month"]:
                    stats["by_month"][year_str] = {}
                stats["by_month"][year_str][month_name] = stats["by_month"][year_str].get(month_name, 0) + 1
                
                # By sender
                sig_sender = signal.get("sender", "unknown").lower()
                if sig_sender in stats["by_sender"]:
                    stats["by_sender"][sig_sender] += 1
                
                # By direction
                direction = signal.get("direction", "LONG")
                stats["by_direction"][direction] += 1
                
                # By ticker
                ticker = signal.get("ticker", "N/A")
                stats["by_ticker"][ticker] = stats["by_ticker"].get(ticker, 0) + 1
    
    return stats

async def update_views_for_all_signals(context: ContextTypes.DEFAULT_TYPE):
    """Update view counts for all signals - called at midnight"""
    global db
    
    signals_data = db.get("signals", {})
    updated_count = 0
    
    for year, months in signals_data.items():
        for month_key, signals in months.items():
            for i, signal in enumerate(signals):
                message_id = signal.get("message_id")
                if message_id:
                    try:
                        # Get message to check views
                        # Note: This requires the bot to be admin in the channel
                        message = await context.bot.forward_message(
                            chat_id=ADMIN_IDS[0] if ADMIN_IDS else CHANNEL_ID,
                            from_chat_id=CHANNEL_ID,
                            message_id=message_id,
                            disable_notification=True
                        )
                        # Delete the forwarded message
                        await context.bot.delete_message(
                            chat_id=ADMIN_IDS[0] if ADMIN_IDS else CHANNEL_ID,
                            message_id=message.message_id
                        )
                        
                        # Unfortunately, Telegram doesn't expose view count via Bot API
                        # We'll need to track this differently
                        updated_count += 1
                    except Exception as e:
                        logger.debug(f"Could not update views for message {message_id}: {e}")
    
    # Save today's view snapshot
    today = get_ist_date()
    if "views" not in db:
        db["views"] = {}
    db["views"][today] = {
        "updated_at": get_ist_timestamp(),
        "signals_checked": updated_count
    }
    save_db(db)
    
    logger.info(f"Updated views for {updated_count} signals")

async def update_channel_stats(context: ContextTypes.DEFAULT_TYPE):
    """Update channel member count - called at midnight"""
    global db
    
    try:
        chat = await context.bot.get_chat(CHANNEL_ID)
        member_count = await context.bot.get_chat_member_count(CHANNEL_ID)
        
        today = get_ist_date()
        month_key = get_month_key()
        
        if "channel_stats" not in db:
            db["channel_stats"] = {}
        
        if "daily" not in db["channel_stats"]:
            db["channel_stats"]["daily"] = {}
        
        if "monthly" not in db["channel_stats"]:
            db["channel_stats"]["monthly"] = {}
        
        db["channel_stats"]["daily"][today] = member_count
        db["channel_stats"]["current"] = member_count
        db["channel_stats"]["last_updated"] = get_ist_timestamp()
        
        # Monthly tracking
        if month_key not in db["channel_stats"]["monthly"]:
            db["channel_stats"]["monthly"][month_key] = {
                "start": member_count,
                "end": member_count
            }
        else:
            db["channel_stats"]["monthly"][month_key]["end"] = member_count
        
        save_db(db)
        logger.info(f"Updated channel stats: {member_count} members")
        
    except Exception as e:
        logger.error(f"Could not update channel stats: {e}")

async def midnight_task(context: ContextTypes.DEFAULT_TYPE):
    """Task that runs at midnight IST"""
    logger.info("Running midnight task...")
    await update_channel_stats(context)
    # Note: View tracking via Bot API is limited
    # await update_views_for_all_signals(context)

def schedule_midnight_task(application):
    """Schedule the midnight task"""
    job_queue = application.job_queue
    
    # Calculate time until next midnight IST
    now = get_ist_now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    seconds_until_midnight = (midnight - now).total_seconds()
    
    # Schedule daily task at midnight IST
    job_queue.run_repeating(
        midnight_task,
        interval=86400,  # 24 hours
        first=seconds_until_midnight
    )
    logger.info(f"Midnight task scheduled. First run in {seconds_until_midnight/3600:.1f} hours")


# ============== COMMAND HANDLERS ==============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start123 command to activate bot"""
    global BOT_ACTIVE
    
    text = update.message.text.strip()
    if text == "start123":
        BOT_ACTIVE = True
        await update.message.reply_text(
            "✅ <b>Bot Activated!</b>\n\n"
            "Ready to post signals.\n"
            "Type <code>help</code> for commands.",
            parse_mode="HTML"
        )
        logger.info("Bot activated")
    else:
        await help_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    help_text = """🚀 <b>MUDREX SIGNAL BOT v3.0</b>

<b>━━━━ SIGNALS ━━━━</b>
<code>signal BTC 86800 90200 3x [link]</code>
<code>BTC 86800 90200 3x [link]</code>
<code>delete</code>

<b>━━━━ LINKS ━━━━</b>
<code>links</code>
<code>addlink BTC link1 ETH link2</code>
<code>clearlink BTC</code> / <code>clearlink all</code>

<b>━━━━ CREATIVES ━━━━</b>
<code>savefix1</code> (save new creative)
<code>fix1</code> or <code>use fix1</code> (use in signal)
<code>list</code>
<code>clearfix 1</code> / <code>clearfix all</code>

<b>━━━━ ANALYTICS ━━━━</b>
<code>totalsignal</code> / <code>totalsignal2025</code>
<code>totalrohith</code> / <code>totalrajini</code> / <code>totalbalaji</code>
<code>views</code> / <code>views2025</code>
<code>channelstats</code>

<b>━━━━ OTHER ━━━━</b>
<code>format</code>
<code>help</code>
<code>start123</code>

💡 Signal flow: <code>signal</code> → <code>fix1</code> → <code>/sendnow_as_name</code>"""
    
    await update.message.reply_text(help_text, parse_mode="HTML")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle signal command"""
    global pending_signals
    
    if not BOT_ACTIVE:
        await update.message.reply_text("❌ Bot is not active. Use <code>start123</code> to activate.", parse_mode="HTML")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    
    text = update.message.text.strip()
    if text.lower().startswith('/signal'):
        text = text[7:].strip()
    elif text.lower().startswith('signal'):
        text = text[6:].strip()
    
    parts = text.split()
    
    if len(parts) < 4:
        await update.message.reply_text(
            "❌ Invalid format!\n\n"
            "Use: <code>signal BTC 86800 90200 3x [link]</code>\n"
            "Or: <code>BTC 86800 90200 3x [link]</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    try:
        ticker = parts[0].upper()
        entry1 = float(parts[1])
        sl = float(parts[2])
        leverage = int(parts[3].lower().replace('x', ''))
        
        # Check for adjust link
        adjust_link = None
        if len(parts) >= 5 and parts[4].startswith('http'):
            adjust_link = parts[4]
            save_adjust_link(ticker, adjust_link)
        else:
            adjust_link = get_adjust_link(ticker)
        
        if not adjust_link:
            await update.message.reply_text(f"❌ No link found for {ticker}")
            return ConversationHandler.END
        
        signal_id = get_signal_number()
        signal_data = calculate_signal(ticker, entry1, sl, leverage)
        signal_data['signal_id'] = signal_id
        signal_data['adjust_link'] = adjust_link
        
        pending_signals[user_id] = {
            "signal_data": signal_data,
            "signal_id": signal_id,
            "adjust_link": adjust_link
        }
        
        # Show saved creatives if available
        creative_list = ""
        if db.get("creatives"):
            creative_list = "\n\n📁 Saved: " + ", ".join(sorted(db["creatives"].keys()))
        
        await update.message.reply_text(
            f"📊 <b>Signal #{signal_id}</b>\n\n"
            f"• Ticker: {signal_data['ticker']} {signal_data['direction']}\n"
            f"• Entry1: ${signal_data['entry1']}\n"
            f"• Entry2: ${signal_data['entry2']}\n"
            f"• TP1: ${signal_data['tp1']}\n"
            f"• TP2: ${signal_data['tp2']}\n"
            f"• SL: ${signal_data['sl']}\n"
            f"• Leverage: {signal_data['leverage']}x\n"
            f"🔗 Link: ✅\n\n"
            f"🖼️ Drop creative or type <code>fix1</code>"
            f"{creative_list}",
            parse_mode="HTML"
        )
        
        return WAITING_FOR_CREATIVE
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Error: Invalid number format")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Signal error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def receive_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle creative input - either image or 'use fix1' etc."""
    global pending_signals
    
    user_id = update.effective_user.id
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal. Start with <code>signal</code> command.", parse_mode="HTML")
        return ConversationHandler.END
    
    # Check if it's a photo
    if update.message.photo:
        pending_signals[user_id]["creative_file_id"] = update.message.photo[-1].file_id
    # Check if it's text
    elif update.message.text:
        text = update.message.text.lower().strip()
        
        # Handle "use fix1", "use fix2", etc. OR just "fix1", "fix2"
        if text.startswith("use fix") or (text.startswith("fix") and len(text) >= 4 and text[3:].isdigit()):
            fix_key = text.replace("use ", "") if text.startswith("use ") else text
            if fix_key in db.get("creatives", {}):
                pending_signals[user_id]["creative_file_id"] = db["creatives"][fix_key]
            else:
                saved_list = ', '.join(db.get('creatives', {}).keys()) or 'None'
                await update.message.reply_text(f"❌ '{fix_key}' not found.\n\nSaved: {saved_list}")
                return WAITING_FOR_CREATIVE
        else:
            await update.message.reply_text("❌ Send image or type <code>use fix1</code> or <code>fix1</code>", parse_mode="HTML")
            return WAITING_FOR_CREATIVE
    else:
        await update.message.reply_text("❌ Send image or type <code>use fix1</code> or <code>fix1</code>", parse_mode="HTML")
        return WAITING_FOR_CREATIVE
    
    # Show preview
    signal_data = pending_signals[user_id]["signal_data"]
    signal_text = generate_signal_text(signal_data)
    creative_file_id = pending_signals[user_id]["creative_file_id"]
    adjust_link = pending_signals[user_id]["adjust_link"]
    
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=adjust_link)]]
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
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Tap to post:\n\n"
        "/sendnow_as_rohith\n"
        "/sendnow_as_rajini\n"
        "/sendnow_as_balaji\n\n"
        "Or type /cancel to abort",
        parse_mode="HTML"
    )
    
    return WAITING_FOR_CONFIRM

async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle send confirmation with sender name"""
    global pending_signals, db
    
    user_id = update.effective_user.id
    text = update.message.text.lower().strip()
    
    if text == "/cancel" or text == "cancel":
        pending_signals.pop(user_id, None)
        await update.message.reply_text("❌ Cancelled.")
        return ConversationHandler.END
    
    # Check for sendnow commands
    sender = None
    if text.startswith("/sendnow_as_"):
        sender = text.replace("/sendnow_as_", "")
    elif text.startswith("sendnow_as_"):
        sender = text.replace("sendnow_as_", "")
    
    if not sender or sender not in TEAM_MEMBERS:
        await update.message.reply_text(
            "Tap to post:\n\n"
            "/sendnow_as_rohith\n"
            "/sendnow_as_rajini\n"
            "/sendnow_as_balaji\n\n"
            "Or type /cancel to abort",
            parse_mode="HTML"
        )
        return WAITING_FOR_CONFIRM
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal.")
        return ConversationHandler.END
    
    signal_data = pending_signals[user_id]["signal_data"]
    creative_file_id = pending_signals[user_id]["creative_file_id"]
    signal_id = pending_signals[user_id]["signal_id"]
    adjust_link = pending_signals[user_id]["adjust_link"]
    signal_text = generate_signal_text(signal_data)
    
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=adjust_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        sent_message = await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=creative_file_id,
            caption=signal_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        record_signal(
            signal_id, 
            signal_data['ticker'], 
            signal_data['direction'], 
            sent_message.message_id, 
            sender
        )
        
        await update.message.reply_text(
            f"✅ <b>Signal #{signal_id} posted!</b>\n\n"
            f"Ticker: {signal_data['ticker']} {signal_data['direction']}\n"
            f"Sender: {sender.capitalize()}",
            parse_mode="HTML"
        )
        
        pending_signals.pop(user_id, None)
        logger.info(f"Signal #{signal_id} posted by {sender}: {signal_data['ticker']} {signal_data['direction']}")
        
    except Exception as e:
        logger.error(f"Post error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
    
    return ConversationHandler.END

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete last signal"""
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
        
        # Remove from database
        last = db["last_signal"]
        year = last.get("year")
        month_key = last.get("month_key")
        signal_id = last.get("signal_id")
        
        if year and month_key and year in db.get("signals", {}) and month_key in db["signals"][year]:
            db["signals"][year][month_key] = [
                s for s in db["signals"][year][month_key] 
                if s.get("signal_id") != signal_id
            ]
        
        ticker = last["ticker"]
        db["last_signal"] = None
        save_db(db)
        
        await update.message.reply_text(f"✅ Deleted Signal #{signal_id} ({ticker})")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show saved adjust links"""
    links = db.get("adjust_links", {})
    
    if not links:
        await update.message.reply_text("📭 No saved links.")
        return
    
    links_text = "\n".join([f"  {k} → {v}" for k, v in sorted(links.items())])
    await update.message.reply_text(
        f"🔗 <b>Saved Links</b>\n\n{links_text}\n\nTotal: {len(links)}",
        parse_mode="HTML"
    )

async def addlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add multiple links: addlink BTC link1 ETH link2"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.strip()
    if text.lower().startswith('/addlink'):
        text = text[8:].strip()
    elif text.lower().startswith('addlink'):
        text = text[7:].strip()
    
    parts = text.split()
    
    if len(parts) < 2 or len(parts) % 2 != 0:
        await update.message.reply_text(
            "❌ Invalid format!\n\n"
            "Use: <code>addlink BTC link1 ETH link2</code>",
            parse_mode="HTML"
        )
        return
    
    added = []
    for i in range(0, len(parts), 2):
        ticker = parts[i].upper()
        link = parts[i + 1]
        if link.startswith('http'):
            save_adjust_link(ticker, link)
            added.append(ticker)
    
    if added:
        await update.message.reply_text(f"✅ Added links for: {', '.join(added)}")
    else:
        await update.message.reply_text("❌ No valid links added.")

async def clearlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear links"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.lower().strip()
    parts = text.split()
    
    if len(parts) < 2:
        await update.message.reply_text("Use: <code>clearlink BTC</code> or <code>clearlink all</code>", parse_mode="HTML")
        return
    
    target = parts[1].upper()
    
    if target == "ALL":
        count = len(db.get("adjust_links", {}))
        db["adjust_links"] = {}
        save_db(db)
        await update.message.reply_text(f"✅ Deleted {count} links.")
    else:
        if target in db.get("adjust_links", {}):
            del db["adjust_links"][target]
            save_db(db)
            await update.message.reply_text(f"✅ Deleted {target}")
        else:
            await update.message.reply_text(f"❌ {target} not found.")

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a creative with savefix1, savefix2, etc."""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
    # Extract fix key: savefix1 -> fix1
    fix_key = text.replace("save", "")  # savefix1 -> fix1
    
    # Store the pending fix key
    context.user_data["pending_fix_key"] = fix_key
    context.user_data["waiting_for_fix"] = True
    
    await update.message.reply_text(f"🖼️ Drop image to save as <code>{fix_key}</code>", parse_mode="HTML")

async def receive_fix_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save creative image - called from handle_text when photo received"""
    global db
    
    if not update.message.photo:
        return False
    
    if not context.user_data.get("waiting_for_fix"):
        return False
    
    fix_key = context.user_data.get("pending_fix_key", "fix1")
    if "creatives" not in db:
        db["creatives"] = {}
    db["creatives"][fix_key] = update.message.photo[-1].file_id
    save_db(db)
    
    context.user_data["waiting_for_fix"] = False
    context.user_data["pending_fix_key"] = None
    
    await update.message.reply_text(f"✅ Saved as <code>{fix_key}</code>", parse_mode="HTML")
    return True

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List saved creatives"""
    creatives = db.get("creatives", {})
    
    if not creatives:
        await update.message.reply_text("📭 No saved creatives.")
        return
    
    creative_list = "\n".join([f"  • {k}" for k in sorted(creatives.keys())])
    await update.message.reply_text(
        f"🖼️ <b>Saved Creatives</b>\n\n{creative_list}\n\nTotal: {len(creatives)}",
        parse_mode="HTML"
    )

async def clearfix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear creatives"""
    global db
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.lower().strip()
    parts = text.split()
    
    if len(parts) < 2:
        await update.message.reply_text("Use: <code>clearfix 1</code> or <code>clearfix all</code>", parse_mode="HTML")
        return
    
    target = parts[1]
    
    if target == "all":
        count = len(db.get("creatives", {}))
        db["creatives"] = {}
        save_db(db)
        await update.message.reply_text(f"✅ Deleted {count} creatives.")
    else:
        fix_key = f"fix{target}"
        if fix_key in db.get("creatives", {}):
            del db["creatives"][fix_key]
            save_db(db)
            await update.message.reply_text(f"✅ Deleted {fix_key}")
        else:
            await update.message.reply_text(f"❌ {fix_key} not found.")

async def totalsignal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show total signal statistics"""
    text = update.message.text.lower().strip().replace("/", "")
    
    # Parse year range
    start_year, end_year = parse_year_range(text)
    
    if not start_year:
        start_year = get_year()
        end_year = get_year()
    
    stats = get_signal_stats(start_year, end_year)
    
    # Build month breakdown
    month_lines = []
    for year in sorted(stats["by_month"].keys()):
        if start_year != end_year:
            month_lines.append(f"\n<b>{year}</b>")
        for month, count in stats["by_month"][year].items():
            month_lines.append(f"  {month}  {count}")
    
    month_text = "\n".join(month_lines) if month_lines else "  No data"
    
    # Build team breakdown
    team_lines = []
    for member in TEAM_MEMBERS:
        count = stats["by_sender"].get(member, 0)
        team_lines.append(f"  {member.capitalize()}  {count}")
    team_text = "\n".join(team_lines)
    
    # Title
    if start_year == end_year:
        title = f"Signal Analytics {start_year}"
    else:
        title = f"Signal Analytics {start_year}-{end_year}"
    
    await update.message.reply_text(
        f"📊 <b>{title}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total Signals: {stats['total']}\n\n"
        f"<b>By Month</b>\n{month_text}\n\n"
        f"<b>By Team</b>\n{team_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )

async def total_member_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show total signals for a team member"""
    text = update.message.text.lower().strip().replace("/", "")
    
    # Determine which member
    member = None
    for m in TEAM_MEMBERS:
        if text.startswith(f"total{m}"):
            member = m
            text = text.replace(f"total{m}", "")
            break
    
    if not member:
        await update.message.reply_text("❌ Invalid command.")
        return
    
    # Parse year range
    start_year, end_year = parse_year_range("x" + text) if text else (None, None)
    
    if not start_year:
        start_year = get_year()
        end_year = get_year()
    
    stats = get_signal_stats(start_year, end_year, member)
    
    # Build month breakdown
    month_lines = []
    for year in sorted(stats["by_month"].keys()):
        if start_year != end_year:
            month_lines.append(f"\n<b>{year}</b>")
        for month, count in stats["by_month"][year].items():
            month_lines.append(f"  {month}  {count}")
    
    month_text = "\n".join(month_lines) if month_lines else "  No data"
    
    # Title
    if start_year == end_year:
        title = f"{member.capitalize()}'s Signals {start_year}"
    else:
        title = f"{member.capitalize()}'s Signals {start_year}-{end_year}"
    
    await update.message.reply_text(
        f"📊 <b>{title}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {stats['total']}\n\n"
        f"<b>By Month</b>\n{month_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )

async def views_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show views statistics"""
    text = update.message.text.lower().strip().replace("/", "").replace("views", "")
    
    # Parse year range
    start_year, end_year = parse_year_range("x" + text) if text else (None, None)
    
    if not start_year:
        start_year = get_year()
        end_year = get_year()
    
    # Get signals and their view data
    signals_data = db.get("signals", {})
    total_views = 0
    top_posts = []
    
    for year in range(int(start_year), int(end_year) + 1):
        year_str = str(year)
        if year_str not in signals_data:
            continue
        
        for month_key, signals in signals_data[year_str].items():
            for signal in signals:
                views = signal.get("views", 0)
                total_views += views
                top_posts.append({
                    "signal_id": signal.get("signal_id"),
                    "ticker": signal.get("ticker"),
                    "views": views
                })
    
    # Sort top posts
    top_posts.sort(key=lambda x: x["views"], reverse=True)
    top_5 = top_posts[:5]
    
    top_text = "\n".join([
        f"  #{p['signal_id']} {p['ticker']}  —  {p['views']} views" 
        for p in top_5
    ]) if top_5 else "  No data"
    
    # Title
    if start_year == end_year:
        title = f"Channel Views {start_year}"
    else:
        title = f"Channel Views {start_year}-{end_year}"
    
    last_updated = db.get("views", {}).get(get_ist_date(), {}).get("updated_at", "Never")
    
    await update.message.reply_text(
        f"📈 <b>{title}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total Views: {total_views:,}\n\n"
        f"<b>Top Posts</b>\n{top_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Last Updated: {last_updated}",
        parse_mode="HTML"
    )

async def channelstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel statistics"""
    stats = db.get("channel_stats", {})
    
    current = stats.get("current", 0)
    last_updated = stats.get("last_updated", "Never")
    daily = stats.get("daily", {})
    monthly = stats.get("monthly", {})
    
    # Calculate this month's growth
    month_key = get_month_key()
    month_data = monthly.get(month_key, {})
    month_start = month_data.get("start", current)
    month_net = current - month_start
    
    # Calculate last 7 days
    today = get_ist_now()
    week_ago_date = (today - timedelta(days=7)).strftime("%d %b %Y")
    week_ago_count = daily.get(week_ago_date, current)
    week_net = current - week_ago_count
    
    # Growth trend (last 4 months)
    trend_lines = []
    for i in range(4):
        month_dt = today - timedelta(days=30 * i)
        mk = month_dt.strftime("%Y-%m")
        month_name = month_dt.strftime("%b")
        md = monthly.get(mk, {})
        if md:
            net = md.get("end", 0) - md.get("start", 0)
            sign = "+" if net >= 0 else ""
            trend_lines.append(f"  {month_name}  {sign}{net}")
    
    trend_text = "\n".join(trend_lines) if trend_lines else "  No data"
    
    month_sign = "+" if month_net >= 0 else ""
    week_sign = "+" if week_net >= 0 else ""
    
    await update.message.reply_text(
        f"📊 <b>Channel Statistics</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total Members: {current:,}\n\n"
        f"<b>This Month</b>\n"
        f"  Net: {month_sign}{month_net}\n\n"
        f"<b>Last 7 Days</b>\n"
        f"  Net: {week_sign}{week_net}\n\n"
        f"<b>Growth Trend</b>\n{trend_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Last Updated: {last_updated}",
        parse_mode="HTML"
    )

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change signal format"""
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
    """Receive new format"""
    global db
    
    text = update.message.text
    
    if text.lower().strip() == "reset":
        db["settings"]["signal_format"] = None
        save_db(db)
        await update.message.reply_text("✅ Format reset to default!")
    else:
        db["settings"]["signal_format"] = text
        save_db(db)
        await update.message.reply_text("✅ Format saved!")
    
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    global pending_signals
    user_id = update.effective_user.id
    pending_signals.pop(user_id, None)
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages without commands"""
    if not BOT_ACTIVE:
        return
    
    text = update.message.text.lower().strip()
    
    # Signal shortcut (BTC 86800 90200 3x)
    parts = text.split()
    if len(parts) >= 4:
        try:
            # Check if it looks like a signal
            ticker = parts[0].upper()
            if ticker.isalpha() and len(ticker) <= 10:
                float(parts[1])  # entry
                float(parts[2])  # sl
                parts[3].lower().replace('x', '')  # leverage
                return await signal_command(update, context)
        except:
            pass
    
    # Other text commands
    if text == "delete":
        return await delete_command(update, context)
    elif text == "links":
        return await links_command(update, context)
    elif text.startswith("addlink"):
        return await addlink_command(update, context)
    elif text.startswith("clearlink"):
        return await clearlink_command(update, context)
    elif text == "list":
        return await list_command(update, context)
    elif text.startswith("clearfix"):
        return await clearfix_command(update, context)
    elif text.startswith("savefix") and len(text) >= 8:
        # savefix1, savefix2, etc. - for saving new creative
        return await fix_command(update, context)
    elif text == "help":
        return await help_command(update, context)
    elif text == "start123":
        return await start_command(update, context)
    elif text.startswith("totalsignal"):
        return await totalsignal_command(update, context)
    elif text.startswith("totalrohith") or text.startswith("totalrajini") or text.startswith("totalbalaji"):
        return await total_member_command(update, context)
    elif text.startswith("views"):
        return await views_command(update, context)
    elif text == "channelstats":
        return await channelstats_command(update, context)
    elif text == "format":
        return await format_command(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads - for saving creatives"""
    if not BOT_ACTIVE:
        return
    
    # Check if waiting for fix creative
    if context.user_data.get("waiting_for_fix"):
        await receive_fix_creative(update, context)


# ============== MAIN ==============

def main():
    global BOT_ACTIVE
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Signal conversation - highest priority
    signal_conv = ConversationHandler(
        entry_points=[
            CommandHandler("signal", signal_command),
            MessageHandler(filters.Regex(r'(?i)^signal\s'), signal_command),
        ],
        states={
            WAITING_FOR_CREATIVE: [
                MessageHandler(filters.PHOTO, receive_creative),
                MessageHandler(filters.Regex(r'(?i)^(use\s+)?fix\d+$'), receive_creative),  # "use fix1" or "fix1"
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_creative),
            ],
            WAITING_FOR_CONFIRM: [
                MessageHandler(filters.TEXT, confirm_send),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'(?i)^/?cancel$'), cancel_command),
        ],
        name="signal_conversation",
        persistent=False,
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
        ],
    )
    
    # Add handlers - signal_conv MUST be first
    application.add_handler(signal_conv)
    application.add_handler(format_conv)
    
    # Command handlers
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("links", links_command))
    application.add_handler(CommandHandler("addlink", addlink_command))
    application.add_handler(CommandHandler("clearlink", clearlink_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("clearfix", clearfix_command))
    application.add_handler(CommandHandler("totalsignal", totalsignal_command))
    application.add_handler(CommandHandler("views", views_command))
    application.add_handler(CommandHandler("channelstats", channelstats_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # Team member commands
    for member in TEAM_MEMBERS:
        application.add_handler(CommandHandler(f"total{member}", total_member_command))
    
    # Text handler for shortcuts
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Photo handler for savefix
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Schedule midnight task
    schedule_midnight_task(application)
    
    # Auto-activate bot
    BOT_ACTIVE = True
    
    logger.info("🚀 Mudrex Signal Bot v3.0 started!")
    logger.info(f"Admins: {ADMIN_IDS}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
