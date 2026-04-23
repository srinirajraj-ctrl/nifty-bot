import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import pytz
import os
import json
import threading
import gc
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import warnings
warnings.filterwarnings('ignore')

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSHEET_AVAILABLE = True
except:
    GSHEET_AVAILABLE = False
    print("⚠️ gspread not available - installing...")
    os.system("pip install gspread google-auth-oauthlib --break-system-packages")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GOOGLE_SHEET_ID    = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON  = os.environ.get("GOOGLE_CREDS_JSON", "")

STOCKS = [
    {"symbol": "^NSEI",         "name": "NIFTY 50",       "tv": "NSE:NIFTY"},
    {"symbol": "^NSEBANK",      "name": "BANK NIFTY",     "tv": "NSE:BANKNIFTY"},
    {"symbol": "SBIN.NS",       "name": "SBIN",           "tv": "NSE:SBIN"},
    {"symbol": "YESBANK.NS",    "name": "YES BANK",       "tv": "NSE:YESBANK"},
    {"symbol": "PNB.NS",        "name": "PNB",            "tv": "NSE:PNB"},
    {"symbol": "BANKBARODA.NS", "name": "BANK OF BARODA", "tv": "NSE:BANKBARODA"},
    {"symbol": "HFCL.NS",       "name": "HFCL",           "tv": "NSE:HFCL"},
    {"symbol": "ITI.NS",        "name": "ITI",            "tv": "NSE:ITI"},
    {"symbol": "NMDC.NS",       "name": "NMDC",           "tv": "NSE:NMDC"},
    {"symbol": "HINDCOPPER.NS", "name": "HIND COPPER",    "tv": "NSE:HINDCOPPER"},
    {"symbol": "CENTRALBK.NS",  "name": "CENTRAL BANK",   "tv": "NSE:CENTRALBK"},
    {"symbol": "BEML.NS",       "name": "BEML",           "tv": "NSE:BEML"},
]

INTERVAL = "5m"
ATR_THRESHOLD_MULTIPLIER = 0.20
TRADE_START = "09:15"
TRADE_END = "15:15"

bot_status = {"last_check": "Not started", "last_signal": "None", "total_signals": 0, "wins": 0, "losses": 0, "active_trades": 0}
active_trades = {}
active_trades_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════════
# 📊 GOOGLE SHEETS INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

gsheet_ws = None

def init_gsheet():
    global gsheet_ws
    if not GOOGLE_CREDS_JSON or not GOOGLE_SHEET_ID:
        print("⚠️ Google Sheets not configured")
        return False
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        gsheet_ws = sheet.sheet1
        print("✅ Google Sheets connected!")
        return True
    except Exception as e:
        print(f"❌ Google Sheets error: {e}")
        return False

def log_to_gsheet(stock_name, signal_type, entry, atr_threshold, opening_range, is_manipulated, pattern, sl, tp):
    global gsheet_ws
    if not gsheet_ws:
        return None
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        row_data = [
            now.strftime("%d-%b-%Y"),
            now.strftime("%I:%M %p"),
            stock_name,
            signal_type,
            round(entry, 2),
            round(atr_threshold, 2),
            round(opening_range, 2),
            "YES" if is_manipulated else "NO",
            pattern,
            round(sl, 2),
            round(tp, 2),
            "",
            "",
            "MONITORING",
            ""
        ]
        gsheet_ws.append_row(row_data)
        all_rows = gsheet_ws.get_all_values()
        row_num = len(all_rows)
        print(f"✅ Logged {stock_name} to row {row_num}")
        return row_num
    except Exception as e:
        print(f"❌ Log error: {e}")
        return None

def update_gsheet_close(row_num, exit_price, pnl, result):
    global gsheet_ws
    if not gsheet_ws or not row_num:
        return
    try:
        gsheet_ws.update_cell(row_num, 12, round(exit_price, 2))
        gsheet_ws.update_cell(row_num, 13, round(pnl, 2))
        gsheet_ws.update_cell(row_num, 14, result)
        print(f"✅ Updated row {row_num}: {result}")
    except Exception as e:
        print(f"❌ Update error: {e}")

class DataCache:
    def __init__(self, max_age_minutes=2):
        self.cache = {}
        self.timestamps = {}
        self.max_age = timedelta(minutes=max_age_minutes)
    def get(self, key):
        if key not in self.cache or datetime.now() - self.timestamps[key] > self.max_age:
            self.cache.pop(key, None)
            self.timestamps.pop(key, None)
            return None
        return self.cache[key]
    def set(self, key, value):
        if len(self.cache) > 30:
            oldest_key = min(self.timestamps, key=self.timestamps.get)
            del self.cache[oldest_key]
            del self.timestamps[oldest_key]
        self.cache[key] = value
        self.timestamps[key] = datetime.now()

data_cache = DataCache(max_age_minutes=3)
alert_history = {}

class BotHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        stock_list = "".join([f"<li>{s['name']}</li>" for s in STOCKS])
        total = bot_status['wins'] + bot_status['losses']
        win_rate = round(bot_status['wins'] / total * 100, 1) if total > 0 else 0
        with active_trades_lock:
            active_list = "".join([f"<li>{t['name']} {t['signal']}</li>" for t in active_trades.values()]) or "<li>None</li>"
        html = f"""<html><head><title>Rumers 3-Step Bot</title><meta http-equiv="refresh" content="30"><style>body{{font-family:Arial;padding:20px;background:#1a1a2e;color:#eee}}h1{{color:#00d4aa}}.card{{background:#16213e;padding:15px;border-radius:10px;margin:10px 0}}.green{{color:#00ff88}}.red{{color:#ff4444}}</style></head><body><h1>Rumers 3-Step Strategy</h1><div class="card"><p>Step 1: Check manipulation (ATR x 0.20)</p><p>Step 2: Detect reversal patterns</p><p>Stocks: {len(STOCKS)}</p></div><div class="card"><p>Last Check: {bot_status['last_check']}</p><p class="green">Wins: {bot_status['wins']}</p><p class="red">Losses: {bot_status['losses']}</p><p>Win Rate: {win_rate}%</p></div><div class="card"><p>Active: {len(active_trades)}</p><ul>{active_list}</ul></div></body></html>"""
        self.wfile.write(html.encode())
    def log_message(self, format, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), BotHandler)
    print(f"✅ Web server on port {port}")
    server.serve_forever()

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except: pass

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%d-%b-%Y %I:%M %p IST")

def get_daily_atr(symbol):
    try:
        df = yf.download(symbol, period="20d", interval="1d", progress=False)
        if df.empty: return None
        high_low = df['High'] - df['Low']
        high_close = abs(df['High'] - df['Close'].shift())
        low_close = abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        time.sleep(2)
        return float(atr)
    except: return None

def check_manipulation(symbol, df_5m, daily_atr):
    if daily_atr is None: return None, None, None
    atr_threshold = daily_atr * ATR_THRESHOLD_MULTIPLIER
    try:
        first_3 = df_5m.head(3)
        if len(first_3) < 3: return None, None, None
        opening_high = float(first_3['High'].max())
        opening_low = float(first_3['Low'].min())
        opening_range = opening_high - opening_low
        is_manipulated = opening_range < atr_threshold
        return is_manipulated, opening_range, atr_threshold
    except: return None, None, None

def detect_reversal_pattern(df_5m):
    if len(df_5m) < 3: return None
    try:
        c1, c2 = df_5m.iloc[0], df_5m.iloc[1]
        if (c1['Close'] < c1['Open'] and c2['Close'] > c2['Open'] and c2['High'] > c1['High'] and c2['Low'] < c1['Low']): return "BULLISH_ENGULFING"
        if (c1['Close'] > c1['Open'] and c2['Close'] < c2['Open'] and c2['High'] > c1['High'] and c2['Low'] < c1['Low']): return "BEARISH_ENGULFING"
        if (c1['Close'] < c1['Open'] and c2['Close'] > c2['Open'] and c2['High'] < c1['High'] and c2['Low'] > c1['Low']): return "BULLISH_HARAMI"
        if (c1['Close'] > c1['Open'] and c2['Close'] < c2['Open'] and c2['High'] < c1['High'] and c2['Low'] > c1['Low']): return "BEARISH_HARAMI"
        return "NO_PATTERN"
    except: return None

def generate_signal(df_5m, is_manipulated, pattern):
    if is_manipulated or pattern is None or pattern == "NO_PATTERN": return None
    current = float(df_5m.iloc[-1]['Close'])
    if "BULLISH" in pattern: return {'type': 'BUY', 'entry': current, 'pattern': pattern}
    if "BEARISH" in pattern: return {'type': 'SELL', 'entry': current, 'pattern': pattern}
    return None

def alert_signal(stock, pattern, signal, atr_threshold, opening_range, is_manipulated):
    bot_status['last_signal'] = f"{signal['type']} {stock['name']}"
    bot_status['total_signals'] += 1
    emoji = "🟢" if signal['type'] == "BUY" else "🔴"
    entry = signal['entry']
    sl = entry * 0.98 if signal['type'] == "BUY" else entry * 1.02
    tp = entry * 1.03 if signal['type'] == "BUY" else entry * 0.97
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0
    chart_url = f"https://www.tradingview.com/chart/?symbol={stock['tv']}&interval=5"
    send_telegram(f"{emoji} <b>{signal['type']} {stock['name']}</b>\n\n📍 Entry: {entry:.2f}\n🛡 SL: {sl:.2f} ({risk:.2f} pts)\n🎯 TP: {tp:.2f} ({reward:.2f} pts)\n📊 R:R: 1:{rr:.1f}\nPattern: {pattern}\n\n📊 <a href='{chart_url}'>Open TradingView Chart</a>\n\n{get_ist_time()}")
    
    # LOG TO GOOGLE SHEETS
    row_num = log_to_gsheet(stock['name'], signal['type'], entry, atr_threshold, opening_range, is_manipulated, pattern, sl, tp)
    
    with active_trades_lock:
        active_trades[stock['symbol']] = {"name": stock['name'], "signal": signal['type'], "entry": entry, "sl": sl, "tp": tp, "row": row_num, "symbol": stock['symbol']}
        bot_status['active_trades'] = len(active_trades)

def is_trading_time():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    if now.weekday() >= 5: return False
    sh, sm = map(int, TRADE_START.split(":"))
    eh, em = map(int, TRADE_END.split(":"))
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end

def fetch_data(symbol):
    cache_key = f"{symbol}_daily"
    cached = data_cache.get(cache_key)
    if cached is not None: return cached
    for attempt in range(3):
        try:
            df = yf.download(symbol, interval="1d", period="30d", progress=False)
            if df.empty: return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df[['Open','High','Low','Close','Volume']].dropna()
            if len(df) > 20: df = df.iloc[-20:]
            data_cache.set(cache_key, df)
            time.sleep(3)
            return df
        except Exception as e:
            print(f"⚠️ {symbol}: {e}")
            if attempt < 2: time.sleep(20)
    return None

def fetch_intraday(symbol):
    cache_key = f"{symbol}_5m"
    cached = data_cache.get(cache_key)
    if cached is not None: return cached
    for attempt in range(3):
        try:
            df = yf.download(symbol, interval="5m", period="3d", progress=False)
            if df.empty: return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df[['Open','High','Low','Close','Volume']].dropna()
            if len(df) > 100: df = df.iloc[-100:]
            data_cache.set(cache_key, df)
            time.sleep(3)
            return df
        except Exception as e:
            print(f"⚠️ {symbol}: {e}")
            if attempt < 2: time.sleep(20)
    return None

def get_current_price(symbol):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if data.empty: return None
            return float(data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ Price {symbol}: {e}")
            time.sleep(5)
    return None

def monitor_trades():
    while True:
        try:
            with active_trades_lock:
                symbols = list(active_trades.keys())
            
            for symbol in symbols:
                with active_trades_lock:
                    if symbol not in active_trades:
                        continue
                    trade = active_trades[symbol].copy()
                
                price = get_current_price(symbol)
                if price is None:
                    continue
                
                name = trade['name']
                signal_type = trade['signal']
                entry = trade['entry']
                sl = trade['sl']
                tp = trade['tp']
                row_num = trade['row']
                
                result = None
                pnl = 0
                exit_price = price
                
                # BUY Signal
                if signal_type == "BUY":
                    if price >= tp:
                        # TP Hit
                        result = "✅ WIN TP"
                        exit_price = tp
                        pnl = tp - entry
                        bot_status['wins'] += 1
                        print(f"  ✅ {name} BUY: Price {price:.2f} >= TP {tp:.2f}")
                    elif price <= sl:
                        # SL Hit
                        result = "❌ LOSS SL"
                        exit_price = sl
                        pnl = sl - entry
                        bot_status['losses'] += 1
                        print(f"  ❌ {name} BUY: Price {price:.2f} <= SL {sl:.2f}")
                
                # SELL Signal
                elif signal_type == "SELL":
                    if price <= tp:
                        # TP Hit
                        result = "✅ WIN TP"
                        exit_price = tp
                        pnl = entry - tp
                        bot_status['wins'] += 1
                        print(f"  ✅ {name} SELL: Price {price:.2f} <= TP {tp:.2f}")
                    elif price >= sl:
                        # SL Hit
                        result = "❌ LOSS SL"
                        exit_price = sl
                        pnl = entry - sl
                        bot_status['losses'] += 1
                        print(f"  ❌ {name} SELL: Price {price:.2f} >= SL {sl:.2f}")
                
                # Trade closed
                if result:
                    print(f"✅ Trade closed: {name} | {signal_type} | Exit: {exit_price:.2f} | P&L: {pnl:+.2f} | {result}")
                    
                    # Send Telegram alert
                    send_telegram(f"📊 <b>Trade CLOSED</b>\n━━━━━━━━━━━━\n{result}\n\n<b>{name}</b>\n{signal_type} | Entry: {entry:.2f} | Exit: {exit_price:.2f}\nP&L: {pnl:+.2f} pts\n\n{get_ist_time()}")
                    
                    # Update Google Sheets
                    update_gsheet_close(row_num, exit_price, pnl, result)
                    
                    # Remove from active trades
                    with active_trades_lock:
                        active_trades.pop(symbol, None)
                        bot_status['active_trades'] = len(active_trades)
                
                time.sleep(5)
        
        except Exception as e:
            print(f"❌ Monitor error: {e}")
        
        time.sleep(30)

def scan_stock(stock):
    symbol, name = stock['symbol'], stock['name']
    try:
        with active_trades_lock:
            if symbol in active_trades: return
        daily_atr = get_daily_atr(symbol)
        if daily_atr is None: return
        df_5m = fetch_intraday(symbol)
        if df_5m is None: return
        is_manipulated, opening_range, atr_threshold = check_manipulation(symbol, df_5m, daily_atr)
        if is_manipulated is None: return
        print(f"  {name}: Manip={is_manipulated}, Range={opening_range:.2f}, Threshold={atr_threshold:.2f}")
        if is_manipulated: return
        pattern = detect_reversal_pattern(df_5m)
        if pattern is None or pattern == "NO_PATTERN": return
        print(f"  ✅ {name}: Pattern={pattern}")
        signal = generate_signal(df_5m, is_manipulated, pattern)
        if signal is None: return
        alert_key = f"{symbol}_{datetime.now().strftime('%H:%M')}"
        if alert_key in alert_history: return
        print(f"  ✅ SIGNAL: {signal['type']} {name}")
        alert_signal(stock, pattern, signal, atr_threshold, opening_range, is_manipulated)
        alert_history[alert_key] = True
        if len(alert_history) > 100:
            oldest_key = next(iter(alert_history))
            del alert_history[oldest_key]
    except Exception as e:
        print(f"❌ {name}: {e}")

def run_strategy():
    print(f"\n{'='*40}\n🔄 {get_ist_time()}")
    bot_status['last_check'] = get_ist_time()
    if not is_trading_time():
        print("⏸ Outside trading hours")
        return
    print(f"Scanning {len(STOCKS)} with 3-Step...")
    for stock in STOCKS:
        scan_stock(stock)
        time.sleep(10)
    gc.collect()

def bot_loop():
    print("🚀 Rumers 3-Step Bot starting...")
    send_telegram("🎯 Rumers 3-Step Bot Started!\n\n1️⃣ Check: Manipulation (ATR×0.20)\n2️⃣ Detect: Reversal patterns\n3️⃣ Signal: Generate trade\n\n" + get_ist_time())
    while True:
        try:
            run_strategy()
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(120)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Missing credentials!")
    else:
        init_gsheet()
        monitor_thread = threading.Thread(target=monitor_trades)
        monitor_thread.daemon = True
        monitor_thread.start()
        bot_thread = threading.Thread(target=bot_loop)
        bot_thread.daemon = True
        bot_thread.start()
        run_web_server()
