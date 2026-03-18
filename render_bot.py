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
    {"symbol": "^NSEI",         "name": "NIFTY 50",       "tv": "NSE:NIFTY",      "sl": 20},
    {"symbol": "^NSEBANK",      "name": "BANK NIFTY",     "tv": "NSE:BANKNIFTY",  "sl": 50},
    {"symbol": "SBIN.NS",       "name": "SBIN",           "tv": "NSE:SBIN",       "sl": 2},
    {"symbol": "IDEA.NS",       "name": "IDEA",           "tv": "NSE:IDEA",       "sl": 1},
    {"symbol": "YESBANK.NS",    "name": "YES BANK",       "tv": "NSE:YESBANK",    "sl": 1},
    {"symbol": "SAIL.NS",       "name": "SAIL",           "tv": "NSE:SAIL",       "sl": 2},
    {"symbol": "NHPC.NS",       "name": "NHPC",           "tv": "NSE:NHPC",       "sl": 2},
    {"symbol": "IRFC.NS",       "name": "IRFC",           "tv": "NSE:IRFC",       "sl": 2},
    {"symbol": "PNB.NS",        "name": "PNB",            "tv": "NSE:PNB",        "sl": 2},
    {"symbol": "BANKBARODA.NS", "name": "BANK OF BARODA", "tv": "NSE:BANKBARODA", "sl": 2},
    {"symbol": "SUZLON.NS",     "name": "SUZLON",         "tv": "NSE:SUZLON",     "sl": 1},
    {"symbol": "HFCL.NS",       "name": "HFCL",           "tv": "NSE:HFCL",       "sl": 2},
    {"symbol": "TRIDENT.NS",    "name": "TRIDENT",        "tv": "NSE:TRIDENT",    "sl": 1},
    {"symbol": "JPPOWER.NS",    "name": "JP POWER",       "tv": "NSE:JPPOWER",    "sl": 1},
    {"symbol": "DISHTV.NS",     "name": "DISH TV",        "tv": "NSE:DISHTV",     "sl": 1},
    {"symbol": "ITI.NS",        "name": "ITI",            "tv": "NSE:ITI",        "sl": 1},
    {"symbol": "RVNL.NS",       "name": "RVNL",           "tv": "NSE:RVNL",       "sl": 2},
    {"symbol": "NALCO.NS",      "name": "NALCO",          "tv": "NSE:NALCO",      "sl": 2},
    {"symbol": "NMDC.NS",       "name": "NMDC",           "tv": "NSE:NMDC",       "sl": 2},
    {"symbol": "HINDCOPPER.NS", "name": "HIND COPPER",    "tv": "NSE:HINDCOPPER", "sl": 2},
    {"symbol": "CENTRALBK.NS",  "name": "CENTRAL BANK",   "tv": "NSE:CENTRALBK",  "sl": 1},
    {"symbol": "BEML.NS",       "name": "BEML",           "tv": "NSE:BEML",       "sl": 2},
    {"symbol": "ABCAPITAL.NS",  "name": "AB CAPITAL",     "tv": "NSE:ABCAPITAL",  "sl": 2},
]

INTERVAL        = "5m"
TV_INTERVAL     = "5"
HLC3_SHIFT      = 1
SLOW_EMA_PERIOD = 20
KAMA_LENGTH     = 5
KAMA_FASTEND    = 2.5
KAMA_SLOWEND    = 20
TARGET1_RATIO   = 1.5
TARGET2_RATIO   = 2.0
TRADE_START     = "9:15"
TRADE_END       = "15:30"
SWING_LOOKBACK  = 5

bot_status = {
    "last_check"    : "Not started",
    "last_signal"   : "None",
    "total_signals" : 0,
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
            <title>Multi Stock Bot</title>
            <meta http-equiv="refresh" content="60">
            <style>
                body{{font-family:Arial;padding:20px;background:#1a1a2e;color:#eee}}
                h1{{color:#00d4aa}}
                .card{{background:#16213e;padding:15px;border-radius:10px;margin:10px 0}}
                .green{{color:#00ff88}}
                ul{{columns:2}}
            </style>
        </head>
        <body>
            <h1>&#x1F916; Multi Stock Bot</h1>
            <div class="card">
                <p>&#x23F1; <b>Timeframe:</b> {INTERVAL}</p>
                <p>&#x1F557; <b>Hours:</b> {TRADE_START} - {TRADE_END} IST</p>
                <p>&#x1F4CA; <b>Stocks:</b> {len(STOCKS)}</p>
            </div>
            <div class="card">
                <p>&#x1F504; <b>Last Check:</b> {bot_status['last_check']}</p>
                <p>&#x1F3AF; <b>Last Signal:</b> <span class="green">{bot_status['last_signal']}</span></p>
                <p>&#x1F4E8; <b>Total Signals:</b> {bot_status['total_signals']}</p>
            </div>
            <div class="card">
                <b>Scanning:</b><ul>{stock_list}</ul>
            </div>
            <p class="green">&#x1F7E2; Bot Running 24/7</p>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), BotHandler)
    print(f"✅ Web server on port {port}")
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
            ws.update('A1:K1', [[
                "Date","Time","Stock","Signal","Entry",
                "SL","T1","T2","Trend","AO Signal","AO Divergence"
            ]])
        print("✅ Google Sheets connected!")
        return True
    except Exception as e:
        print(f"❌ Sheets: {e}")
        return False

def log_to_gsheet(name, signal, price, sl, t1, t2, trend, ao_signal, ao_div):
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
            name, signal,
            round(price,2), round(sl,2),
            round(t1,2), round(t2,2),
            trend, ao_signal, ao_div
        ])
        print(f"✅ Logged {name} to Sheets!")
    except Exception as e:
        print(f"❌ Sheets log: {e}")


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
        print("✅ TG sent!" if r.status_code == 200 else f"❌ {r.text}")
    except Exception as e:
        print(f"❌ TG: {e}")

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%d-%b-%Y %I:%M %p IST")

def get_chart_link(tv_symbol):
    return f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={TV_INTERVAL}"

def trend_emoji(trend):
    if trend == "UPTREND":   return "📈 UPTREND (HH HL)"
    if trend == "DOWNTREND": return "📉 DOWNTREND (LH LL)"
    return "↔️ SIDEWAYS"

def ao_emoji(ao_signal):
    if ao_signal == "BULLISH": return "🟢 AO BULLISH"
    if ao_signal == "BEARISH": return "🔴 AO BEARISH"
    return "⚪ AO NEUTRAL"

def div_emoji(div):
    if div == "BULLISH_DIV": return "🔵 BULLISH DIVERGENCE"
    if div == "BEARISH_DIV": return "🟠 BEARISH DIVERGENCE"
    return "➖ No Divergence"

def trade_confidence(signal_type, trend, ao_signal, ao_div):
    score = 0
    if signal_type == "BUY":
        if trend == "UPTREND":        score += 2
        if ao_signal == "BULLISH":    score += 2
        if ao_div == "BULLISH_DIV":   score += 3
        if trend == "SIDEWAYS":       score += 1
    else:
        if trend == "DOWNTREND":      score += 2
        if ao_signal == "BEARISH":    score += 2
        if ao_div == "BEARISH_DIV":   score += 3
        if trend == "SIDEWAYS":       score += 1

    if score >= 6: return "🔥 VERY STRONG"
    if score >= 4: return "💪 STRONG"
    if score >= 2: return "👍 MODERATE"
    return "⚠️ WEAK — SKIP"

def alert_signal(stock, price, signal_type, trend, ao_signal, ao_div):
    sl    = price - stock['sl'] if signal_type == "BUY" else price + stock['sl']
    t1    = price + (stock['sl'] * TARGET1_RATIO) if signal_type == "BUY" else price - (stock['sl'] * TARGET1_RATIO)
    t2    = price + (stock['sl'] * TARGET2_RATIO) if signal_type == "BUY" else price - (stock['sl'] * TARGET2_RATIO)
    chart = get_chart_link(stock['tv'])
    emoji = "🟢" if signal_type == "BUY" else "🔴"
    arrow = "📈" if signal_type == "BUY" else "📉"
    conf  = trade_confidence(signal_type, trend, ao_signal, ao_div)

    bot_status['last_signal'] = f"{signal_type} {stock['name']} @ {price:.0f}"
    bot_status['total_signals'] += 1

    send_telegram(
        f"{emoji} <b>{signal_type} — {stock['name']}</b>\n\n"
        f"{arrow} Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{sl:.2f}</b>\n"
        f"🎯 Target1: <b>{t1:.2f}</b>\n"
        f"🎯 Target2: <b>{t2:.2f}</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 <b>Market Analysis:</b>\n"
        f"{trend_emoji(trend)}\n"
        f"{ao_emoji(ao_signal)}\n"
        f"{div_emoji(ao_div)}\n\n"
        f"🎯 <b>Confidence: {conf}</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"✅ HLC3/KAU Crossover\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}\n"
        f"⚠️ Paper trade first!"
    )
    log_to_gsheet(stock['name'], signal_type, price, sl, t1, t2, trend, ao_signal, ao_div)

def alert_startup():
    names = "\n".join([f"• {s['name']}" for s in STOCKS])
    send_telegram(
        f"🚀 <b>Multi Stock Bot Started!</b>\n\n"
        f"📊 Scanning {len(STOCKS)} stocks\n"
        f"🕐 {TRADE_START} – {TRADE_END} IST\n\n"
        f"✅ Combined Signals:\n"
        f"• HLC3/KAU Crossover\n"
        f"• Market Structure (HH/HL/LH/LL)\n"
        f"• Awesome Oscillator\n"
        f"• AO Divergence\n"
        f"• Confidence Score\n\n"
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
def fetch_data(symbol):
    try:
        df = yf.download(symbol, interval=INTERVAL, period="5d", progress=False)
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

def awesome_oscillator(df):
    mid = (df['High'] + df['Low']) / 2
    return mid.rolling(5).mean() - mid.rolling(34).mean()


# ──────────────────────────────────────────
#  📊 MARKET STRUCTURE
# ──────────────────────────────────────────
def detect_market_structure(df):
    highs = df['High'].values
    lows  = df['Low'].values
    n     = len(highs)
    lb    = SWING_LOOKBACK

    swing_highs = []
    swing_lows  = []

    for i in range(lb, n - lb):
        if highs[i] == max(highs[i-lb:i+lb+1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i-lb:i+lb+1]):
            swing_lows.append(lows[i])

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "SIDEWAYS"

    last_sh = swing_highs[-1]
    prev_sh = swing_highs[-2]
    last_sl = swing_lows[-1]
    prev_sl = swing_lows[-2]

    hh = last_sh > prev_sh
    hl = last_sl > prev_sl
    lh = last_sh < prev_sh
    ll = last_sl < prev_sl

    if hh and hl:   return "UPTREND"
    elif lh and ll: return "DOWNTREND"
    else:           return "SIDEWAYS"


# ──────────────────────────────────────────
#  📊 AWESOME OSCILLATOR ANALYSIS
# ──────────────────────────────────────────
def analyze_ao(df):
    ao = awesome_oscillator(df)
    df = df.copy()
    df['ao'] = ao
    df_clean = df.dropna(subset=['ao'])

    if len(df_clean) < 5:
        return "NEUTRAL", "NO_DIV"

    ao_v  = df_clean['ao'].values
    cl    = df_clean['Close'].values

    # ── AO Signal ──
    ao_signal = "NEUTRAL"
    if len(ao_v) >= 2:
        # Cross above zero = bullish
        if ao_v[-1] > 0 and ao_v[-2] <= 0:
            ao_signal = "BULLISH"
        # Cross below zero = bearish
        elif ao_v[-1] < 0 and ao_v[-2] >= 0:
            ao_signal = "BEARISH"
        # Saucer bullish: above zero, dip then rise
        elif (len(ao_v) >= 3 and ao_v[-1] > 0 and
              ao_v[-2] > 0 and ao_v[-3] > 0 and
              ao_v[-1] > ao_v[-2] < ao_v[-3]):
            ao_signal = "BULLISH"
        # Saucer bearish: below zero, rise then fall
        elif (len(ao_v) >= 3 and ao_v[-1] < 0 and
              ao_v[-2] < 0 and ao_v[-3] < 0 and
              ao_v[-1] < ao_v[-2] > ao_v[-3]):
            ao_signal = "BEARISH"

    # ── AO Divergence ──
    ao_div = "NO_DIV"
    lookback = min(30, len(cl) - 1)
    rc = cl[-lookback:]
    ra = ao_v[-lookback:]

    # Find price swing lows and highs
    p_lows  = [i for i in range(1, len(rc)-1)
               if rc[i] < rc[i-1] and rc[i] < rc[i+1]]
    p_highs = [i for i in range(1, len(rc)-1)
               if rc[i] > rc[i-1] and rc[i] > rc[i+1]]

    # Bullish divergence: price lower low but AO higher low
    if len(p_lows) >= 2:
        pl1, pl2 = p_lows[-2], p_lows[-1]
        if rc[pl2] < rc[pl1] and ra[pl2] > ra[pl1]:
            ao_div = "BULLISH_DIV"

    # Bearish divergence: price higher high but AO lower high
    if len(p_highs) >= 2:
        ph1, ph2 = p_highs[-2], p_highs[-1]
        if rc[ph2] > rc[ph1] and ra[ph2] < ra[ph1]:
            ao_div = "BEARISH_DIV"

    return ao_signal, ao_div


# ──────────────────────────────────────────
#  🔬 BUILD HLC3/KAU SIGNALS
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
#  🔄 SCAN EACH STOCK
# ──────────────────────────────────────────
last_alerts = {}

def scan_stock(stock):
    symbol = stock['symbol']
    name   = stock['name']
    try:
        df  = fetch_data(symbol)
        d4h = fetch_htf(symbol)

        if df is None or d4h is None:
            print(f"⚠️ {name}: No data")
            return
        if len(df) < 40:
            print(f"⚠️ {name}: Not enough data")
            return

        # Build HLC3/KAU signals
        df = build(df, d4h)
        last = df.iloc[-2]
        ct   = str(df.index[-2])

        print(f"  {name}: Close:{last['Close']:.2f} BUY:{last['buy']} SELL:{last['sell']}")

        # Skip if already alerted this candle
        if last_alerts.get(symbol) == ct:
            return

        # Check for signal
        if not last['buy'] and not last['sell']:
            return

        signal_type = "BUY" if last['buy'] else "SELL"

        # Market structure analysis
        trend = detect_market_structure(df)

        # AO analysis
        ao_signal, ao_div = analyze_ao(df)

        print(f"  ✅ {signal_type} — {name} | Trend:{trend} AO:{ao_signal} Div:{ao_div}")

        # Send combined alert
        alert_signal(stock, last['Close'], signal_type, trend, ao_signal, ao_div)
        last_alerts[symbol] = ct

    except Exception as e:
        print(f"❌ {name}: {e}")


# ──────────────────────────────────────────
#  🔄 MAIN LOOP
# ──────────────────────────────────────────
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
        time.sleep(2)

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
