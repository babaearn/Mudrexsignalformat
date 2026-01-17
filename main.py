"""
🚀 MUDREX TRADING SIGNAL BOT v3.0
==================================
Complete Telegram bot for posting crypto trading signals

Features:
- Signal posting with preview
- Team tracking (Rohith, Rajini, Balaji)
- Google Sheets auto-sync
- Unlimited creatives (fix1, fix2...)
- Auto-save deeplinks per ticker
- Year-based signal analytics
- Channel stats & views tracking
- Midnight IST auto-save
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Google Sheets imports
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False

# ============== CONFIGURATION ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1002163454656")

# Google Sheets Configuration
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "PnL Update")  # Sheet tab name

# Admin IDs - supports admin_id1, admin_id2, admin_id3, etc.
ADMIN_IDS = []
for key, value in os.environ.items():
    if key.lower().startswith("admin_id") and value.strip():
        try:
            ADMIN_IDS.append(int(value.strip()))
        except ValueError:
            pass

# Database file path
DB_PATH = Path("/app/data/database.json") if os.path.exists("/app") else Path("database.json")

# Team members
TEAM_MEMBERS = ["rohith", "rajini", "balaji"]

# Logging - Only show warnings and errors
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
logging.getLogger("googleapiclient").setLevel(logging.WARNING)

# Conversation states
WAITING_FOR_CREATIVE = 1
WAITING_FOR_CONFIRM = 2
WAITING_FOR_FIX_CREATIVE = 3
WAITING_FOR_FORMAT = 4

# IST Timezone
IST = ZoneInfo("Asia/Kolkata")

# Bot active state
BOT_ACTIVE = False

# Bot start time for uptime tracking
BOT_START_TIME = None

# Google Sheets service
sheets_service = None


# ============== GOOGLE SHEETS ==============

def init_google_sheets():
    """Initialize Google Sheets API service"""
    global sheets_service
    
    if not SHEETS_AVAILABLE:
        logger.warning("Google Sheets libraries not installed")
        return False
    
    if not GOOGLE_SHEETS_CREDENTIALS or not GOOGLE_SHEET_ID:
        logger.warning("Google Sheets credentials or Sheet ID not configured")
        return False
    
    try:
        # Parse credentials from environment variable
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        
        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        
        sheets_service = build('sheets', 'v4', credentials=credentials)
        logger.info("Google Sheets API initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
        return False

def append_to_sheet(signal_data: dict) -> bool:
    """Append signal data to Google Sheet"""
    global sheets_service
    
    if not sheets_service:
        logger.warning("Google Sheets not initialized")
        return False
    
    try:
        # Prepare row data matching your sheet columns:
        # Timestamp | Symbol | Direction | Leverage | Entry 1 | Entry 2 | TP1 | TP2 | Stop Loss | Status | Highest TP Hit | ROI | ROI % | ROI Value
        row = [
            signal_data.get('timestamp', ''),      # Timestamp
            signal_data.get('ticker', ''),         # Symbol
            signal_data.get('direction', ''),      # Direction
            signal_data.get('leverage', ''),       # Leverage
            signal_data.get('entry1', ''),         # Entry 1
            signal_data.get('entry2', ''),         # Entry 2
            signal_data.get('tp1', ''),            # TP1
            signal_data.get('tp2', ''),            # TP2
            signal_data.get('sl', ''),             # Stop Loss
            'ACTIVE',                              # Status (default)
            '',                                    # Highest TP Hit (manual)
            '',                                    # ROI (formula/manual)
            '',                                    # ROI % (formula/manual)
            '',                                    # ROI Value (formula/manual)
        ]
        
        body = {'values': [row]}
        
        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"'{SHEET_NAME}'!A:N",
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        logger.info(f"Signal added to Google Sheet: {signal_data.get('ticker')}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to append to Google Sheet: {e}")
        return False


# ============== DATABASE ==============

# Pre-loaded Adjust Links (626 tokens from Mudrex Futures)
PRELOADED_ADJUST_LINKS = {"BTC": "https://mudrex.go.link/1Yogo", "ETH": "https://mudrex.go.link/kmYNX", "BNB": "https://mudrex.go.link/3G8Mh", "SOL": "https://mudrex.go.link/g6445", "USDC": "https://mudrex.go.link/kDf6w", "XRP": "https://mudrex.go.link/h6Nof", "DOGE": "https://mudrex.go.link/8BuD2", "ADA": "https://mudrex.go.link/hKGmX", "AVAX": "https://mudrex.go.link/dZEy1", "TRX": "https://mudrex.go.link/lnojH", "LINK": "https://mudrex.go.link/6fvof", "DOT": "https://mudrex.go.link/2Xc0B", "BCH": "https://mudrex.go.link/iXh5Q", "UNI": "https://mudrex.go.link/4BQrV", "NEAR": "https://mudrex.go.link/4abAr", "LTC": "https://mudrex.go.link/5KhId", "ICP": "https://mudrex.go.link/8oFyE", "ETC": "https://mudrex.go.link/5UlJJ", "APT": "https://mudrex.go.link/3jz4i", "HBAR": "https://mudrex.go.link/cYDjC", "XLM": "https://mudrex.go.link/3mvNd", "ATOM": "https://mudrex.go.link/cpkYU", "FIL": "https://mudrex.go.link/2wnCx", "STX": "https://mudrex.go.link/ik2aE", "IMX": "https://mudrex.go.link/GRCEi", "MKR": "https://mudrex.go.link/ciFFE", "VET": "https://mudrex.go.link/6XUUJ", "GRT": "https://mudrex.go.link/gGppc", "OP": "https://mudrex.go.link/ivoLn", "AR": "https://mudrex.go.link/3wXbs", "JASMY": "https://mudrex.go.link/93h9I", "CRV": "https://mudrex.go.link/l8DBq", "ENS": "https://mudrex.go.link/8lqHU", "RUNE": "https://mudrex.go.link/2ywzj", "ARB": "https://mudrex.go.link/80iC5", "ENA": "https://mudrex.go.link/5KVOf", "ETHFI": "https://mudrex.go.link/6yGSS", "STRK": "https://mudrex.go.link/gNjvO", "SUI": "https://mudrex.go.link/djU1j", "ARKM": "https://mudrex.go.link/id1ub", "USTC": "https://mudrex.go.link/92g3I", "SEI": "https://mudrex.go.link/dfYuY", "DYM": "https://mudrex.go.link/c9LXx", "IO": "https://mudrex.go.link/9FGTj", "BOME": "https://mudrex.go.link/eIrCK", "JUP": "https://mudrex.go.link/fRHkD", "ZK": "https://mudrex.go.link/2NVXz", "OM": "https://mudrex.go.link/e7w9Y", "PYTH": "https://mudrex.go.link/hxEFz", "TAO": "https://mudrex.go.link/cX2j6", "MANTA": "https://mudrex.go.link/1vtB8", "JTO": "https://mudrex.go.link/a7LDw", "BLUR": "https://mudrex.go.link/hj2GQ", "SAGA": "https://mudrex.go.link/kMrS9", "AERGO": "https://mudrex.go.link/6FNGk", "OG": "https://mudrex.go.link/44fHa", "GNO": "https://mudrex.go.link/ikUTm", "BSW": "https://mudrex.go.link/9dvOE", "JST": "https://mudrex.go.link/iujBU", "OSMO": "https://mudrex.go.link/kXXxf", "COS": "https://mudrex.go.link/6zBZX", "FORTH": "https://mudrex.go.link/lvUDP", "NKN": "https://mudrex.go.link/el4Nx", "BAL": "https://mudrex.go.link/lv8fN", "PROM": "https://mudrex.go.link/ciKWR", "IDEX": "https://mudrex.go.link/4bpe4", "MBL": "https://mudrex.go.link/eBwmd", "CTK": "https://mudrex.go.link/4sfr0", "XNO": "https://mudrex.go.link/2VlfM", "MBOX": "https://mudrex.go.link/8LCDF", "WAXP": "https://mudrex.go.link/fiTXa", "BOBA": "https://mudrex.go.link/c1RXZ", "DODO": "https://mudrex.go.link/3okFt", "VTHO": "https://mudrex.go.link/fKmDD", "REQ": "https://mudrex.go.link/iIsJK", "CVC": "https://mudrex.go.link/29Cso", "SFP": "https://mudrex.go.link/2E86s", "DENT": "https://mudrex.go.link/9c3h9", "LOOKS": "https://mudrex.go.link/kz06D", "SUN": "https://mudrex.go.link/4lT94", "BAND": "https://mudrex.go.link/lHHwN", "PHA": "https://mudrex.go.link/epb5n", "T": "https://mudrex.go.link/2onI4", "RLC": "https://mudrex.go.link/7wtkD", "BADGER": "https://mudrex.go.link/lcG6A", "QI": "https://mudrex.go.link/QIUSDT", "SXP": "https://mudrex.go.link/sxpusdt", "LQTY": "https://mudrex.go.link/LQTYUSDT", "SCRT": "https://mudrex.go.link/SCRT", "CRO": "https://mudrex.go.link/iNUXQ", "XCN": "https://mudrex.go.link/XCN", "STEEM": "https://mudrex.go.link/STEEM", "CTSI": "https://mudrex.go.link/CTSI", "ARPA": "https://mudrex.go.link/ARPA", "SNT": "https://mudrex.go.link/SNT", "BNT": "https://mudrex.go.link/BNT", "OXT": "https://mudrex.go.link/OXT", "SKL": "https://mudrex.go.link/SKL", "DGB": "https://mudrex.go.link/DGB", "KNC": "https://mudrex.go.link/KNC", "POWR": "https://mudrex.go.link/POWR", "XVS": "https://mudrex.go.link/XVS", "HFT": "https://mudrex.go.link/HFT", "RARE": "https://mudrex.go.link/RARE", "AGLD": "https://mudrex.go.link/AGLD", "BAT": "https://mudrex.go.link/aWkbq", "OGN": "https://mudrex.go.link/OGNUSDT", "HOOK": "https://mudrex.go.link/HOOK", "RVN": "https://mudrex.go.link/RVN", "CTC": "https://mudrex.go.link/CTC", "MAV": "https://mudrex.go.link/MAV", "IOST": "https://mudrex.go.link/IOST", "BICO": "https://mudrex.go.link/BICO", "ICX": "https://mudrex.go.link/ICX", "MTL": "https://mudrex.go.link/MTL", "ALPHA": "https://mudrex.go.link/ALPHA", "KAVA": "https://mudrex.go.link/KAVA", "ATA": "https://mudrex.go.link/ATA", "LRC": "https://mudrex.go.link/LRCUSDT", "CELR": "https://mudrex.go.link/CERL", "QNT": "https://mudrex.go.link/1047W", "ONT": "https://mudrex.go.link/ONT", "TWT": "https://mudrex.go.link/4ILyp", "GLMR": "https://mudrex.go.link/GLMR", "HIFI": "https://mudrex.go.link/HIFI", "ANKR": "https://mudrex.go.link/ANKR", "RIF": "https://mudrex.go.link/RIF", "PAXG": "https://mudrex.go.link/PAXG", "METIS": "https://mudrex.go.link/METIS", "TLM": "https://mudrex.go.link/TLM", "YFI": "https://mudrex.go.link/YFI", "XMR": "https://mudrex.go.link/ilbvY", "AUCTION": "https://mudrex.go.link/ACTION", "BEL": "https://mudrex.go.link/BEL", "IOTA": "https://mudrex.go.link/IOTA", "ENJ": "https://mudrex.go.link/ENJUSDT", "LSK": "https://mudrex.go.link/LSK", "RPL": "https://mudrex.go.link/RPL", "SPELL": "https://mudrex.go.link/SPELL", "NTRN": "https://mudrex.go.link/NTRN", "GTC": "https://mudrex.go.link/GTC", "ONG": "https://mudrex.go.link/ONG", "RAD": "https://mudrex.go.link/RAD", "ONE": "https://mudrex.go.link/ONE", "REZ": "https://mudrex.go.link/REN", "RSS3": "https://mudrex.go.link/RSS3", "SWEAT": "https://mudrex.go.link/SWEAT", "ONDO": "https://mudrex.go.link/ciJVT", "GODS": "https://mudrex.go.link/GODS", "CORE": "https://mudrex.go.link/CORE", "MNT": "https://mudrex.go.link/MNT", "KAS": "https://mudrex.go.link/KASUSDT", "MYRO": "https://mudrex.go.link/MYRO", "DEGEN": "https://mudrex.go.link/DEGEN", "BRETT": "https://mudrex.go.link/7zBLe", "MEW": "https://mudrex.go.link/MEW", "PONKE": "https://mudrex.go.link/PONKE", "POPCAT": "https://mudrex.go.link/POPCAT", "BLAST": "https://mudrex.go.link/BLAST", "FLR": "https://mudrex.go.link/FLR", "AGI": "https://mudrex.go.link/AGI", "VELO": "https://mudrex.go.link/VELO", "TOKEN": "https://mudrex.go.link/TOKEN", "MYRIA": "https://mudrex.go.link/MYRIA", "AIOZ": "https://mudrex.go.link/AIOZ", "ZETA": "https://mudrex.go.link/ZETA", "MAVIA": "https://mudrex.go.link/MAVIA", "SCA": "https://mudrex.go.link/SCA", "PRCL": "https://mudrex.go.link/PRCL", "MERL": "https://mudrex.go.link/MERL", "SAFE": "https://mudrex.go.link/SAFE", "DRIFT": "https://mudrex.go.link/DRIFT", "TAIKO": "https://mudrex.go.link/TAIKO", "ATH": "https://mudrex.go.link/ATH", "MASA": "https://mudrex.go.link/MASA", "KMNO": "https://mudrex.go.link/KMNO", "MOCA": "https://mudrex.go.link/MOCA", "XTZ": "https://mudrex.go.link/c1JgB", "XEM": "https://mudrex.go.link/XEM", "SUSHI": "https://mudrex.go.link/cHJxv", "AAVE": "https://mudrex.go.link/7aMeO", "AXS": "https://mudrex.go.link/AXS", "THETA": "https://mudrex.go.link/THETA", "COMP": "https://mudrex.go.link/COMP", "ALGO": "https://mudrex.go.link/ALGO", "DYDX": "https://mudrex.go.link/DYDX", "KSM": "https://mudrex.go.link/KSM", "CHZ": "https://mudrex.go.link/CHZ", "DASH": "https://mudrex.go.link/b3iTo", "ALICE": "https://mudrex.go.link/ALICE", "SAND": "https://mudrex.go.link/SAND", "MANA": "https://mudrex.go.link/MANA", "GALA": "https://mudrex.go.link/GALA", "WOO": "https://mudrex.go.link/WOO", "IOTX": "https://mudrex.go.link/IOTX", "CHR": "https://mudrex.go.link/CHR", "SLP": "https://mudrex.go.link/SLP", "STORJ": "https://mudrex.go.link/STORJ", "EGLD": "https://mudrex.go.link/EGLDUSDT", "YGG": "https://mudrex.go.link/YGG", "ZEC": "https://mudrex.go.link/zec", "ILV": "https://mudrex.go.link/ILV", "AUDIO": "https://mudrex.go.link/AUDIO", "ZEN": "https://mudrex.go.link/11qTy", "FLOW": "https://mudrex.go.link/FLOW", "SC": "https://mudrex.go.link/SCUSDT", "RSR": "https://mudrex.go.link/goNFc", "COTI": "https://mudrex.go.link/COTI", "MASK": "https://mudrex.go.link/MASK", "1INCH": "https://mudrex.go.link/1INCH", "BSV": "https://mudrex.go.link/BSV", "SNX": "https://mudrex.go.link/SNX", "LPT": "https://mudrex.go.link/LPT", "QTUM": "https://mudrex.go.link/QTUM", "DUSK": "https://mudrex.go.link/DUSK", "PEOPLE": "https://mudrex.go.link/PEOPLE", "CELO": "https://mudrex.go.link/CELO", "WAVES": "https://mudrex.go.link/WAVES", "C98": "https://mudrex.go.link/C98", "ROSE": "https://mudrex.go.link/ROSE", "HNT": "https://mudrex.go.link/HNT", "ZIL": "https://mudrex.go.link/ZIL", "NEO": "https://mudrex.go.link/NEO", "CKB": "https://mudrex.go.link/CKB", "API3": "https://mudrex.go.link/API3USDT", "APE": "https://mudrex.go.link/APE", "GMT": "https://mudrex.go.link/GMT", "HOT": "https://mudrex.go.link/HOT", "ZRX": "https://mudrex.go.link/ZRX", "BAKE": "https://mudrex.go.link/hsfaH", "FXS": "https://mudrex.go.link/FXS", "ASTR": "https://mudrex.go.link/ASTR", "MINA": "https://mudrex.go.link/MINA", "ACH": "https://mudrex.go.link/ACH", "CVX": "https://mudrex.go.link/CVX", "FLM": "https://mudrex.go.link/FLMUSDT", "LUNA2": "https://mudrex.go.link/LUNA2", "TRB": "https://mudrex.go.link/TRB", "LDO": "https://mudrex.go.link/LDO", "INJ": "https://mudrex.go.link/INJ", "STG": "https://mudrex.go.link/STG", "GMX": "https://mudrex.go.link/GMX", "NMR": "https://mudrex.go.link/NMR", "UMA": "https://mudrex.go.link/UMA", "TRU": "https://mudrex.go.link/TRU", "CAKE": "https://mudrex.go.link/cake", "SUPER": "https://mudrex.go.link/SUPER", "CFX": "https://mudrex.go.link/cRli2", "XVG": "https://mudrex.go.link/XVG", "DEXE": "https://mudrex.go.link/DEXE", "QUICK": "https://mudrex.go.link/QUICK", "SYS": "https://mudrex.go.link/SYS", "CHESS": "https://mudrex.go.link/CHESS", "MOVR": "https://mudrex.go.link/MOVR", "FLUX": "https://mudrex.go.link/FLUX", "JOE": "https://mudrex.go.link/JOE", "VOXEL": "https://mudrex.go.link/VOXEL", "HIGH": "https://mudrex.go.link/HIGH", "POLYX": "https://mudrex.go.link/POLYX", "PHB": "https://mudrex.go.link/PHB", "MAGIC": "https://mudrex.go.link/MAGIC", "WLD": "https://mudrex.go.link/WLD", "SSV": "https://mudrex.go.link/SSV", "SYN": "https://mudrex.go.link/SYN", "MEME": "https://mudrex.go.link/MEME", "ID": "https://mudrex.go.link/IDUSDT", "RDNT": "https://mudrex.go.link/RDNT", "EDU": "https://mudrex.go.link/EDU", "PENDLE": "https://mudrex.go.link/PENDLE", "CYBER": "https://mudrex.go.link/CYBER", "TIA": "https://mudrex.go.link/TIA", "ORDI": "https://mudrex.go.link/ORDI", "VANRY": "https://mudrex.go.link/VANRY", "ACE": "https://mudrex.go.link/ACE", "NFP": "https://mudrex.go.link/NFP", "AI": "https://mudrex.go.link/f2ls8", "XAI": "https://mudrex.go.link/XAI", "GAS": "https://mudrex.go.link/gas", "GLM": "https://mudrex.go.link/GLM", "ARK": "https://mudrex.go.link/ARK", "PIXEL": "https://mudrex.go.link/PIXEL", "ALT": "https://mudrex.go.link/ATL", "AXL": "https://mudrex.go.link/AXL", "PORTAL": "https://mudrex.go.link/PORTAL", "WIF": "https://mudrex.go.link/2rObR", "AEVO": "https://mudrex.go.link/AEVO", "W": "https://mudrex.go.link/WUSDT", "TNSR": "https://mudrex.go.link/TNSR", "OMNI": "https://mudrex.go.link/jX83d", "BB": "https://mudrex.go.link/BBUSDT", "NOT": "https://mudrex.go.link/NOT", "LISTA": "https://mudrex.go.link/LISTA", "ZRO": "https://mudrex.go.link/ZRO", "G": "https://mudrex.go.link/GUSDT", "BANANA": "https://mudrex.go.link/BANANA", "RENDER": "https://mudrex.go.link/ceGKB", "MOODENG": "https://mudrex.go.link/MOODENG", "1000CATS": "https://mudrex.go.link/1000CATS", "1000X": "https://mudrex.go.link/1000X", "HPOS10I": "https://mudrex.go.link/HPOS10I", "PUFFER": "https://mudrex.go.link/PUFFER", "A8": "https://mudrex.go.link/A8USDT", "AERO": "https://mudrex.go.link/AERO", "AVAIL": "https://mudrex.go.link/AVAIL", "BAN": "https://mudrex.go.link/BAN", "CARV": "https://mudrex.go.link/CARV", "CHILLGUY": "https://mudrex.go.link/CHILLYGUY", "CLOUD": "https://mudrex.go.link/CLOUD", "DBR": "https://mudrex.go.link/DBR", "DEEP": "https://mudrex.go.link/DEEP", "FIDA": "https://mudrex.go.link/FIDA", "FIO": "https://mudrex.go.link/FIO", "GOAT": "https://mudrex.go.link/GOAT", "GRASS": "https://mudrex.go.link/GRASS", "L3": "https://mudrex.go.link/L3USDT0", "ORDER": "https://mudrex.go.link/i6ugG", "PYR": "https://mudrex.go.link/PYR", "SPEC": "https://mudrex.go.link/SPEC", "SUNDOG": "https://mudrex.go.link/SUNDOG", "SWELL": "https://mudrex.go.link/SWELL", "UXLINK": "https://mudrex.go.link/UXLINK", "VIRTUAL": "https://mudrex.go.link/VIRTUAL", "TRUMP": "https://mudrex.go.link/9CKlG", "MELANIA": "https://mudrex.go.link/MELANIA", "VINE": "https://mudrex.go.link/frCnW", "ANIME": "https://mudrex.go.link/ANIME", "1000TOSHI": "https://mudrex.go.link/1000TOSH", "MUBARAK": "https://mudrex.go.link/MUBARAK", "S": "https://mudrex.go.link/5AzYW", "AVL": "https://mudrex.go.link/5VJlV", "BERA": "https://mudrex.go.link/BERA", "J": "https://mudrex.go.link/JUSDT", "PLUME": "https://mudrex.go.link/PLUME", "GPS": "https://mudrex.go.link/GPS", "B3": "https://mudrex.go.link/B3USDT", "AIXBT": "https://mudrex.go.link/AIXBT", "AI16Z": "https://mudrex.go.link/AI16Z", "SERAPH": "https://mudrex.go.link/jpCKA", "FLOCK": "https://mudrex.go.link/FLOCK", "RED": "https://mudrex.go.link/RED", "SOLV": "https://mudrex.go.link/SOLV", "PENGU": "https://mudrex.go.link/1rd6r", "PNUT": "https://mudrex.go.link/PNUT", "SCR": "https://mudrex.go.link/SCR", "HMSTR": "https://mudrex.go.link/HMSTR", "POL": "https://mudrex.go.link/cPywM", "TON": "https://mudrex.go.link/ton", "ALCH": "https://mudrex.go.link/ALCH", "ELX": "https://mudrex.go.link/kCW97", "ROAM": "https://mudrex.go.link/ROAM", "BMT": "https://mudrex.go.link/BMT", "IP": "https://mudrex.go.link/3xMPc", "COOK": "https://mudrex.go.link/COOK", "NS": "https://mudrex.go.link/NSUSDT", "AVA": "https://mudrex.go.link/AVA", "FUEL": "https://mudrex.go.link/FUEL", "SEND": "https://mudrex.go.link/SENDUSDT", "MAJOR": "https://mudrex.go.link/MAJOR", "HYPER": "https://mudrex.go.link/fqQ25", "SIGN": "https://mudrex.go.link/SIGN", "INIT": "https://mudrex.go.link/INIT", "MORPHO": "https://mudrex.go.link/MORPHO", "HAEDAL": "https://mudrex.go.link/HAEDAL", "MILK": "https://mudrex.go.link/MILK", "OBOL": "https://mudrex.go.link/OBOL", "SXT": "https://mudrex.go.link/SXT", "1000000MOG": "https://mudrex.go.link/MOG", "10000SATS": "https://mudrex.go.link/10000SATS", "1000BONK": "https://mudrex.go.link/BONK", "1000FLOKI": "https://mudrex.go.link/FLOKI", "1000NEIROCTO": "https://mudrex.go.link/NEIROCTO", "1000PEPE": "https://mudrex.go.link/PEPE", "1000RATS": "https://mudrex.go.link/RATS", "ARC": "https://mudrex.go.link/ARC", "COW": "https://mudrex.go.link/COW", "FARTCOIN": "https://mudrex.go.link/FARTCOIN", "GORK": "https://mudrex.go.link/GORK", "GRIFFAIN": "https://mudrex.go.link/GRIFFAIN", "HYPE": "https://mudrex.go.link/fYNEv", "JELLYJELLY": "https://mudrex.go.link/JELLYJELLY", "KAITO": "https://mudrex.go.link/KAITO", "LAUNCHCOIN": "https://mudrex.go.link/LAUNCHCOIN", "SHIB1000": "https://mudrex.go.link/5rgfQ", "SOLAYER": "https://mudrex.go.link/SOLAYER", "SONIC": "https://mudrex.go.link/dz0mW", "BABY": "https://mudrex.go.link/BABY", "AVAAI": "https://mudrex.go.link/AVAAI", "STO": "https://mudrex.go.link/STO", "PIPPIN": "https://mudrex.go.link/PIPPIN", "ZBCN": "https://mudrex.go.link/ZBCN", "DOG": "https://mudrex.go.link/DOG", "REX": "https://mudrex.go.link/REX", "NIL": "https://mudrex.go.link/NIL", "SWARMS": "https://mudrex.go.link/SWARMS", "ORCA": "https://mudrex.go.link/ORCA", "1000TURBO": "https://mudrex.go.link/TURBO", "SYRUP": "https://mudrex.go.link/SYRUP", "1000CAT": "https://mudrex.go.link/CAT", "CETUS": "https://mudrex.go.link/CETUS", "KERNEL": "https://mudrex.go.link/KERNEL", "THE": "https://mudrex.go.link/THE", "BIO": "https://mudrex.go.link/BIO", "FWOG": "https://mudrex.go.link/FWOG", "USUAL": "https://mudrex.go.link/USUAL", "BANK": "https://mudrex.go.link/BANK", "DARK": "https://mudrex.go.link/DARK", "FORM": "https://mudrex.go.link/ccbhQ", "ACT": "https://mudrex.go.link/ACT", "HIPPO": "https://mudrex.go.link/HIIPPO", "RFC": "https://mudrex.go.link/RFC", "PROMPT": "https://mudrex.go.link/PROMPT", "BEAM": "https://mudrex.go.link/BEAM", "GIGA": "https://mudrex.go.link/GIGA", "KOMA": "https://mudrex.go.link/KOMA", "1000000BABYDOGE": "https://mudrex.go.link/BABYDOGE", "AKT": "https://mudrex.go.link/AKT", "TSTBSC": "https://mudrex.go.link/TSTBSC", "BIGTIME": "https://mudrex.go.link/BIGTIME", "RAYDIUM": "https://mudrex.go.link/RAYDIUM", "SKYAI": "https://mudrex.go.link/SKYAI", "BROCCOLI": "https://mudrex.go.link/BROCCOLI", "SHELL": "https://mudrex.go.link/SHELL", "1000000CHEEMS": "https://mudrex.go.link/CHEEMS", "TUT": "https://mudrex.go.link/TUT", "10000LADYS": "https://mudrex.go.link/LADYS", "10000WHY": "https://mudrex.go.link/WHY", "1000LUNC": "https://mudrex.go.link/LUNC", "AWE": "https://mudrex.go.link/AWE", "B": "https://mudrex.go.link/BUSDT", "BANANAS31": "https://mudrex.go.link/BANANAS31", "EPIC": "https://mudrex.go.link/8fJvl", "F": "https://mudrex.go.link/FUSDT", "GUN": "https://mudrex.go.link/GUN", "HEI": "https://mudrex.go.link/HEI", "LUMIA": "https://mudrex.go.link/LUMIA", "OL": "https://mudrex.go.link/OLUSDT", "PEAQ": "https://mudrex.go.link/PEAQ", "SIREN": "https://mudrex.go.link/SIREN", "SOON": "https://mudrex.go.link/iO7JO", "VELODROME": "https://mudrex.go.link/VELODROME", "ZEUS": "https://mudrex.go.link/ZEUS", "1000000PEIPEI": "https://mudrex.go.link/PEIPEI", "10000COQ": "https://mudrex.go.link/COQ", "10000ELON": "https://mudrex.go.link/ELON", "10000QUBIC": "https://mudrex.go.link/QUBIC", "10000WEN": "https://mudrex.go.link/WEN", "1000BTT": "https://mudrex.go.link/1000BTT", "1000XEC": "https://mudrex.go.link/XEC", "ACX": "https://mudrex.go.link/ACX", "ALEO": "https://mudrex.go.link/ALEO", "ALU": "https://mudrex.go.link/ALU", "CLANKER": "https://mudrex.go.link/CLANKER", "DUCK": "https://mudrex.go.link/DUCK", "MOBILE": "https://mudrex.go.link/MOBILE", "ORBS": "https://mudrex.go.link/ORBS", "SLERF": "https://mudrex.go.link/SLERF", "SLF": "https://mudrex.go.link/SLF", "USDE": "https://mudrex.go.link/USDE", "VR": "https://mudrex.go.link/VRUSDT", "XCH": "https://mudrex.go.link/XCHUSDT", "BR": "https://mudrex.go.link/BRUSDT", "CATI": "https://mudrex.go.link/CATI", "DOGS": "https://mudrex.go.link/DOGS", "DOOD": "https://mudrex.go.link/DOOD", "EIGEN": "https://mudrex.go.link/EIGEN", "EPT": "https://mudrex.go.link/EPT", "FHE": "https://mudrex.go.link/FHE", "HIVE": "https://mudrex.go.link/HIVE", "KAIA": "https://mudrex.go.link/KAIA", "ME": "https://mudrex.go.link/MEUSDT", "MLN": "https://mudrex.go.link/MLN", "MOVE": "https://mudrex.go.link/MOVE", "NXPC": "https://mudrex.go.link/NXPC", "OBT": "https://mudrex.go.link/OBT", "PARTI": "https://mudrex.go.link/PARTI", "PUNDIX": "https://mudrex.go.link/PUNDIXUSDT", "RONIN": "https://mudrex.go.link/RONIN", "VANA": "https://mudrex.go.link/VANA", "VIC": "https://mudrex.go.link/VIC", "VVV": "https://mudrex.go.link/VVV", "WAL": "https://mudrex.go.link/WAL", "WCT": "https://mudrex.go.link/WCT", "XAUT": "https://mudrex.go.link/kHROS", "A": "https://mudrex.go.link/ausdt", "BDXN": "https://mudrex.go.link/BDXN", "CUDIS": "https://mudrex.go.link/CUDIS", "ETHBTC": "https://mudrex.go.link/ETHBTC", "HOME": "https://mudrex.go.link/HOME", "HUMA": "https://mudrex.go.link/HUMA", "LA": "https://mudrex.go.link/LAUSDT", "PUMPBTC": "https://mudrex.go.link/PUMPBTC", "RESOLV": "https://mudrex.go.link/RESOLV", "SKATE": "https://mudrex.go.link/SKATE", "B2": "https://mudrex.go.link/B2USDT", "SOPH": "https://mudrex.go.link/SOPH", "AGT": "https://mudrex.go.link/AGT", "PUMPFUN": "https://mudrex.go.link/jFKUX", "SOSO": "https://mudrex.go.link/bGwua", "FRAG": "https://mudrex.go.link/jIeEH", "ICNT": "https://mudrex.go.link/8nnku", "DMC": "https://mudrex.go.link/lzJFQ", "H": "https://mudrex.go.link/3N3rS", "SAHARA": "https://mudrex.go.link/2neTr", "NEWT": "https://mudrex.go.link/hH5AK", "SPK": "https://mudrex.go.link/dP2cL", "CGPT": "https://mudrex.go.link/55LQg", "COOKIE": "https://mudrex.go.link/2BlQC", "CPOOL": "https://mudrex.go.link/1MQWS", "MVL": "https://mudrex.go.link/it3bU", "PRIME": "https://mudrex.go.link/cFoRP", "SAROS": "https://mudrex.go.link/3J2D8", "SD": "https://mudrex.go.link/178xx", "SOLO": "https://mudrex.go.link/eBil4", "SQD": "https://mudrex.go.link/8c8gD", "TAI": "https://mudrex.go.link/dwNXL", "XDC": "https://mudrex.go.link/6eYhR", "XION": "https://mudrex.go.link/lrws4", "XTER": "https://mudrex.go.link/4GP3g", "ZENT": "https://mudrex.go.link/94dOO", "ZEREBRO": "https://mudrex.go.link/4Sh7C", "ZORA": "https://mudrex.go.link/8BJ8h", "ZRC": "https://mudrex.go.link/l4Heu", "VELVET": "https://mudrex.go.link/cZlZZ", "USELESS": "https://mudrex.go.link/dXgQf", "AIN": "https://mudrex.go.link/66wR4", "CROSS": "https://mudrex.go.link/1ndEh", "TANSSI": "https://mudrex.go.link/7uYJR", "M": "https://mudrex.go.link/aZhIP", "C": "https://mudrex.go.link/f377s", "TAC": "https://mudrex.go.link/jg3mL", "ES": "https://mudrex.go.link/b00VX", "ERA": "https://mudrex.go.link/ktfiK", "TA": "https://mudrex.go.link/4bxoG", "DIA": "https://mudrex.go.link/22gQZ", "ASP": "https://mudrex.go.link/8aBA2", "DOLO": "https://mudrex.go.link/iVGig", "FIS": "https://mudrex.go.link/5Sj4W", "1000TAG": "https://mudrex.go.link/gVIRT", "ESPORTS": "https://mudrex.go.link/J5usQ", "TREE": "https://mudrex.go.link/8J2Yu", "A2Z": "https://mudrex.go.link/fUaVq", "MYX": "https://mudrex.go.link/gm1fQ", "TOWNS": "https://mudrex.go.link/hbc7F", "PROVE": "https://mudrex.go.link/aWDI9", "RHEA": "https://mudrex.go.link/hmUjQ", "IN": "https://mudrex.go.link/dQsmN", "YALA": "https://mudrex.go.link/6GvTL", "K": "https://mudrex.go.link/1AUJC", "ASR": "https://mudrex.go.link/bBezC", "XNY": "https://mudrex.go.link/bhJsU", "AIO": "https://mudrex.go.link/KIdK3", "ALPINE": "https://mudrex.go.link/9TYzA", "NAORIS": "https://mudrex.go.link/gtWqJ", "SKY": "https://mudrex.go.link/6nyvt", "YZY": "https://mudrex.go.link/KMna6", "SAPIEN": "https://mudrex.go.link/7N7pS", "DAM": "https://mudrex.go.link/5dnGq", "BTR": "https://mudrex.go.link/bcLHJ", "BSU": "https://mudrex.go.link/5Bi3h", "WLFI": "https://mudrex.go.link/3KpRP", "PTB": "https://mudrex.go.link/aNKHf", "ARIA": "https://mudrex.go.link/8UX32", "SOMI": "https://mudrex.go.link/3TzGw", "MITO": "https://mudrex.go.link/aAOcy", "CAMP": "https://mudrex.go.link/2UCG3", "STBL": "https://mudrex.go.link/NkBen", "BARD": "https://mudrex.go.link/5ESuP", "ZKC": "https://mudrex.go.link/5BRW3", "Q": "https://mudrex.go.link/gR3hd", "XPIN": "https://mudrex.go.link/o327e", "UB": "https://mudrex.go.link/4qEjl", "HOLO": "https://mudrex.go.link/hlLuO", "OKB": "https://mudrex.go.link/eZDOV", "ASTER": "https://mudrex.go.link/3KxTX", "0G": "https://mudrex.go.link/ipa6i", "HEMI": "https://mudrex.go.link/h2AHp", "BLESS": "https://mudrex.go.link///futuresdetails/01998093-d2b4-7c0d-817a-40d839bf0319?adj_t=1ste07ys&adj_engagement_type=fallback_click", "FLUID": "https://mudrex.go.link/Ro8sC", "AVNT": "https://mudrex.go.link/7FbPn", "MIRA": "https://mudrex.go.link/6mGHI", "AKE": "https://mudrex.go.link/dWinv", "RLUSD": "https://mudrex.go.link/2GJ77", "LIGHT": "https://mudrex.go.link/aYuGW", "APEX": "https://mudrex.go.link/7vRdF", "XAN": "https://mudrex.go.link/8IrIR", "FF": "https://mudrex.go.link/aeVBZ", "EDEN": "https://mudrex.go.link/7mIJZ", "VFY": "https://mudrex.go.link/8wavS", "TRUTH": "https://mudrex.go.link/kJhJ5", "COAI": "https://mudrex.go.link/fLCdG", "2Z": "https://mudrex.go.link/iurDt", "KGEN": "https://mudrex.go.link/6YtCY", "4": "https://mudrex.go.link/bdnjR", "GIGGLE": "https://mudrex.go.link/89nLT", "MET": "https://mudrex.go.link/bNYiQ", "YB": "https://mudrex.go.link/6GrE9", "EUL": "https://mudrex.go.link/cxTKN", "ENSO": "https://mudrex.go.link/hyubN", "RECALL": "https://mudrex.go.link/c5umD", "CLO": "https://mudrex.go.link/hPB3N", "HANA": "https://mudrex.go.link/3Uxft", "EVAA": "https://mudrex.go.link/adpkb", "ZBT": "https://mudrex.go.link/1cYZl", "RIVER": "https://mudrex.go.link/lg4ol", "TURTLE": "https://mudrex.go.link/cAlDD", "APR": "https://mudrex.go.link/kgBuQ", "BLUAI": "https://mudrex.go.link/7hTd4", "LAB": "https://mudrex.go.link/1BiQK", "COMMON": "https://mudrex.go.link/k21NL", "PIGGY": "https://mudrex.go.link/8SPKs", "AT": "https://mudrex.go.link/khbpP", "MMT": "https://mudrex.go.link/9Ut2B", "KITE": "https://mudrex.go.link/e29e6", "CC": "https://mudrex.go.link/aBlVl", "TRUST": "https://mudrex.go.link/LvXJl", "ALLO": "https://mudrex.go.link/8NkGN", "PIEVERSE": "https://mudrex.go.link/5nYMT", "UAI": "https://mudrex.go.link/fhsRa", "JCT": "https://mudrex.go.link/89N17", "BEAT": "https://mudrex.go.link/eswyC", "BOBBOB": "https://mudrex.go.link/gWqeX", "IRYS": "https://mudrex.go.link/3V5Y6", "CYS": "https://mudrex.go.link/cys", "US": "https://mudrex.go.link/ususdt", "RAVE": "https://mudrex.go.link/RAVE", "ZKP": "https://mudrex.go.link/ZKPUSDT"}

DEFAULT_DB = {
    "creatives": {},
    "adjust_links": {},
    "signals": {},
    "last_signal": None,
    "signal_counter": 0,
    "channel_stats": {},
    "views": {},
    "settings": {
        "signal_format": None
    }
}

def load_db():
    """Load database from JSON file and merge with pre-loaded adjust links"""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DB_PATH.exists():
            with open(DB_PATH, 'r') as f:
                db = json.load(f)
                for key in DEFAULT_DB:
                    if key not in db:
                        db[key] = DEFAULT_DB[key]
                # Merge pre-loaded adjust links (don't overwrite user's custom links)
                for ticker, link in PRELOADED_ADJUST_LINKS.items():
                    if ticker not in db["adjust_links"]:
                        db["adjust_links"][ticker] = link
                return db
    except Exception as e:
        logger.error(f"Error loading database: {e}")
    # Fresh database - include all pre-loaded links
    fresh_db = DEFAULT_DB.copy()
    fresh_db["adjust_links"] = PRELOADED_ADJUST_LINKS.copy()
    return fresh_db

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
DEFAULT_FORMAT = """🚨 NEW CRYPTO TRADE ALERT {direction_emoji}🔥

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

⚠️ Disclaimer: Crypto assets are unregulated and extremely volatile. Losses are possible, and no regulatory recourse is available. Always DYOR before taking any trade."""


# ============== HELPER FUNCTIONS ==============

def get_ist_now():
    """Get current datetime in IST"""
    return datetime.now(IST)

def get_ist_timestamp() -> str:
    """Get current time in IST format"""
    return get_ist_now().strftime("%d %b %Y, %I:%M %p")

def get_ist_date() -> str:
    """Get current date in IST"""
    return get_ist_now().strftime("%d %b %Y")

def get_sheet_timestamp() -> str:
    """Get timestamp for Google Sheet (format: M/D/YYYY H:MM:SS)"""
    return get_ist_now().strftime("%-m/%-d/%Y %-H:%M:%S")

def get_year() -> str:
    """Get current year"""
    return get_ist_now().strftime("%Y")

def get_month_key() -> str:
    """Get current month key (YYYY-MM)"""
    return get_ist_now().strftime("%Y-%m")

def get_signal_number() -> str:
    """Get next signal number formatted as 001, 002, etc."""
    global db
    db["signal_counter"] = db.get("signal_counter", 0) + 1
    save_db(db)
    return f"{db['signal_counter']:03d}"

def get_decimal_places(value_str: str) -> int:
    """Get number of decimal places from input string"""
    if '.' in value_str:
        return len(value_str.split('.')[1])
    return 0

def format_price(price: float, decimals: int = None) -> str:
    """Format price with specified decimal places or smart default"""
    if decimals is not None:
        return f"{price:.{decimals}f}"
    
    # Smart default for calculated values
    if price >= 10000:
        return f"{price:.0f}"
    elif price >= 1000:
        return f"{price:.1f}".rstrip('0').rstrip('.')
    elif price >= 100:
        return f"{price:.2f}".rstrip('0').rstrip('.')
    elif price >= 10:
        return f"{price:.2f}".rstrip('0').rstrip('.')
    elif price >= 1:
        return f"{price:.3f}".rstrip('0').rstrip('.')
    elif price >= 0.1:
        return f"{price:.4f}".rstrip('0').rstrip('.')
    elif price >= 0.01:
        return f"{price:.5f}".rstrip('0').rstrip('.')
    elif price >= 0.001:
        return f"{price:.6f}".rstrip('0').rstrip('.')
    else:
        return f"{price:.8f}".rstrip('0').rstrip('.')

def calculate_signal(ticker: str, entry1: float, sl: float, leverage: int = None, entry1_str: str = None, sl_str: str = None) -> dict:
    """Calculate all signal parameters"""
    direction = "LONG" if sl < entry1 else "SHORT"
    direction_emoji = "📈" if direction == "LONG" else "📉"
    
    # Get decimal places from input
    if entry1_str:
        decimals = get_decimal_places(entry1_str)
    elif sl_str:
        decimals = get_decimal_places(sl_str)
    else:
        decimals = None
    
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
        "entry1": format_price(entry1, decimals),
        "entry2": format_price(entry2, decimals),
        "avg_entry": format_price(avg_entry, decimals),
        "tp1": format_price(tp1, decimals),
        "tp2": format_price(tp2, decimals),
        "sl": format_price(sl, decimals),
        "leverage": leverage,
        "holding_time": holding_time,
        "potential_profit": f"{potential_profit:.2f}%",
    }

def generate_signal_text(signal_data: dict) -> str:
    """Generate signal text from template"""
    template = db["settings"].get("signal_format") or DEFAULT_FORMAT
    return template.format(**signal_data)

def generate_figma_prompt(signal_data: dict) -> str:
    """Generate Figma agent instructions"""
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
    """Get trade URL for ticker - MUST be in database or provided"""
    global db
    
    if custom_url:
        # Save new link to database
        db["adjust_links"][ticker.upper()] = custom_url
        save_db(db)
        return custom_url
    elif ticker.upper() in db["adjust_links"]:
        return db["adjust_links"][ticker.upper()]
    else:
        # Should not reach here - signal_command checks first
        return None

def record_signal(signal_id: str, ticker: str, direction: str, message_id: int, sender: str, signal_data: dict = None):
    """Record signal in database with sender info and sync to Google Sheets"""
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
    
    # Sync to Google Sheets
    if signal_data:
        sheet_data = {
            'timestamp': get_sheet_timestamp(),
            'ticker': signal_data.get('ticker', ''),
            'direction': signal_data.get('direction', ''),
            'leverage': signal_data.get('leverage', ''),
            'entry1': signal_data.get('entry1', ''),
            'entry2': signal_data.get('entry2', ''),
            'tp1': signal_data.get('tp1', ''),
            'tp2': signal_data.get('tp2', ''),
            'sl': signal_data.get('sl', ''),
        }
        append_to_sheet(sheet_data)

def parse_year_range(text: str):
    """Parse year or year range from command like totalsignal2025 or totalsignal20252026"""
    digits = ""
    for char in reversed(text):
        if char.isdigit():
            digits = char + digits
        else:
            break
    
    if not digits:
        return None, None
    
    if len(digits) == 4:
        return digits, digits
    elif len(digits) == 8:
        return digits[:4], digits[4:]
    else:
        return None, None

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
        "recent_signals": [],
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
                
                # Recent signals (keep last 5)
                stats["recent_signals"].append(signal)
    
    # Sort recent signals by signal_id descending
    stats["recent_signals"] = sorted(stats["recent_signals"], key=lambda x: x.get("signal_id", ""), reverse=True)[:5]
    
    return stats

def is_admin(user_id: int) -> bool:
    """Check if user is admin - blocks non-admins when ADMIN_IDS is configured"""
    if not ADMIN_IDS:
        # No admins configured = allow all (for testing)
        return True
    return user_id in ADMIN_IDS


# ============== MIDNIGHT TASK ==============

async def update_channel_stats(context: ContextTypes.DEFAULT_TYPE):
    """Update channel member count - called at midnight"""
    global db
    
    try:
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
    
    if not update.message or not update.message.text:
        return
    
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
    """Help command with all commands"""
    if not update.message:
        return
    
    sheets_status = "✅ Connected" if sheets_service else "❌ Not configured"
    
    help_text = f"""🚀 <b>MUDREX SIGNAL BOT v3.0</b>

<b>━━━━ SIGNALS ━━━━</b>
<code>signal BTC 86800 90200 3x [link]</code>
<code>BTC 86800 90200 3x [link]</code>
<code>delete</code> - Delete last signal

<b>━━━━ LINKS ━━━━</b>
<code>links</code> - Show saved links
<code>addlink BTC link1 ETH link2</code>
<code>clearlink BTC</code> / <code>clearlink all</code>

<b>━━━━ CREATIVES ━━━━</b>
<code>fix1</code>, <code>fix2</code>... - Save creative
<code>use fix1</code> - Use in signal
<code>list</code> - Show saved creatives
<code>clearfix 1</code> / <code>clearfix all</code>

<b>━━━━ ANALYTICS ━━━━</b>
<code>totalsignal</code> / <code>totalsignal2025</code>
<code>totalsignal20252026</code> - Year range
<code>totalrohith</code> / <code>totalrajini</code> / <code>totalbalaji</code>
<code>views</code> / <code>views2025</code>
<code>channelstats</code>

<b>━━━━ OTHER ━━━━</b>
<code>format</code> - Change template
<code>help</code> - This guide
<code>start123</code> - Activate bot

📊 Google Sheets: {sheets_status}

💡 After preview: <code>/sendnow_as_rohith</code>"""
    
    await update.message.reply_text(help_text, parse_mode="HTML")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle signal command"""
    global pending_signals
    
    # Show error if photo sent instead of text
    if not update.message:
        return ConversationHandler.END
    
    if not update.message.text:
        await update.message.reply_text(
            "❌ Please send text command, not image!\n\n"
            "Use: <code>BTC 86800 90200 3x</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    if not BOT_ACTIVE:
        await update.message.reply_text("❌ Bot is not active. Use <code>start123</code> to activate.", parse_mode="HTML")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You're not authorized.")
        return ConversationHandler.END
    
    text = update.message.text.strip()
    if text.startswith('/'):
        text = text[1:]
    
    # Remove "signal" prefix if present
    if text.lower().startswith("signal "):
        text = text[7:]
    
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
        entry1_str = parts[1]
        sl_str = parts[2]
        entry1 = float(entry1_str)
        sl = float(sl_str)
        leverage = int(parts[3].lower().replace('x', ''))
        
        custom_url = None
        if len(parts) >= 5 and parts[4].startswith('http'):
            custom_url = parts[4]
        
        # ALWAYS require link from database or command - no default URL
        has_saved_link = ticker.upper() in db.get("adjust_links", {})
        
        if not custom_url and not has_saved_link:
            await update.message.reply_text(
                f"❌ No deeplink found for <b>{ticker}</b>!\n\n"
                f"Add link first:\n"
                f"<code>addlink {ticker} https://your-link</code>\n\n"
                f"Or include in signal:\n"
                f"<code>{ticker} {entry1_str} {sl_str} {leverage}x https://link</code>",
                parse_mode="HTML"
            )
            return ConversationHandler.END
        
        # Get trade URL (from command or database)
        trade_url = get_trade_url(ticker, custom_url)
        
        # Generate signal ID
        signal_id = get_signal_number()
        
        signal_data = calculate_signal(ticker, entry1, sl, leverage, entry1_str, sl_str)
        signal_data['signal_id'] = signal_id
        signal_data['trade_url'] = trade_url
        
        pending_signals[user_id] = {
            "signal_data": signal_data,
            "custom_url": custom_url,
            "signal_id": signal_id
        }
        
        link_status = "🔗 Link: ✅ (saved)" if custom_url else "🔗 Link: ✅"
        
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
            f"{link_status}\n\n"
            f"🖼️ Drop creative or type <code>use fix1</code>"
            f"{creative_list}",
            parse_mode="HTML"
        )
        
        return WAITING_FOR_CREATIVE
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Error: Invalid number format")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Signal command error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def receive_creative(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive creative and show preview"""
    global pending_signals
    
    if not update.message:
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    
    if user_id not in pending_signals:
        await update.message.reply_text("❌ No pending signal. Use <code>signal</code> first.", parse_mode="HTML")
        return ConversationHandler.END
    
    if update.message.text:
        text = update.message.text.lower().strip()
        if text.startswith("use fix"):
            fix_key = text.replace("use ", "")
            if fix_key in db.get("creatives", {}):
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
    """Confirm and send signal to channel with sender tracking"""
    global pending_signals, db
    
    if not update.message or not update.message.text:
        return WAITING_FOR_CONFIRM
    
    user_id = update.effective_user.id
    text = update.message.text.lower().strip()
    
    if text == "cancel" or text == "/cancel":
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
        
        # Record signal with Google Sheets sync
        record_signal(signal_id, signal_data['ticker'], signal_data['direction'], sent_message.message_id, sender, signal_data)
        
        sheets_msg = "📊 Synced to Google Sheets ✅" if sheets_service else ""
        
        await update.message.reply_text(
            f"✅ <b>Signal #{signal_id} posted!</b>\n\n"
            f"Ticker: {signal_data['ticker']} {signal_data['direction']}\n"
            f"Sender: {sender.capitalize()}\n"
            f"{sheets_msg}",
            parse_mode="HTML"
        )
        
        figma_prompt = generate_figma_prompt(signal_data)
        await update.message.reply_text(figma_prompt, parse_mode="Markdown")
        
        summary = generate_summary_box(signal_data)
        await update.message.reply_text(summary, parse_mode="Markdown")
        
        pending_signals.pop(user_id, None)
        
        logger.info(f"Signal #{signal_id} posted by {sender}: {signal_data['ticker']} {signal_data['direction']}")
        
    except Exception as e:
        logger.error(f"Error posting signal: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
    
    return ConversationHandler.END

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete last signal from channel"""
    global db
    
    if not update.message:
        return
    
    if not BOT_ACTIVE:
        return
    
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
        
        await update.message.reply_text(f"✅ Deleted Signal #{signal_id} ({ticker})\n\n⚠️ Note: Google Sheet row not deleted (manual)")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle fixN command - save creative"""
    global db
    
    if not update.message or not update.message.text:
        return ConversationHandler.END
    
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
    """Receive and save fix creative"""
    global db
    
    if not update.message:
        return ConversationHandler.END
    
    if not update.message.photo:
        await update.message.reply_text("❌ Send an image.")
        return WAITING_FOR_FIX_CREATIVE
    
    fix_key = context.user_data.get("pending_fix_key", "fix1")
    if "creatives" not in db:
        db["creatives"] = {}
    db["creatives"][fix_key] = update.message.photo[-1].file_id
    save_db(db)
    
    await update.message.reply_text(f"✅ Saved as <code>{fix_key}</code>", parse_mode="HTML")
    return ConversationHandler.END

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all saved creatives"""
    if not update.message:
        return
    if not BOT_ACTIVE:
        return
    if not is_admin(update.effective_user.id):
        return
    
    if not db.get("creatives"):
        await update.message.reply_text("📭 No saved creatives.", parse_mode="HTML")
        return
    
    creative_list = "\n".join([f"  • {k}" for k in sorted(db["creatives"].keys())])
    await update.message.reply_text(
        f"🖼️ <b>Saved Creatives</b>\n\n{creative_list}\n\n"
        f"Total: {len(db['creatives'])}",
        parse_mode="HTML"
    )

async def clearfix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear saved creative(s)"""
    global db
    
    if not update.message or not update.message.text:
        return
    
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

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all saved links"""
    if not update.message:
        return
    if not BOT_ACTIVE:
        return
    if not is_admin(update.effective_user.id):
        return
    
    if not db.get("adjust_links"):
        await update.message.reply_text("📭 No saved links.", parse_mode="HTML")
        return
    
    links_list = "\n".join([f"  • <b>{k}</b> → {v}" for k, v in sorted(db["adjust_links"].items())])
    await update.message.reply_text(
        f"🔗 <b>Saved Links</b>\n\n{links_list}\n\n"
        f"Total: {len(db['adjust_links'])}",
        parse_mode="HTML"
    )

async def addlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add multiple links: addlink BTC link1 ETH link2"""
    global db
    
    if not update.message or not update.message.text:
        return
    
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
    
    if "adjust_links" not in db:
        db["adjust_links"] = {}
    
    added = []
    for i in range(0, len(parts), 2):
        ticker = parts[i].upper()
        link = parts[i + 1]
        if link.startswith('http'):
            db["adjust_links"][ticker] = link
            added.append(ticker)
    
    save_db(db)
    
    if added:
        await update.message.reply_text(f"✅ Added links for: {', '.join(added)}")
    else:
        await update.message.reply_text("❌ No valid links added.")

async def clearlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear saved link(s)"""
    global db
    
    if not update.message or not update.message.text:
        return
    
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    text = update.message.text.lower().strip()
    if text.startswith('/'):
        text = text[1:]
    
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

async def totalsignal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show total signal statistics"""
    if not update.message or not update.message.text:
        return
    if not BOT_ACTIVE:
        return
    if not is_admin(update.effective_user.id):
        return
    
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
    if not update.message or not update.message.text:
        return
    if not BOT_ACTIVE:
        return
    if not is_admin(update.effective_user.id):
        return
    
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
    
    # Recent signals
    recent_lines = []
    for sig in stats["recent_signals"][:5]:
        recent_lines.append(f"  #{sig['signal_id']} {sig['ticker']} {sig['direction']}  {sig['date']}")
    recent_text = "\n".join(recent_lines) if recent_lines else "  No data"
    
    # Title
    if start_year == end_year:
        title = f"{member.capitalize()}'s Signals {start_year}"
    else:
        title = f"{member.capitalize()}'s Signals {start_year}-{end_year}"
    
    await update.message.reply_text(
        f"📊 <b>{title}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {stats['total']}\n\n"
        f"<b>By Month</b>\n{month_text}\n\n"
        f"<b>Recent Signals</b>\n{recent_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )

async def views_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show views statistics"""
    if not update.message or not update.message.text:
        return
    if not BOT_ACTIVE:
        return
    if not is_admin(update.effective_user.id):
        return
    
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
    
    last_updated = db.get("channel_stats", {}).get("last_updated", "Never")
    
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
    if not update.message:
        return
    if not BOT_ACTIVE:
        return
    if not is_admin(update.effective_user.id):
        return
    
    stats = db.get("channel_stats", {})
    
    current = stats.get("current", 0)
    last_updated = stats.get("last_updated", "Never")
    daily = stats.get("daily", {})
    monthly = stats.get("monthly", {})
    
    # If no current, try to fetch now
    if not current:
        try:
            current = await context.bot.get_chat_member_count(CHANNEL_ID)
            db["channel_stats"]["current"] = current
            db["channel_stats"]["last_updated"] = get_ist_timestamp()
            save_db(db)
            last_updated = db["channel_stats"]["last_updated"]
        except:
            pass
    
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
    
    trend_text = "\n".join(trend_lines) if trend_lines else "  No data yet"
    
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

async def botstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status and uptime - secret command /bot3132"""
    if not update.message:
        return
    if not is_admin(update.effective_user.id):
        return
    
    # Calculate uptime
    if BOT_START_TIME:
        uptime_delta = get_ist_now() - BOT_START_TIME
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if days > 0:
            uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        elif hours > 0:
            uptime_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            uptime_str = f"{minutes}m {seconds}s"
        else:
            uptime_str = f"{seconds}s"
    else:
        uptime_str = "Unknown"
    
    # Bot status
    status = "✅ Active" if BOT_ACTIVE else "❌ Inactive"
    
    # Google Sheets status
    sheets_status = "✅ Connected" if sheets_service else "❌ Not configured"
    
    # Count total signals
    total_signals = 0
    signals_data = db.get("signals", {})
    for year in signals_data.values():
        for month in year.values():
            total_signals += len(month)
    
    # Last signal info
    last_signal = db.get("last_signal")
    if last_signal:
        last_signal_str = f"#{last_signal.get('signal_id', 'N/A')} {last_signal.get('ticker', '')} {last_signal.get('direction', '')}"
    else:
        last_signal_str = "None"
    
    # Database counts
    creatives_count = len(db.get("creatives", {}))
    links_count = len(db.get("adjust_links", {}))
    
    # Admin count
    admin_count = len(ADMIN_IDS) if ADMIN_IDS else "All (no restriction)"
    
    # Server time
    server_time = get_ist_timestamp()
    
    await update.message.reply_text(
        f"🤖 <b>Bot Status</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: {status}\n"
        f"Uptime: {uptime_str}\n\n"
        f"<b>📊 Database</b>\n"
        f"  Total Signals: {total_signals}\n"
        f"  Last Signal: {last_signal_str}\n"
        f"  Creatives: {creatives_count}\n"
        f"  Links: {links_count}\n\n"
        f"<b>📋 Google Sheets:</b> {sheets_status}\n"
        f"<b>👥 Admins:</b> {admin_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Server Time: {server_time}",
        parse_mode="HTML"
    )

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change signal format template"""
    if not update.message:
        return ConversationHandler.END
    
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
    """Receive and save new format"""
    global db
    
    if not update.message or not update.message.text:
        return ConversationHandler.END
    
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
    
    if not update.message:
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    pending_signals.pop(user_id, None)
    
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages without / prefix"""
    if not update.message:
        return
    
    # Show error if non-text message
    if not update.message.text:
        if update.message.photo and BOT_ACTIVE:
            await update.message.reply_text(
                "❌ Send text command first, then image!\n\n"
                "Start with: <code>BTC 86800 90200 3x</code>",
                parse_mode="HTML"
            )
        return
    
    if not BOT_ACTIVE:
        return
    
    text = update.message.text.lower().strip()
    
    # Signal shortcut (BTC 86800 90200 3x)
    parts = text.split()
    if len(parts) >= 4:
        try:
            ticker = parts[0].upper()
            if ticker.isalpha() and len(ticker) <= 10:
                float(parts[1])  # entry
                float(parts[2])  # sl
                parts[3].lower().replace('x', '')  # leverage
                return await signal_command(update, context)
        except:
            pass
    
    # Commands
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
    elif text.startswith("addlink"):
        return await addlink_command(update, context)
    elif text.startswith("clearlink"):
        return await clearlink_command(update, context)
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
    elif text in ["help", "start"]:
        return await help_command(update, context)
    elif text == "start123":
        return await start_command(update, context)
    elif text == "cancel":
        return await cancel_command(update, context)


# ============== MAIN ==============

def main():
    """Start the bot"""
    global BOT_ACTIVE, BOT_START_TIME
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    # Initialize Google Sheets
    init_google_sheets()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Signal conversation handler
    signal_conv = ConversationHandler(
        entry_points=[
            CommandHandler("signal", signal_command),
            MessageHandler(filters.Regex(r'(?i)^signal\s') & filters.TEXT, signal_command),
            MessageHandler(filters.Regex(r'^[A-Za-z]{2,10}\s+\d') & filters.TEXT, signal_command),  # BTC 86800...
        ],
        states={
            WAITING_FOR_CREATIVE: [
                MessageHandler(filters.PHOTO, receive_creative),
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
    )
    
    # Fix conversation handler
    fix_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r'(?i)^/?fix\d+$') & filters.TEXT, fix_command),
        ],
        states={
            WAITING_FOR_FIX_CREATIVE: [MessageHandler(filters.PHOTO, receive_fix_creative)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'(?i)^cancel$'), cancel_command),
        ],
    )
    
    # Format conversation handler
    format_conv = ConversationHandler(
        entry_points=[
            CommandHandler("format", format_command),
            MessageHandler(filters.Regex(r'(?i)^format$') & filters.TEXT, format_command),
        ],
        states={
            WAITING_FOR_FORMAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_format)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            MessageHandler(filters.Regex(r'(?i)^cancel$'), cancel_command),
        ],
    )
    
    # Add handlers
    application.add_handler(signal_conv)
    application.add_handler(fix_conv)
    application.add_handler(format_conv)
    
    # Command handlers
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("clearfix", clearfix_command))
    application.add_handler(CommandHandler("links", links_command))
    application.add_handler(CommandHandler("addlink", addlink_command))
    application.add_handler(CommandHandler("clearlink", clearlink_command))
    application.add_handler(CommandHandler("totalsignal", totalsignal_command))
    application.add_handler(CommandHandler("views", views_command))
    application.add_handler(CommandHandler("channelstats", channelstats_command))
    application.add_handler(CommandHandler("bot3132", botstatus_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # Team member commands
    for member in TEAM_MEMBERS:
        application.add_handler(CommandHandler(f"total{member}", total_member_command))
    
    # Text handler for commands without /
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Schedule midnight task
    schedule_midnight_task(application)
    
    # Auto-activate bot and set start time
    BOT_ACTIVE = True
    BOT_START_TIME = get_ist_now()
    
    logger.info("🚀 Mudrex Signal Bot v3.0 started!")
    logger.info(f"Admins: {ADMIN_IDS}")
    logger.info(f"Google Sheets: {'Connected' if sheets_service else 'Not configured'}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
