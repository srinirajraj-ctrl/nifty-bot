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

# ──────────────────────────────────────────────
#  ⚙️ CREDENTIALS
# ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GOOGLE_SHEET_ID    = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON  = os.environ.get("GOOGLE_CREDS_JSON", "")

# ──────────────────────────────────────────────
#  📋 STOCKS TO SCAN
# ──────────────────────────────────────────────
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

INTERVAL        = "5m"
TV_INTERVAL     = "5"

# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 THE RUMERS BOX STRATEGY PARAMETERS
# ═══════════════════════════════════════════════════════════════════════════════

BOX_ZONE_PERCENT = 0.20          # 20% zones (top and bottom)
MIDPOINT_PERCENT = 0.50          # 50% midpoint
OPENING_HOUR = 8                 # 8:45 AM IST for NSE
OPENING_MINUTE = 45
TRADE_START = "09:15"            # Start scanning at 9:15 AM
TRADE_END = "15:15"              # Stop at 3:15 PM
SL_TYPE = "yesterday_levels"     # Use yesterday high/low as SL

bot_status = {
    "last_check"    : "Not started",
    "last_signal"   : "None",
    "total_signals" : 0,
    "wins"          : 0,
    "losses"        : 0,
    "active_trades" : 0,
}

active_trades      = {}
active_trades_lock = threading.Lock()

# ──────────────────────────────────────────────
#  💾 DATA CACHE
# ──────────────────────────────────────────────
class DataCache:
    def __init__(self, max_age_minutes=2, max_size_mb=30):
        self.cache = {}
        self.timestamps = {}
        self.max_age = timedelta(minutes=max_age_minutes)
        self.max_size = max_size_mb * 1024 * 1024
        
    def get(self, key):
        if key not in self.cache:
            return None
        if datetime.now() - self.timestamps[key] > self.max_age:
            del self.cache[key]
            del self.timestamps[key]
            return None
        return self.cache[key]
    
    def set(self, key, value):
        self._cleanup_if_needed()
        self.cache[key] = value
        self.timestamps[key] = datetime.now()
    
    def _cleanup_if_needed(self):
        if len(self.cache) > 30:
            oldest_key = min(self.timestamps, key=self.timestamps.get)
            del self.cache[oldest_key]
            del self.timestamps[oldest_key]
    
    def clear(self):
        self.cache.clear()
        self.timestamps.clear()

data_cache = DataCache(max_age_minutes=3)
alert_history = {}

# ──────────────────────────────────────────────
#  🌐 WEB SERVER
# ──────────────────────────────────────────────
class BotHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        stock_list = "".join([f"<li>{s['name']}</li>" for s in STOCKS])
        total    = bot_status['wins'] + bot_status['losses']
        win_rate = round(bot_status['wins'] / total * 100, 1) if total > 0 else 0
        with active_trades_lock:
            active_list = "".join([
                f"<li>{t['name']} {t['signal']} @ {t['entry']:.2f}</li>"
                for t in active_trades.values()
            ]) or "<li>None</li>"
        html = f"""
        <html>
        <head>
            <title>🎯 The Rumers Box Strategy Bot</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body{{font-family:Arial;padding:20px;background:#1a1a2e;color:#eee}}
                h1{{color:#00d4aa}}
                .card{{background:#16213e;padding:15px;border-radius:10px;margin:10px 0}}
                .green{{color:#00ff88}}
                .red{{color:#ff4444}}
                .yellow{{color:#ffcc00}}
                ul{{columns:2}}
            </style>
        </head>
        <body>
            <h1>🎯 The Rumers Box Strategy</h1>
            <div class="card">
                <p>📊 <b>Strategy:</b> Price Action Box Trading</p>
                <p>🕐 <b>Hours:</b> {TRADE_START} - {TRADE_END} IST</p>
                <p>📏 <b>Zones:</b> 20% top/bottom, 50% midpoint</p>
                <p>💰 <b>Risk/Reward:</b> 1:2 minimum</p>
                <p>📈 <b>Stocks:</b> {len(STOCKS)}</p>
            </div>
            <div class="card">
                <p>⏱️ <b>Last Check:</b> {bot_status['last_check']}</p>
                <p>🎯 <b>Last Signal:</b> <span class="green">{bot_status['last_signal']}</span></p>
                <p>📊 <b>Total Signals:</b> {bot_status['total_signals']}</p>
                <p class="green">✅ <b>Wins:</b> {bot_status['wins']}</p>
                <p class="red">❌ <b>Losses:</b> {bot_status['losses']}</p>
                <p>🏆 <b>Win Rate:</b> {win_rate}%</p>
            </div>
            <div class="card">
                <p class="yellow">💰 <b>Active Trades:</b></p>
                <ul>{active_list}</ul>
            </div>
            <div class="card">
                <b>Scanning:</b><ul>{stock_list}</ul>
            </div>
            <p class="green">🟢 Bot Running 24/7</p>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), BotHandler)
    print(f"✅ Web server on port {port}")
    server.serve_forever()

# ──────────────────────────────────────────────
#  📊 GOOGLE SHEETS
# ──────────────────────────────────────────────
gsheet_client = None

def init_gsheet():
    global gsheet_client
    if not GOOGLE_CREDS_JSON or not GOOGLE_SHEET_ID:
        print("⚠️ Google Sheets not configured")
        return False
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scopes     = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds         = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gsheet_client = gspread.authorize(creds)
        sh = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1
        if ws.cell(1,1).value != "Date":
            ws.update('A1:O1', [[
                "Date","Time","Stock","Signal","Entry",
                "Yesterday High","Yesterday Low","Top 20%","Bottom 20%","Midpoint",
                "SL","Target","Trend","Confidence","Result"
            ]])
        print("✅ Google Sheets connected!")
        return True
    except Exception as e:
        print(f"❌ Sheets: {e}")
        return False

def log_to_gsheet(name, signal, entry, yh, yl, top20, bottom20, mid, sl, target, trend, conf):
    if not gsheet_client:
        return None
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        sh  = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws  = sh.sheet1
        ws.append_row([
            now.strftime("%d-%b-%Y"),
            now.strftime("%I:%M %p"),
            name, signal,
            round(entry, 2),
            round(yh, 2),
            round(yl, 2),
            round(top20, 2),
            round(bottom20, 2),
            round(mid, 2),
            round(sl, 2),
            round(target, 2),
            trend,
            conf,
            "MONITORING"
        ])
        all_rows = ws.get_all_values()
        row_num  = len(all_rows)
        print(f"✅ Logged {name} row {row_num}")
        return row_num
    except Exception as e:
        print(f"❌ Sheets log: {e}")
        return None

def update_outcome(row_num, exit_price, pnl, result):
    if not gsheet_client or not row_num:
        return
    try:
        sh = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1
        ws.update_cell(row_num, 15, result)
        print(f"✅ Updated outcome row {row_num}: {result}")
    except Exception as e:
        print(f"❌ Outcome update: {e}")

# ──────────────────────────────────────────────
#  📡 TELEGRAM
# ──────────────────────────────────────────────
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r   = requests.post(url, data={
            "chat_id"                 : TELEGRAM_CHAT_ID,
            "text"                    : msg,
            "parse_mode"              : "HTML",
            "disable_web_page_preview": False
        }, timeout=10)
        print("✅ TG sent!" if r.status_code == 200 else f"❌ {r.text}")
    except Exception as e:
        print(f"❌ TG: {e}")

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%d-%b-%Y %I:%M %p IST")

def get_chart_link(tv_symbol):
    return f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={TV_INTERVAL}"

# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 THE RUMERS BOX STRATEGY CORE LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

def build_rumers_box(df_daily, df_5m):
    """
    Build The Rumers Box Strategy
    
    Uses yesterday's HIGH/LOW to create trading zones
    """
    
    if len(df_daily) < 2:
        return None
    
    # Get yesterday's data
    yesterday = df_daily.iloc[-2]
    yesterday_high = float(yesterday['High'])
    yesterday_low = float(yesterday['Low'])
    
    box_range = yesterday_high - yesterday_low
    
    # Calculate zones
    top_20 = yesterday_high - (box_range * BOX_ZONE_PERCENT)
    bottom_20 = yesterday_low + (box_range * BOX_ZONE_PERCENT)
    midpoint = yesterday_high - (box_range * MIDPOINT_PERCENT)
    
    # Check if setup is qualified (8:45 AM opening candle)
    try:
        opening_candles = df_5m[
            (df_5m.index.hour == OPENING_HOUR) & 
            (df_5m.index.minute == OPENING_MINUTE)
        ]
        
        if len(opening_candles) > 0:
            opening = opening_candles.iloc[-1]
            opening_range = float(opening['High'] - opening['Low'])
            qualified = opening_range > (box_range * BOX_ZONE_PERCENT)
        else:
            qualified = False
    except:
        qualified = False
    
    return {
        'yesterday_high': yesterday_high,
        'yesterday_low': yesterday_low,
        'box_range': box_range,
        'top_20': top_20,
        'bottom_20': bottom_20,
        'midpoint': midpoint,
        'qualified': qualified,
        'current_price': float(df_5m.iloc[-1]['Close'])
    }

def generate_signal(stock_name, box_data):
    """
    Generate BUY/SELL signals based on Rumers Box
    """
    
    if not box_data or not box_data['qualified']:
        return None
    
    current = box_data['current_price']
    top_20 = box_data['top_20']
    bottom_20 = box_data['bottom_20']
    midpoint = box_data['midpoint']
    yh = box_data['yesterday_high']
    yl = box_data['yesterday_low']
    
    signal = None
    
    # BUY signal: Price touches bottom 20%
    if current <= bottom_20 and current > yl:
        signal = {
            'type': 'BUY',
            'entry': bottom_20,
            'sl': yl,
            'target': midpoint,
            'zone': 'BOTTOM_20%'
        }
    
    # SELL signal: Price touches top 20%
    elif current >= top_20 and current < yh:
        signal = {
            'type': 'SELL',
            'entry': top_20,
            'sl': yh,
            'target': midpoint,
            'zone': 'TOP_20%'
        }
    
    return signal

def alert_signal(stock, box_data, signal):
    """Send alert when signal is generated"""
    
    chart = get_chart_link(stock['tv'])
    emoji = "🟢" if signal['type'] == "BUY" else "🔴"
    
    yh = box_data['yesterday_high']
    yl = box_data['yesterday_low']
    entry = signal['entry']
    sl = signal['sl']
    target = signal['target']
    
    risk = abs(entry - sl)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0
    
    bot_status['last_signal'] = f"{signal['type']} {stock['name']} @ {entry:.2f}"
    bot_status['total_signals'] += 1
    
    send_telegram(
        f"🎯 <b>RUMERS BOX SIGNAL</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{signal['type']} — {stock['name']}</b>\n\n"
        f"📍 <b>Entry Zone:</b> {signal['zone']}\n"
        f"Entry: <b>{entry:.2f}</b>\n\n"
        f"🛡 <b>Stop Loss:</b> <b>{sl:.2f}</b> ({risk:.2f} pts)\n"
        f"🎯 <b>Target:</b> <b>{target:.2f}</b> ({reward:.2f} pts)\n"
        f"📊 <b>Risk/Reward:</b> 1:{rr:.1f}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 <b>Yesterday's Range:</b>\n"
        f"High: {yh:.2f} | Low: {yl:.2f}\n\n"
        f"👁 Monitoring live...\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}"
    )
    
    row_num = log_to_gsheet(
        stock['name'], signal['type'], entry, yh, yl,
        box_data['top_20'], box_data['bottom_20'], box_data['midpoint'],
        sl, target, "RUMERS_BOX", signal['zone']
    )
    
    with active_trades_lock:
        active_trades[stock['symbol']] = {
            "name": stock['name'],
            "signal": signal['type'],
            "entry": entry,
            "sl": sl,
            "target": target,
            "row": row_num,
            "symbol": stock['symbol'],
        }
        bot_status['active_trades'] = len(active_trades)
    
    print(f"👁 Monitoring {stock['name']} live!")

def alert_startup():
    names = "\n".join([f"• {s['name']}" for s in STOCKS])
    send_telegram(
        f"🎯 <b>RUMERS BOX BOT Started!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 Strategy: The Rumers Box (Price Action)\n"
        f"📊 Scanning {len(STOCKS)} stocks\n"
        f"🕐 {TRADE_START} – {TRADE_END} IST\n\n"
        f"📏 <b>Rules:</b>\n"
        f"• Yesterday's HIGH/LOW = Box\n"
        f"• 20% zones = Entry signals\n"
        f"• 50% midpoint = Exit target\n"
        f"• 1:2+ Risk/Reward ratio\n\n"
        f"📋 Stocks:\n{names}\n\n"
        f"⏰ {get_ist_time()}"
    )

# ──────────────────────────────────────────────
#  🕐 TIME CHECK
# ──────────────────────────────────────────────
def is_trading_time():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    if now.weekday() >= 5:
        return False
    sh, sm = map(int, TRADE_START.split(":"))
    eh, em = map(int, TRADE_END.split(":"))
    start  = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end    = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end

# ──────────────────────────────────────────────
#  📦 DATA FETCH
# ──────────────────────────────────────────────
def fetch_data(symbol):
    cache_key = f"{symbol}_daily"
    cached = data_cache.get(cache_key)
    if cached is not None:
        return cached
    
    for attempt in range(3):
        try:
            df = yf.download(symbol, interval="1d", period="30d", progress=False)
            if df.empty:
                return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df[['Open','High','Low','Close','Volume']].dropna()
            
            if len(df) > 20:
                df = df.iloc[-20:]
            
            data_cache.set(cache_key, df)
            time.sleep(3)
            return df
        except Exception as e:
            print(f"⚠️ {symbol} daily attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(20)
            else:
                time.sleep(40)
    return None

def fetch_intraday(symbol):
    cache_key = f"{symbol}_5m"
    cached = data_cache.get(cache_key)
    if cached is not None:
        return cached
    
    for attempt in range(3):
        try:
            df = yf.download(symbol, interval="5m", period="3d", progress=False)
            if df.empty:
                return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df[['Open','High','Low','Close','Volume']].dropna()
            
            if len(df) > 100:
                df = df.iloc[-100:]
            
            data_cache.set(cache_key, df)
            time.sleep(3)
            return df
        except Exception as e:
            print(f"⚠️ {symbol} 5m attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(20)
            else:
                time.sleep(40)
    return None

def get_current_price(symbol):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            data   = ticker.history(period="1d", interval="1m")
            if data.empty:
                return None
            return float(data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ Price {symbol} attempt {attempt+1}: {e}")
            time.sleep(5)
    return None

# ──────────────────────────────────────────────
#  👁 LIVE TRADE MONITOR
# ──────────────────────────────────────────────
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
                target = trade['target']
                row = trade['row']
                
                result = None
                pnl = 0
                
                if signal_type == "BUY":
                    pnl = price - entry
                    if price >= target:
                        result = "✅ WIN TARGET"
                        bot_status['wins'] += 1
                    elif price <= sl:
                        result = "❌ LOSS SL"
                        pnl = price - entry
                        bot_status['losses'] += 1
                
                elif signal_type == "SELL":
                    pnl = entry - price
                    if price <= target:
                        result = "✅ WIN TARGET"
                        bot_status['wins'] += 1
                    elif price >= sl:
                        result = "❌ LOSS SL"
                        pnl = entry - price
                        bot_status['losses'] += 1
                
                if result:
                    emoji = "✅" if "WIN" in result else "❌"
                    send_telegram(
                        f"📊 <b>Trade Closed</b>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{emoji} <b>{name}</b>\n\n"
                        f"Type: {signal_type}\n"
                        f"Entry: {entry:.2f}\n"
                        f"Exit: {price:.2f}\n"
                        f"P&L: {pnl:+.2f} pts\n\n"
                        f"<b>{result}</b>\n\n"
                        f"⏰ {get_ist_time()}"
                    )
                    update_outcome(row, price, pnl, result)
                    with active_trades_lock:
                        active_trades.pop(symbol, None)
                        bot_status['active_trades'] = len(active_trades)
                    print(f"✅ Closed: {name} {result}")
                
                time.sleep(3)
        except Exception as e:
            print(f"❌ Monitor error: {e}")
        time.sleep(60)

# ──────────────────────────────────────────────
#  🔄 SCAN EACH STOCK
# ──────────────────────────────────────────────
def scan_stock(stock):
    symbol = stock['symbol']
    name   = stock['name']
    try:
        with active_trades_lock:
            if symbol in active_trades:
                return
        
        df_daily = fetch_data(symbol)
        df_5m = fetch_intraday(symbol)
        
        if df_daily is None or df_5m is None:
            return
        
        if len(df_daily) < 2:
            return
        
        # Build Rumers Box
        box_data = build_rumers_box(df_daily, df_5m)
        
        if not box_data:
            return
        
        print(f"  {name}: Price={box_data['current_price']:.2f} Qualified={box_data['qualified']}")
        
        if not box_data['qualified']:
            return
        
        # Generate signal
        signal = generate_signal(name, box_data)
        
        if signal is None:
            return
        
        # Check if already alerted
        alert_key = f"{symbol}_{datetime.now().strftime('%H:%M')}"
        if alert_key in alert_history:
            return
        
        print(f"  ✅ SIGNAL: {signal['type']} {name} @ {signal['entry']:.2f}")
        alert_signal(stock, box_data, signal)
        alert_history[alert_key] = True
        
        if len(alert_history) > 100:
            oldest_key = next(iter(alert_history))
            del alert_history[oldest_key]
    
    except Exception as e:
        print(f"❌ {name}: {e}")

# ──────────────────────────────────────────────
#  🔄 MAIN LOOP
# ──────────────────────────────────────────────
def run_strategy():
    print(f"\n{'='*40}\n🔄 {get_ist_time()}")
    bot_status['last_check'] = get_ist_time()
    
    if not is_trading_time():
        print("⏸  Outside trading hours (9:15 AM - 3:15 PM IST).")
        return
    
    print(f"Scanning {len(STOCKS)} stocks with Rumers Box...")
    for stock in STOCKS:
        scan_stock(stock)
        time.sleep(10)
    
    gc.collect()

def bot_loop():
    print("🚀 The Rumers Box Bot starting...")
    alert_startup()
    while True:
        try:
            run_strategy()
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(120)  # Scan every 2 minutes

# ──────────────────────────────────────────────
#  ▶️ START
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
    elif not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID not set!")
    else:
        monitor_thread = threading.Thread(target=monitor_trades)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        bot_thread = threading.Thread(target=bot_loop)
        bot_thread.daemon = True
        bot_thread.start()
        
        init_gsheet()
        run_web_server()
