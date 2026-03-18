import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import pytz
import os
import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import warnings
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────
#  ⚙️ CREDENTIALS
# ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GOOGLE_SHEET_ID    = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON  = os.environ.get("GOOGLE_CREDS_JSON", "")

# ──────────────────────────────────────────
#  📋 STOCKS TO SCAN
# ──────────────────────────────────────────
STOCKS = [
    {"symbol": "^NSEI",          "name": "NIFTY 50",       "tv": "NSE:NIFTY",       "sl": 20},
    {"symbol": "^NSEBANK",       "name": "BANK NIFTY",     "tv": "NSE:BANKNIFTY",   "sl": 50},
    {"symbol": "SBIN.NS",        "name": "SBIN",           "tv": "NSE:SBIN",        "sl": 2},
    {"symbol": "IDEA.NS",        "name": "IDEA",           "tv": "NSE:IDEA",        "sl": 1},
    {"symbol": "YESBANK.NS",     "name": "YES BANK",       "tv": "NSE:YESBANK",     "sl": 1},
    {"symbol": "SAIL.NS",        "name": "SAIL",           "tv": "NSE:SAIL",        "sl": 2},
    {"symbol": "NHPC.NS",        "name": "NHPC",           "tv": "NSE:NHPC",        "sl": 2},
    {"symbol": "IRFC.NS",        "name": "IRFC",           "tv": "NSE:IRFC",        "sl": 2},
    {"symbol": "PNB.NS",         "name": "PNB",            "tv": "NSE:PNB",         "sl": 2},
    {"symbol": "BANKBARODA.NS",  "name": "BANK OF BARODA", "tv": "NSE:BANKBARODA",  "sl": 2},
    {"symbol": "SUZLON.NS",      "name": "SUZLON",         "tv": "NSE:SUZLON",      "sl": 1},
    {"symbol": "HFCL.NS",        "name": "HFCL",           "tv": "NSE:HFCL",        "sl": 2},
    {"symbol": "TRIDENT.NS",     "name": "TRIDENT",        "tv": "NSE:TRIDENT",     "sl": 1},
    {"symbol": "JPPOWER.NS",     "name": "JP POWER",       "tv": "NSE:JPPOWER",     "sl": 1},
    {"symbol": "DISHTV.NS",      "name": "DISH TV",        "tv": "NSE:DISHTV",      "sl": 1},
    {"symbol": "ITI.NS",         "name": "ITI",            "tv": "NSE:ITI",         "sl": 1},
    {"symbol": "RVNL.NS",        "name": "RVNL",           "tv": "NSE:RVNL",        "sl": 2},
    {"symbol": "NALCO.NS",       "name": "NALCO",          "tv": "NSE:NALCO",       "sl": 2},
    {"symbol": "NMDC.NS",        "name": "NMDC",           "tv": "NSE:NMDC",        "sl": 2},
    {"symbol": "HINDCOPPER.NS",  "name": "HIND COPPER",    "tv": "NSE:HINDCOPPER",  "sl": 2},
    {"symbol": "CENTRALBK.NS",   "name": "CENTRAL BANK",   "tv": "NSE:CENTRALBK",   "sl": 1},
    {"symbol": "BEML.NS",        "name": "BEML",           "tv": "NSE:BEML",        "sl": 2},
    {"symbol": "ABCAPITAL.NS",   "name": "ABIRLA CAPITAL", "tv": "NSE:ABCAPITAL",   "sl": 2},
]

INTERVAL     = "5m"
TV_INTERVAL  = "5"

HLC3_SHIFT      = 1
SLOW_EMA_PERIOD = 20
KAMA_LENGTH     = 5
KAMA_FASTEND    = 2.5
KAMA_SLOWEND    = 20

TARGET1_RATIO = 1.5
TARGET2_RATIO = 2.0

TRADE_START = "9:15"
TRADE_END   = "15:30"

bot_status = {
    "last_check": "Not started",
    "last_signal": "None",
    "total_signals": 0,
    "stocks_scanned": 0
}


# ──────────────────────────────────────────
#  🌐 WEB SERVER
# ──────────────────────────────────────────
class BotHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        stock_list = "".join([f"<li>{s['name']}</li>" for s in STOCKS])
        html = f"""
        <html>
        <head>
            <title>Nifty Bot Status</title>
            <meta http-equiv="refresh" content="60">
            <style>
                body {{ font-family: Arial; padding: 20px; background: #1a1a2e; color: #eee; }}
                h1 {{ color: #00d4aa; }}
                .card {{ background: #16213e; padding: 15px; border-radius: 10px; margin: 10px 0; }}
                .green {{ color: #00ff88; }}
                ul {{ columns: 2; }}
            </style>
        </head>
        <body>
            <h1>&#x1F916; Multi Stock Bot Status</h1>
            <div class="card">
                <p>&#x23F1; <b>Timeframe:</b> {INTERVAL}</p>
                <p>&#x1F557; <b>Trading Hours:</b> {TRADE_START} - {TRADE_END} IST</p>
                <p>&#x1F4CA; <b>Stocks Scanning:</b> {len(STOCKS)}</p>
            </div>
            <div class="card">
                <p>&#x1F504; <b>Last Check:</b> {bot_status['last_check']}</p>
                <p>&#x1F4CA; <b>Stocks Scanned:</b> {bot_status['stocks_scanned']}</p>
                <p>&#x1F3AF; <b>Last Signal:</b> <span class="green">{bot_status['last_signal']}</span></p>
                <p>&#x1F4E8; <b>Total Signals:</b> {bot_status['total_signals']}</p>
            </div>
            <div class="card">
                <b>Scanning These Stocks:</b>
                <ul>{stock_list}</ul>
            </div>
            <div class="card">
                <p class="green">&#x1F7E2; Bot is Running 24/7</p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), BotHandler)
    print(f"✅ Web server running on port {port}")
    server.serve_forever()


# ──────────────────────────────────────────
#  📊 GOOGLE SHEETS
# ──────────────────────────────────────────
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
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gsheet_client = gspread.authorize(creds)
        sh = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1
        if ws.cell(1,1).value != "Date":
            ws.update('A1:H1', [[
                "Date","Time","Stock","Signal",
                "Entry","Stop Loss","Target1","Target2"
            ]])
        print("✅ Google Sheets connected!")
        return True
    except Exception as e:
        print(f"❌ Sheets error: {e}")
        return False

def log_to_gsheet(stock_name, signal, price, sl, t1, t2):
    if not gsheet_client:
        return
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        sh  = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws  = sh.sheet1
        ws.append_row([
            now.strftime("%d-%b-%Y"),
            now.strftime("%I:%M %p"),
            stock_name,
            signal,
            round(price, 2),
            round(sl, 2),
            round(t1, 2),
            round(t2, 2),
        ])
        print(f"✅ Logged {stock_name} {signal} to Sheets!")
    except Exception as e:
        print(f"❌ Sheets log error: {e}")


# ──────────────────────────────────────────
#  📡 TELEGRAM
# ──────────────────────────────────────────
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }, timeout=10)
        print("✅ Telegram sent!" if r.status_code == 200 else f"❌ {r.text}")
    except Exception as e:
        print(f"❌ {e}")

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%d-%b-%Y %I:%M %p IST")

def get_chart_link(tv_symbol):
    return f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={TV_INTERVAL}"

def alert_buy(stock, price):
    sl  = price - stock['sl']
    t1  = price + (stock['sl'] * TARGET1_RATIO)
    t2  = price + (stock['sl'] * TARGET2_RATIO)
    chart = get_chart_link(stock['tv'])
    bot_status['last_signal'] = f"BUY {stock['name']} @ {price:.0f}"
    bot_status['total_signals'] += 1
    send_telegram(
        f"🟢 <b>BUY — {stock['name']}</b>\n\n"
        f"📈 Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{sl:.2f}</b>\n"
        f"🎯 Target1: <b>{t1:.2f}</b>\n"
        f"🎯 Target2: <b>{t2:.2f}</b>\n\n"
        f"✅ HLC3/KAU Crossover\n\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}\n"
        f"⚠️ Paper trade first!"
    )
    log_to_gsheet(stock['name'], "BUY", price, sl, t1, t2)

def alert_sell(stock, price):
    sl  = price + stock['sl']
    t1  = price - (stock['sl'] * TARGET1_RATIO)
    t2  = price - (stock['sl'] * TARGET2_RATIO)
    chart = get_chart_link(stock['tv'])
    bot_status['last_signal'] = f"SELL {stock['name']} @ {price:.0f}"
    bot_status['total_signals'] += 1
    send_telegram(
        f"🔴 <b>SELL — {stock['name']}</b>\n\n"
        f"📉 Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{sl:.2f}</b>\n"
        f"🎯 Target1: <b>{t1:.2f}</b>\n"
        f"🎯 Target2: <b>{t2:.2f}</b>\n\n"
        f"✅ HLC3/KAU Crossover\n\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}\n"
        f"⚠️ Paper trade first!"
    )
    log_to_gsheet(stock['name'], "SELL", price, sl, t1, t2)

def alert_startup():
    names = ", ".join([s['name'] for s in STOCKS])
    send_telegram(
        f"🚀 <b>Multi Stock Bot Started!</b>\n\n"
        f"📊 Scanning {len(STOCKS)} stocks\n"
        f"🕐 {TRADE_START} – {TRADE_END} IST\n"
        f"✅ HLC3/KAU Signal\n\n"
        f"📋 Stocks:\n{names}\n\n"
        f"⏰ {get_ist_time()}"
    )


# ──────────────────────────────────────────
#  🕐 TIME CHECK
# ──────────────────────────────────────────
def is_trading_time():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    if now.weekday() >= 5:
        return False
    sh, sm = map(int, TRADE_START.split(":"))
    eh, em = map(int, TRADE_END.split(":"))
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end   = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


# ──────────────────────────────────────────
#  📦 DATA FETCH
# ──────────────────────────────────────────
def fetch_data(symbol, interval, period):
    try:
        df = yf.download(symbol, interval=interval, period=period, progress=False)
        if df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df[['Open','High','Low','Close','Volume']].dropna()
        return df
    except Exception as e:
        print(f"❌ {symbol}: {e}")
        return None

def fetch_htf(symbol):
    try:
        df = yf.download(symbol, interval="1h", period="60d", progress=False)
        if df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df[['Open','High','Low','Close','Volume']].dropna()
        df4h = df.resample('4h').agg({
            'Open':'first','High':'max',
            'Low':'min','Close':'last','Volume':'sum'
        }).dropna()
        df4h['hlc3'] = (df4h['High'] + df4h['Low'] + df4h['Close']) / 3
        return df4h
    except Exception as e:
        print(f"❌ HTF {symbol}: {e}")
        return None


# ──────────────────────────────────────────
#  📐 INDICATORS
# ──────────────────────────────────────────
def kama(series, length=5, fastend=2.5, slowend=20):
    nfe = 2 / (fastend + 1)
    nse = 2 / (slowend + 1)
    out = np.full(len(series), np.nan)
    p   = series.values
    for i in range(length, len(p)):
        if np.isnan(out[i-1]):
            out[i] = p[i]
            continue
        noise  = np.sum(np.abs(np.diff(p[i-length:i+1])))
        signal = abs(p[i] - p[i-length])
        ef     = signal / noise if noise else 0
        sc     = (ef * (nfe - nse) + nse) ** 2
        out[i] = out[i-1] + sc * (p[i] - out[i-1])
    return pd.Series(out, index=series.index)

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


# ──────────────────────────────────────────
#  🔬 BUILD SIGNALS
# ──────────────────────────────────────────
def build(df, df4h):
    df = df.copy()
    df['hlc3']     = (df['High'] + df['Low'] + df['Close']) / 3
    df['kama_val'] = kama(df['hlc3'], KAMA_LENGTH, KAMA_FASTEND, KAMA_SLOWEND)
    df['bsma']     = ema(df['kama_val'], SLOW_EMA_PERIOD)
    htf            = df4h['hlc3'].shift(HLC3_SHIFT).reindex(df.index, method='ffill')
    df['bfma']     = ema(htf, 1)
    pb             = df['bfma'].shift(1)
    ps             = df['bsma'].shift(1)
    df['buy']      = (df['bfma'] > df['bsma']) & (pb <= ps)
    df['sell']     = (df['bfma'] < df['bsma']) & (pb >= ps)
    return df


# ──────────────────────────────────────────
#  🔄 STRATEGY LOOP
# ──────────────────────────────────────────
last_alerts = {}

def scan_stock(stock):
    symbol = stock['symbol']
    name   = stock['name']
    try:
        df  = fetch_data(symbol, INTERVAL, "5d")
        d4h = fetch_htf(symbol)
        if df is None or d4h is None:
            print(f"⚠️ {name}: No data")
            return
        if len(df) < 30:
            print(f"⚠️ {name}: Not enough data")
            return
        df   = build(df, d4h)
        last = df.iloc[-2]
        ct   = str(df.index[-2])
        print(f"  {name}: Close:{last['Close']:.2f} BUY:{last['buy']} SELL:{last['sell']}")
        if last_alerts.get(symbol) == ct:
            return
        if last['buy']:
            print(f"  ✅ BUY signal — {name}")
            alert_buy(stock, last['Close'])
            last_alerts[symbol] = ct
        elif last['sell']:
            print(f"  ✅ SELL signal — {name}")
            alert_sell(stock, last['Close'])
            last_alerts[symbol] = ct
    except Exception as e:
        print(f"❌ {name} error: {e}")

def run_strategy():
    print(f"\n{'='*40}\n🔄 {get_ist_time()}")
    bot_status['last_check'] = get_ist_time()
    if not is_trading_time():
        print("⏸  Outside trading hours.")
        return
    print(f"Scanning {len(STOCKS)} stocks...")
    bot_status['stocks_scanned'] = len(STOCKS)
    for stock in STOCKS:
        scan_stock(stock)
        time.sleep(2)  # Small delay between stocks

def bot_loop():
    print("🚀 Bot loop starting...")
    alert_startup()
    while True:
        try:
            run_strategy()
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(60)


# ──────────────────────────────────────────
#  ▶️ START
# ──────────────────────────────────────────
if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set!")
elif not TELEGRAM_CHAT_ID:
    print("❌ TELEGRAM_CHAT_ID not set!")
else:
    bot_thread = threading.Thread(target=bot_loop)
    bot_thread.daemon = True
    bot_thread.start()
    init_gsheet()
    run_web_server()
