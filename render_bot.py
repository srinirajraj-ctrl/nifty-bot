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
except:
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
ATR_MULTIPLIER = 0.20  # 20% qualification threshold
SL_BUFFER = 0.20
TRADE_START = "09:15"
TRADE_END = "15:15"

bot_status = {"last_check": "Not started", "last_signal": "None", "total_signals": 0, "wins": 0, "losses": 0, "active_trades": 0}
active_trades = {}
active_trades_lock = threading.Lock()

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

def log_to_gsheet(stock_name, signal_type, entry, daily_atr, threshold, opening_range, box_high, box_low, box_mid, pattern, sl, tp1, tp2):
    global gsheet_ws
    if not gsheet_ws:
        return None
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        
        # 16 columns (A-P): Separated TP1 and TP2
        row_data = [
            now.strftime("%d-%b-%Y"),                          # A: Date
            now.strftime("%I:%M %p"),                          # B: Time
            stock_name,                                         # C: Stock
            signal_type,                                        # D: Signal
            round(entry, 2),                                    # E: Entry
            round(daily_atr, 2),                                # F: ATR Threshold
            round(opening_range, 2),                            # G: Opening Range
            "YES" if opening_range >= threshold else "NO",     # H: Manipulated?
            pattern,                                            # I: Pattern
            round(sl, 2),                                       # J: SL
            round(tp1, 2),                                      # K: TP1 (Midpoint)
            round(tp2, 2),                                      # L: TP2 (Opposite)
            "",                                                 # M: Exit Price
            "",                                                 # N: P&L
            "MONITORING",                                       # O: Result
            "",                                                 # P: Notes
        ]
        
        gsheet_ws.append_row(row_data)
        all_rows = gsheet_ws.get_all_values()
        row_num = len(all_rows)
        print(f"✅ Logged {stock_name} to row {row_num}")
        return row_num
    except Exception as e:
        print(f"❌ Log error: {e}")
        return None

def update_gsheet_close(row_num, exit_tp1, pnl_tp1, exit_tp2, pnl_tp2, total_pnl, result):
    global gsheet_ws
    if not gsheet_ws or not row_num:
        return
    try:
        if exit_tp1:
            gsheet_ws.update_cell(row_num, 17, round(exit_tp1, 2))  # Q: Exit Price TP1
            gsheet_ws.update_cell(row_num, 18, round(pnl_tp1, 2))   # R: P&L TP1
        if exit_tp2:
            gsheet_ws.update_cell(row_num, 19, round(exit_tp2, 2))  # S: Exit Price TP2
            gsheet_ws.update_cell(row_num, 20, round(pnl_tp2, 2))   # T: P&L TP2
        if total_pnl:
            gsheet_ws.update_cell(row_num, 21, round(total_pnl, 2)) # U: Total P&L
        gsheet_ws.update_cell(row_num, 22, result)                  # V: Result
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
        html = f"""<html><head><title>Manipulation Box Reversal Bot</title><meta http-equiv="refresh" content="30"><style>body{{font-family:Arial;padding:20px;background:#1a1a2e;color:#eee}}h1{{color:#00d4aa}}.card{{background:#16213e;padding:15px;border-radius:10px;margin:10px 0}}.green{{color:#00ff88}}.red{{color:#ff4444}}</style></head><body><h1>Manipulation Box Strategy</h1><div class="card"><p>ATR × 0.35 Qualification</p><p>Box HIGH/LOW/MID Setup</p><p>Reversal Pattern at Box</p><p>TP1 (Mid) & TP2 (Opposite)</p></div><div class="card"><p>Last Check: {bot_status['last_check']}</p><p class="green">Wins: {bot_status['wins']}</p><p class="red">Losses: {bot_status['losses']}</p><p>Win Rate: {win_rate}%</p></div><div class="card"><p>Active: {len(active_trades)}</p><ul>{active_list}</ul></div></body></html>"""
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

def check_manipulation_box(symbol, df_5m, daily_atr):
    if daily_atr is None: return None
    threshold = daily_atr * ATR_MULTIPLIER
    try:
        first_3 = df_5m.head(3)
        if len(first_3) < 3: return None
        box_high = float(first_3['High'].max())
        box_low = float(first_3['Low'].min())
        opening_range = box_high - box_low
        box_mid = (box_high + box_low) / 2
        is_qualified = opening_range >= threshold
        return {
            'qualified': is_qualified,
            'opening_range': opening_range,
            'threshold': threshold,
            'box_high': box_high,
            'box_low': box_low,
            'box_mid': box_mid,
            'box_range': opening_range
        }
    except: return None

def detect_reversal_at_box(df_5m, box_high, box_low):
    """Detect reversal pattern AT box levels (candle 4+)"""
    if len(df_5m) < 4: return None
    try:
        # Check candles 4 onwards (index 3+)
        for i in range(3, min(len(df_5m), 10)):  # Check up to candle 10
            candle = df_5m.iloc[i]
            candle_high = float(candle['High'])
            candle_low = float(candle['Low'])
            candle_close = float(candle['Close'])
            candle_open = float(candle['Open'])
            
            # Check if candle touches box levels
            touches_high = candle_high >= (box_high * 0.98)  # Within 2% of box high
            touches_low = candle_low <= (box_low * 1.02)     # Within 2% of box low
            
            if touches_high:
                # Wick rejection at high
                wick_size = candle_high - max(candle_open, candle_close)
                candle_range = candle_high - candle_low
                if candle_range > 0 and wick_size / candle_range > 0.5:
                    if candle_close < candle_open:  # Closes lower = reversal down
                        return "WICK_REJECTION_DOWN", i
                # Bearish engulfing at high
                if i > 0:
                    prev = df_5m.iloc[i-1]
                    if candle_open > prev['Close'] and candle_close < prev['Open']:
                        return "BEARISH_ENGULFING_AT_HIGH", i
            
            if touches_low:
                # Wick rejection at low
                wick_size = min(candle_open, candle_close) - candle_low
                candle_range = candle_high - candle_low
                if candle_range > 0 and wick_size / candle_range > 0.5:
                    if candle_close > candle_open:  # Closes higher = reversal up
                        return "WICK_REJECTION_UP", i
                # Bullish engulfing at low
                if i > 0:
                    prev = df_5m.iloc[i-1]
                    if candle_open < prev['Close'] and candle_close > prev['Open']:
                        return "BULLISH_ENGULFING_AT_LOW", i
        
        return None
    except: return None

def generate_signal(df_5m, box_data, pattern_info):
    if not box_data or not box_data['qualified'] or pattern_info is None: 
        return None
    
    pattern, candle_idx = pattern_info
    candle = df_5m.iloc[candle_idx]
    entry = float(candle['Close'])  # Entry at reversal candle close
    
    box_high = box_data['box_high']
    box_low = box_data['box_low']
    box_mid = box_data['box_mid']
    box_range = box_data['box_range']
    
    if "UP" in pattern or "BULLISH" in pattern:
        # BUY signal
        sl = box_low - (box_range * SL_BUFFER)
        return {
            'type': 'BUY',
            'entry': entry,
            'pattern': pattern,
            'sl': sl,
            'tp1': box_mid,
            'tp2': box_high,
            'box_high': box_high,
            'box_low': box_low,
            'box_mid': box_mid
        }
    elif "DOWN" in pattern or "BEARISH" in pattern:
        # SELL signal
        sl = box_high + (box_range * SL_BUFFER)
        return {
            'type': 'SELL',
            'entry': entry,
            'pattern': pattern,
            'sl': sl,
            'tp1': box_mid,
            'tp2': box_low,
            'box_high': box_high,
            'box_low': box_low,
            'box_mid': box_mid
        }
    return None

def alert_signal(stock, box_data, signal, daily_atr, threshold):
    bot_status['last_signal'] = f"{signal['type']} {stock['name']}"
    bot_status['total_signals'] += 1
    emoji = "🟢" if signal['type'] == "BUY" else "🔴"
    entry = signal['entry']
    tp1 = signal['tp1']
    tp2 = signal['tp2']
    sl = signal['sl']
    
    chart_url = f"https://www.tradingview.com/chart/?symbol={stock['tv']}&interval=5"
    
    send_telegram(
        f"{emoji} <b>{signal['type']} {stock['name']}</b>\n\n"
        f"📍 Entry: {entry:.2f}\n"
        f"🛡 SL: {sl:.2f}\n"
        f"🎯 TP1 (Mid): {tp1:.2f}\n"
        f"🎯 TP2 (Opposite): {tp2:.2f}\n"
        f"📊 Pattern: {signal['pattern']}\n"
        f"📦 Box Range: {box_data['box_range']:.2f}\n\n"
        f"📊 <a href='{chart_url}'>Open TradingView Chart</a>\n\n"
        f"{get_ist_time()}"
    )
    
    row_num = log_to_gsheet(
        stock['name'], signal['type'], entry, daily_atr, threshold,
        box_data['opening_range'], signal['box_high'], signal['box_low'],
        signal['box_mid'], signal['pattern'], sl, tp1, tp2
    )
    
    with active_trades_lock:
        active_trades[stock['symbol']] = {
            "name": stock['name'],
            "signal": signal['type'],
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "row": row_num,
            "symbol": stock['symbol'],
            "tp1_hit": False,
            "tp2_hit": False
        }
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
        except: 
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
        except: 
            if attempt < 2: time.sleep(20)
    return None

def get_current_price(symbol):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if data.empty: return None
            return float(data['Close'].iloc[-1])
        except: time.sleep(5)
    return None

def monitor_trades():
    while True:
        try:
            # Check if it's market close time (3:15 PM)
            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist)
            
            if now.weekday() < 5:  # Trading day
                close_time = now.replace(hour=15, minute=15, second=0, microsecond=0)
                if now >= close_time:
                    # Market closed - auto-close all remaining trades
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
                        row_num = trade['row']
                        exit_price = price
                        
                        if signal_type == "BUY":
                            pnl = exit_price - entry
                        else:
                            pnl = entry - exit_price
                        
                        result = "CLOSED AT MARKET CLOSE"
                        
                        send_telegram(
                            f"📊 <b>MARKET CLOSE - AUTO-CLOSED</b>\n"
                            f"{name} {signal_type}\n"
                            f"Entry: {entry:.2f} | Exit: {exit_price:.2f}\n"
                            f"P&L: {pnl:+.2f}\n{result}\n{get_ist_time()}"
                        )
                        
                        try:
                            gsheet_ws.update_cell(row_num, 12, round(exit_price, 2))
                            gsheet_ws.update_cell(row_num, 13, round(pnl, 2))
                            gsheet_ws.update_cell(row_num, 14, result)
                        except: pass
                        
                        with active_trades_lock:
                            active_trades.pop(symbol, None)
                            bot_status['active_trades'] = len(active_trades)
            
            with active_trades_lock:
                symbols = list(active_trades.keys())
            for symbol in symbols:
                with active_trades_lock:
                    if symbol not in active_trades: continue
                    trade = active_trades[symbol].copy()
                
                price = get_current_price(symbol)
                if price is None: continue
                
                name = trade['name']
                signal_type = trade['signal']
                entry = trade['entry']
                sl = trade['sl']
                tp1 = trade['tp1']
                tp2 = trade['tp2']
                row_num = trade['row']
                tp1_hit = trade['tp1_hit']
                tp2_hit = trade['tp2_hit']
                
                exit_tp1, pnl_tp1 = None, None
                exit_tp2, pnl_tp2 = None, None
                result = None
                
                if signal_type == "BUY":
                    if price >= tp1 and not tp1_hit:
                        exit_tp1, pnl_tp1 = tp1, tp1 - entry
                        with active_trades_lock:
                            if symbol in active_trades:
                                active_trades[symbol]['tp1_hit'] = True
                    
                    if price >= tp2 and not tp2_hit:
                        exit_tp2, pnl_tp2 = tp2, tp2 - entry
                        total_pnl = (pnl_tp1 or 0) + pnl_tp2
                        result = "✅ WIN TP2"
                        bot_status['wins'] += 1
                    
                    elif price <= sl:
                        result = "❌ LOSS SL"
                        bot_status['losses'] += 1
                
                elif signal_type == "SELL":
                    if price <= tp1 and not tp1_hit:
                        exit_tp1, pnl_tp1 = tp1, entry - tp1
                        with active_trades_lock:
                            if symbol in active_trades:
                                active_trades[symbol]['tp1_hit'] = True
                    
                    if price <= tp2 and not tp2_hit:
                        exit_tp2, pnl_tp2 = tp2, entry - tp2
                        total_pnl = (pnl_tp1 or 0) + pnl_tp2
                        result = "✅ WIN TP2"
                        bot_status['wins'] += 1
                    
                    elif price >= sl:
                        result = "❌ LOSS SL"
                        bot_status['losses'] += 1
                
                if result:
                    total_pnl = (pnl_tp1 or 0) + (pnl_tp2 or 0)
                    send_telegram(
                        f"📊 <b>{name}</b>\n"
                        f"{signal_type} | Entry: {entry:.2f}\n"
                        f"TP1: {exit_tp1 or 'N/A':.2f if exit_tp1 else 'N/A'} | P&L: {pnl_tp1 or 0:+.2f}\n"
                        f"TP2: {exit_tp2 or 'N/A':.2f if exit_tp2 else 'N/A'} | P&L: {pnl_tp2 or 0:+.2f}\n"
                        f"Total P&L: {total_pnl:+.2f}\n"
                        f"{result}\n"
                        f"{get_ist_time()}"
                    )
                    update_gsheet_close(row_num, exit_tp1, pnl_tp1, exit_tp2, pnl_tp2, total_pnl, result)
                    with active_trades_lock:
                        active_trades.pop(symbol, None)
                        bot_status['active_trades'] = len(active_trades)
                    print(f"✅ {name} {result}")
                
                time.sleep(5)
        except Exception as e:
            print(f"❌ Monitor: {e}")
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
        
        box_data = check_manipulation_box(symbol, df_5m, daily_atr)
        if box_data is None or not box_data['qualified']: return
        
        print(f"  {name}: Box Range {box_data['opening_range']:.2f} >= {box_data['threshold']:.2f} ✅")
        
        pattern_info = detect_reversal_at_box(df_5m, box_data['box_high'], box_data['box_low'])
        if pattern_info is None: return
        
        pattern, idx = pattern_info
        print(f"  ✅ {name}: Pattern={pattern} at candle {idx+1}")
        
        signal = generate_signal(df_5m, box_data, pattern_info)
        if signal is None: return
        
        alert_key = f"{symbol}_{datetime.now().strftime('%H:%M')}"
        if alert_key in alert_history: return
        
        print(f"  ✅ SIGNAL: {signal['type']} {name}")
        alert_signal(stock, box_data, signal, daily_atr, box_data['threshold'])
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
    print(f"Scanning {len(STOCKS)} with Manipulation Box Strategy...")
    for stock in STOCKS:
        scan_stock(stock)
        time.sleep(10)
    gc.collect()

def bot_loop():
    print("🚀 Manipulation Box Reversal Bot starting...")
    send_telegram("🎯 Manipulation Box Bot Started!\n\n✅ ATR × 0.35 Qualification\n✅ Box HIGH/LOW/MID\n✅ Reversal at Box Levels\n✅ TP1 (Mid) & TP2 (Opposite)\n✅ Proper SL Management\n\n" + get_ist_time())
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
