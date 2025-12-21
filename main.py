"""
🚀 MUDREX TRADING SIGNAL BOT
==============================
Complete Telegram bot for posting crypto trading signals

Commands:
    /signal ETH 3450 3300 3x              → Post signal with default trade URL
    /signal ETH 3450 3300 3x https://...  → Post signal with custom trade URL
    /fix                                   → Set default creative image
    /format                                → Change signal template

Features:
    ✅ Auto-calculations (Entry2, TP1, TP2, Holding Time, Potential Profit)
    ✅ Auto LONG/SHORT detection
    ✅ TradingView precision formatting
    ✅ IST timestamp
    ✅ Image + Signal + Clickable button
    ✅ Figma prompt output
"""

import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ============== CONFIGURATION (Environment Variables) ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@MudrexCryptoInsights")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]

# URLs
DEFAULT_TRADE_URL_BASE = os.environ.get("TRADE_URL_BASE", "https://mudrex.com/trade/")
LEADERBOARD_URL = os.environ.get("LEADERBOARD_URL", "https://t.me/officialmudrex/98446/99038")
CHALLENGE_URL = os.environ.get("CHALLENGE_URL", "https://t.me/officialmudrex/98446/98616")

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_CREATIVE = 1
WAITING_FOR_FIX_CREATIVE = 2
WAITING_FOR_FORMAT = 3

# ============== GLOBAL STORAGE ==============
bot_data = {
    "fixed_creative": None,
    "pending_signal": None,
    "signal_format": None,
}

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


# ============== TRADINGVIEW PRECISION ENGINE ==============
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


# ============== CALCULATION ENGINE ==============
def calculate_signal(ticker: str, entry1: float, sl: float, leverage: int = None) -> dict:
    """
    Calculate all signal parameters based on Entry1 and SL
    
    Rules:
    - Entry2 = midpoint of Entry1 and SL
    - AvgEntry = (Entry1 + Entry2) / 2
    - TP1 = 1:1 of AvgEntry
    - TP2 = 1:2 of AvgEntry
    - Direction: LONG if SL < Entry, SHORT if SL > Entry
    """
    
    # Detect direction
    direction = "LONG" if sl < entry1 else "SHORT"
    direction_emoji = "📈" if direction == "LONG" else "📉"
    
    # Calculate Entry2 (midpoint of Entry1 and SL)
    entry2 = (entry1 + sl) / 2
    
    # Calculate Average Entry
    avg_entry = (entry1 + entry2) / 2
    
    # Calculate risk (distance from avg_entry to SL)
    risk = abs(avg_entry - sl)
    
    # Calculate Take Profits
    if direction == "LONG":
        tp1 = avg_entry + risk       # 1:1
        tp2 = avg_entry + (2 * risk) # 1:2
    else:  # SHORT
        tp1 = avg_entry - risk       # 1:1
        tp2 = avg_entry - (2 * risk) # 1:2
    
    # Calculate SL percentage
    sl_percent = (risk / avg_entry) * 100
    
    # Auto-calculate leverage if not provided
    if leverage is None:
        if sl_percent > 30:
            leverage = 2
        elif sl_percent < 10:
            leverage = 5
        elif sl_percent >= 20:
            leverage = 3
        else:
            leverage = 4
    
    # Calculate holding time based on SL%
    if sl_percent <= 5:
        holding_time = "1–2 days"
    elif sl_percent <= 8:
        holding_time = "2–3 days"
    else:
        holding_time = "5–7 days"
    
    # Calculate potential profit
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
        "sl_percent": f"{sl_percent:.2f}%",
        "rr_ratio": "1:2",
        "challenge_url": CHALLENGE_URL,
        "leaderboard_url": LEADERBOARD_URL,
        "raw_entry1": entry1,
        "raw_entry2": entry2,
        "raw_tp1": tp1,
        "raw_tp2": tp2,
        "raw_sl": sl,
        "raw_avg_entry": avg_entry,
    }


# ============== IST TIMESTAMP ==============
def get_ist_timestamp() -> str:
    """Get current time in IST format"""
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now(ist)
    return now.strftime("%d %b %Y, %I:%M %p")


# ============== GENERATE SIGNAL TEXT ==============
def generate_signal_text(signal_data: dict) -> str:
    """Generate signal text from template"""
    template = bot_data.get("signal_format") or DEFAULT_FORMAT
    return template.format(**signal_data)


# ============== GENERATE FIGMA PROMPT ==============
def generate_figma_prompt(signal_data: dict) -> str:
    """Generate Figma agent instructions"""
    timestamp = get_ist_timestamp()
    
    return f"""📋 **FIGMA AGENT INSTRUCTIONS**

Within the selected frame in Figma, update the following text fields using the provided input data.
Do not alter any design, style, font, alignment, colors, sizing, or auto-layout settings—change only the text content.

```
Asset Name: {signal_data['ticker']}
Direction: {signal_data['direction']}
Leverage: {signal_data['leverage']}x
Entry Price: ${signal_data['entry1']} – ${signal_data['entry2']}
TP1: ${signal_data['tp1']}
TP2: ${signal_data['tp2']}
SL: ${signal_data['sl']}
Profit: {signal_data['potential_profit']}
Published On: {timestamp}
```

Instructions:
• For each field above, locate the corresponding text box in the selected frame and replace its content with the provided value.
• Do not modify any visual design or layout properties.
• Review and confirm all updates before saving."""


# ============== GENERATE SUMMARY BOX ==============
def generate_summary_box(signal_data: dict) -> str:
    """Generate summary box for pinned message"""
    timestamp = get_ist_timestamp()
    
    return f"""📊 **SUMMARY BOX**

```
Entry 1: ${signal_data['entry1']}
Entry 2: ${signal_data['entry2']}
Average Entry: ${signal_data['avg_entry']}
TP1: ${signal_data['tp1']}
TP2: ${signal_data['tp2']}
SL: ${signal_data['sl']}
⏰ Published On: {timestamp}
Potential Profit: {signal_data['potential_profit']}
```"""


# ============== COMMAND HANDLERS ==============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    await update.message.reply_text(
        "🚀 **MUDREX SIGNAL BOT**\n\n"
        "Commands:\n"
        "`/signal ETH 3450 3300 3x` - Post signal\n"
        "`/signal ETH 3450 3300 3x https://...` - With custom link\n"
        "`/fix` - Set default creative\n"
        "`/format` - Change signal template\n"
        "`/cancel` - Cancel operation\n\n"
        "Ready to post signals! 🔥",
        parse_mode="Markdown"
    )


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /signal command"""
    user_id = update.effective_user.id
    
    # Check if admin
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You're not authorized to use this bot.")
        return ConversationHandler.END
    
    # Parse command
    try:
        parts = update.message.text.split()
        
        if len(parts) < 5:
            await update.message.reply_text(
                "❌ Invalid format!\n\n"
                "Use: `/signal TICKER ENTRY SL LEVERAGE [custom_link]`\n"
                "Example: `/signal ETH 3450 3300 3x`\n"
                "Example: `/signal ETH 3450 3300 3x https://mudrex.com/adjust/xyz`",
                parse_mode="Markdown"
            )
            return ConversationHandler.END
        
        ticker = parts[1].upper()
        entry1 = float(parts[2])
        sl = float(parts[3])
        leverage = int(parts[4].replace('x', '').replace('X', ''))
        
        # Check for custom trade URL
        if len(parts) >= 6 and parts[5].startswith('http'):
            trade_url = parts[5]
        else:
            trade_url = f"{DEFAULT_TRADE_URL_BASE}{ticker}-USDT"
        
        # Calculate signal
        signal_data = calculate_signal(ticker, entry1, sl, leverage)
        signal_data['trade_url'] = trade_url
        
        # Store pending signal
        bot_data['pending_signal'] = signal_data
        
        # Preview calculation
        preview = (
            f"📊 **Signal Preview:**\n"
            f"Ticker: {signal_data['ticker']} {signal_data['direction']}\n"
            f"Entry1: ${signal_data['entry1']}\n"
            f"Entry2: ${signal_data['entry2']}\n"
            f"TP1: ${signal_data['tp1']}\n"
            f"TP2: ${signal_data['tp2']}\n"
            f"SL: ${signal_data['sl']}\n"
            f"Leverage: {signal_data['leverage']}x\n"
            f"Trade URL: {trade_url}\n\n"
        )
        
        # Check if fixed creative exists
        if bot_data.get('fixed_creative'):
            await update.message.reply_text(
                f"{preview}"
                f"🖼️ Send image OR type `use fixed` to use saved creative:",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"{preview}"
                f"🖼️ Drop your creative image:",
                parse_mode="Markdown"
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
    """Receive creative image and post signal"""
    
    # Check for "use fixed" text
    if update.message.text and update.message.text.lower() == "use fixed":
        if bot_data.get('fixed_creative'):
            creative_file_id = bot_data['fixed_creative']
        else:
            await update.message.reply_text("❌ No fixed creative set. Send an image or use `/fix` first.", parse_mode="Markdown")
            return WAITING_FOR_CREATIVE
    elif update.message.photo:
        creative_file_id = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("❌ Please send an image or type `use fixed`", parse_mode="Markdown")
        return WAITING_FOR_CREATIVE
    
    signal_data = bot_data.get('pending_signal')
    if not signal_data:
        await update.message.reply_text("❌ No pending signal. Use /signal first.")
        return ConversationHandler.END
    
    # Generate signal text
    signal_text = generate_signal_text(signal_data)
    
    # Create button
    keyboard = [[InlineKeyboardButton(f"TRADE NOW - {signal_data['ticker']} 🔥", url=signal_data['trade_url'])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send to channel
    try:
        bot = context.bot
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=creative_file_id,
            caption=signal_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        # Generate Figma prompt
        figma_prompt = generate_figma_prompt(signal_data)
        summary_box = generate_summary_box(signal_data)
        
        # Send confirmation to admin
        await update.message.reply_text(
            f"✅ **Signal posted successfully!**\n\n"
            f"📍 Ticker: {signal_data['ticker']}\n"
            f"📊 Direction: {signal_data['direction']}\n"
            f"🔗 Trade URL: {signal_data['trade_url']}",
            parse_mode="Markdown"
        )
        
        # Send Figma prompt separately
        await update.message.reply_text(figma_prompt, parse_mode="Markdown")
        
        # Send summary box separately
        await update.message.reply_text(summary_box, parse_mode="Markdown")
        
        # Clear pending signal
        bot_data['pending_signal'] = None
        
        logger.info(f"Signal posted: {signal_data['ticker']} {signal_data['direction']}")
        
    except Exception as e:
        logger.error(f"Error posting to channel: {e}")
        await update.message.reply_text(f"❌ Error posting to channel: {e}")
    
    return ConversationHandler.END


async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fix command - set default creative"""
    user_id = update.effective_user.id
    
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You're not authorized.")
        return ConversationHandler.END
    
    await update.message.reply_text("🖼️ Drop the creative image to set as default:")
    return WAITING_FOR_FIX_CREATIVE


async def receive_fix_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and save fixed creative"""
    if not update.message.photo:
        await update.message.reply_text("❌ Please send an image.")
        return WAITING_FOR_FIX_CREATIVE
    
    bot_data['fixed_creative'] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Fixed creative saved!\n\nType `use fixed` when posting signals to use this image.")
    logger.info("Fixed creative updated")
    return ConversationHandler.END


async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /format command - change signal template"""
    user_id = update.effective_user.id
    
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You're not authorized.")
        return ConversationHandler.END
    
    placeholders = """
`{ticker}` - ETH, BTC
`{direction}` - LONG/SHORT
`{direction_emoji}` - 📈/📉
`{leverage}` - 3
`{holding_time}` - 2-3 days
`{entry1}`, `{entry2}` - Entry prices
`{tp1}`, `{tp2}` - Take profits
`{sl}` - Stop loss
`{avg_entry}` - Average entry
`{potential_profit}` - 23.08%
`{challenge_url}` - Challenge link
`{leaderboard_url}` - Leaderboard link
"""
    
    await update.message.reply_text(
        f"📝 **Send your new signal format template**\n\n"
        f"Available placeholders:\n{placeholders}\n\n"
        f"Or send `reset` to use default format.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_FORMAT


async def receive_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and save new format"""
    text = update.message.text
    
    if text.lower() == "reset":
        bot_data['signal_format'] = None
        await update.message.reply_text("✅ Format reset to default!")
        logger.info("Signal format reset to default")
    else:
        bot_data['signal_format'] = text
        await update.message.reply_text("✅ New format saved!")
        logger.info("Signal format updated")
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    bot_data['pending_signal'] = None
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")


# ============== MAIN ==============
def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Signal conversation handler
    signal_handler = ConversationHandler(
        entry_points=[CommandHandler("signal", signal_command)],
        states={
            WAITING_FOR_CREATIVE: [
                MessageHandler(filters.PHOTO, receive_creative),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_creative),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Fix conversation handler
    fix_handler = ConversationHandler(
        entry_points=[CommandHandler("fix", fix_command)],
        states={
            WAITING_FOR_FIX_CREATIVE: [MessageHandler(filters.PHOTO, receive_fix_creative)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Format conversation handler
    format_handler = ConversationHandler(
        entry_points=[CommandHandler("format", format_command)],
        states={
            WAITING_FOR_FORMAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_format)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(signal_handler)
    application.add_handler(fix_handler)
    application.add_handler(format_handler)
    application.add_error_handler(error_handler)
    
    # Start polling
    logger.info("🚀 Mudrex Signal Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
