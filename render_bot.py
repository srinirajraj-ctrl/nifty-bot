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
    {"symbol": "^NSEI",         "name": "NIFTY 50",       "tv": "NSE:NIFTY"},
    {"symbol": "^NSEBANK",      "name": "BANK NIFTY",     "tv": "NSE:BANKNIFTY"},
    {"symbol": "SBIN.NS",       "name": "SBIN",           "tv": "NSE:SBIN"},
    {"symbol": "IDEA.NS",       "name": "IDEA",           "tv": "NSE:IDEA"},
    {"symbol": "YESBANK.NS",    "name": "YES BANK",       "tv": "NSE:YESBANK"},
    {"symbol": "SAIL.NS",       "name": "SAIL",           "tv": "NSE:SAIL"},
    {"symbol": "NHPC.NS",       "name": "NHPC",           "tv": "NSE:NHPC"},
    {"symbol": "IRFC.NS",       "name": "IRFC",           "tv": "NSE:IRFC"},
    {"symbol": "PNB.NS",        "name": "PNB",            "tv": "NSE:PNB"},
    {"symbol": "BANKBARODA.NS", "name": "BANK OF BARODA", "tv": "NSE:BANKBARODA"},
    {"symbol": "SUZLON.NS",     "name": "SUZLON",         "tv": "NSE:SUZLON"},
    {"symbol": "HFCL.NS",       "name": "HFCL",           "tv": "NSE:HFCL"},
    {"symbol": "TRIDENT.NS",    "name": "TRIDENT",        "tv": "NSE:TRIDENT"},
    {"symbol": "JPPOWER.NS",    "name": "JP POWER",       "tv": "NSE:JPPOWER"},
    {"symbol": "DISHTV.NS",     "name": "DISH TV",        "tv": "NSE:DISHTV"},
    {"symbol": "ITI.NS",        "name": "ITI",            "tv": "NSE:ITI"},
    {"symbol": "RVNL.NS",       "name": "RVNL",           "tv": "NSE:RVNL"},
    {"symbol": "NALCO.NS",      "name": "NALCO",          "tv": "NSE:NALCO"},
    {"symbol": "NMDC.NS",       "name": "NMDC",           "tv": "NSE:NMDC"},
    {"symbol": "HINDCOPPER.NS", "name": "HIND COPPER",    "tv": "NSE:HINDCOPPER"},
    {"symbol": "CENTRALBK.NS",  "name": "CENTRAL BANK",   "tv": "NSE:CENTRALBK"},
    {"symbol": "BEML.NS",       "name": "BEML",           "tv": "NSE:BEML"},
    {"symbol": "ABCAPITAL.NS",  "name": "AB CAPITAL",     "tv": "NSE:ABCAPITAL"},
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
ATR_PERIOD      = 14
ATR_MULTIPLIER  = 1.5

# ── KEY CHANGES ──
TRADE_START    = "10:00"   # Changed from 9:15 — avoid opening volatility
TRADE_END      = "15:30"
SWING_LOOKBACK = 5

bot_status = {
    "last_check"    : "Not started",
    "last_signal"   : "None",
    "total_signals" : 0,
    "wins"          : 0,
    "losses"        : 0,
    "active_trades" : 0,
    "skipped_ao"    : 0,   # Count of AO filtered signals
}

active_trades      = {}
active_trades_lock = threading.Lock()


# ──────────────────────────────────────────
#  🌐 WEB SERVER
# ──────────────────────────────────────────
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
            <title>#HLC3KAU Bot</title>
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
            <h1>&#x1F4CA; #HLC3KAU Bot</h1>
            <div class="card">
                <p>&#x23F1; <b>Timeframe:</b> {INTERVAL}</p>
                <p>&#x1F557; <b>Hours:</b> {TRADE_START} - {TRADE_END} IST</p>
                <p>&#x26A0; <b>Opening filter:</b> Skip 9:15-10:00 AM</p>
                <p>&#x1F4CA; <b>Stocks:</b> {len(STOCKS)}</p>
                <p>&#x1F6E1; <b>SL:</b> ATR {ATR_MULTIPLIER}x + bsma Trail</p>
            </div>
            <div class="card">
                <p>&#x1F504; <b>Last Check:</b> {bot_status['last_check']}</p>
                <p>&#x1F3AF; <b>Last Signal:</b> <span class="green">{bot_status['last_signal']}</span></p>
                <p>&#x1F4E8; <b>Total Signals:</b> {bot_status['total_signals']}</p>
                <p>&#x1F6AB; <b>AO Filtered:</b> {bot_status['skipped_ao']}</p>
                <p class="green">&#x2705; <b>Wins:</b> {bot_status['wins']}</p>
                <p class="red">&#x274C; <b>Losses:</b> {bot_status['losses']}</p>
                <p>&#x1F3C6; <b>Win Rate:</b> {win_rate}%</p>
            </div>
            <div class="card">
                <p class="yellow">&#x1F4B0; <b>Active Trades:</b></p>
                <ul>{active_list}</ul>
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
        scopes     = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds         = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gsheet_client = gspread.authorize(creds)
        sh = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.sheet1
        if ws.cell(1,1).value != "Date":
            ws.update('A1:R1', [[
                "Date","Time","Stock","Signal","Entry",
                "ATR","Hard SL","Trail SL","T1","T2",
                "RR","Trend","AO Signal","AO Div",
                "Confidence","Exit Price","P&L","Result"
            ]])
        print("✅ Google Sheets connected!")
        return True
    except Exception as e:
        print(f"❌ Sheets: {e}")
        return False

def log_to_gsheet(name, signal, price, atr, hard_sl, trail_sl, t1, t2, rr, trend, ao_signal, ao_div, confidence):
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
            round(price,2), round(atr,2),
            round(hard_sl,2), round(trail_sl,2),
            round(t1,2), round(t2,2),
            rr, trend, ao_signal, ao_div, confidence,
            "", "", "MONITORING"
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
        ws.update_cell(row_num, 16, round(exit_price, 2))
        ws.update_cell(row_num, 17, round(pnl, 2))
        ws.update_cell(row_num, 18, result)
        print(f"✅ Updated outcome row {row_num}: {result}")
    except Exception as e:
        print(f"❌ Outcome update: {e}")


# ──────────────────────────────────────────
#  📡 TELEGRAM
# ──────────────────────────────────────────
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

def get_ist_time_short():
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%I:%M %p")

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
        if trend == "UPTREND":      score += 2
        if ao_signal == "BULLISH":  score += 2
        if ao_div == "BULLISH_DIV": score += 3
        if trend == "SIDEWAYS":     score += 1
    else:
        if trend == "DOWNTREND":    score += 2
        if ao_signal == "BEARISH":  score += 2
        if ao_div == "BEARISH_DIV": score += 3
        if trend == "SIDEWAYS":     score += 1
    if score >= 6: return "🔥 VERY STRONG"
    if score >= 4: return "💪 STRONG"
    if score >= 2: return "👍 MODERATE"
    return "⚠️ WEAK — SKIP"

def ao_contradicts(signal_type, ao_signal):
    """
    Returns True if AO directly contradicts the signal direction.
    BUY + AO BEARISH = contradiction
    SELL + AO BULLISH = contradiction
    NEUTRAL = no contradiction
    """
    if signal_type == "BUY"  and ao_signal == "BEARISH": return True
    if signal_type == "SELL" and ao_signal == "BULLISH": return True
    return False

def alert_signal(stock, price, signal_type, atr, hard_sl, trail_sl, t1, t2, trend, ao_signal, ao_div):
    chart  = get_chart_link(stock['tv'])
    emoji  = "🟢" if signal_type == "BUY" else "🔴"
    arrow  = "📈" if signal_type == "BUY" else "📉"
    conf   = trade_confidence(signal_type, trend, ao_signal, ao_div)
    sl_pts = round(abs(price - hard_sl), 2)
    t1_pts = round(abs(price - t1), 2)
    t2_pts = round(abs(price - t2), 2)
    rr     = f"1:{round(t1_pts/sl_pts,1)} / 1:{round(t2_pts/sl_pts,1)}" if sl_pts > 0 else "N/A"

    bot_status['last_signal'] = f"{signal_type} {stock['name']} @ {price:.0f}"
    bot_status['total_signals'] += 1

    send_telegram(
        f"📊 <b>#HLC3KAU Signal</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{signal_type} — {stock['name']}</b>\n\n"
        f"{arrow} Entry     : <b>{price:.2f}</b>\n\n"
        f"🛡 <b>Stop Loss:</b>\n"
        f"🔴 Hard SL  : <b>{hard_sl:.2f}</b>  ({sl_pts} pts)\n"
        f"   Place in broker NOW!\n"
        f"📉 Trail SL : <b>{trail_sl:.2f}</b>  (red line)\n"
        f"   Watch on TradingView\n\n"
        f"🎯 <b>Targets:</b>\n"
        f"T1 : <b>{t1:.2f}</b>  ({t1_pts} pts) — book 50%\n"
        f"T2 : <b>{t2:.2f}</b>  ({t2_pts} pts) — book rest\n\n"
        f"📊 RR = {rr}\n"
        f"📐 ATR({ATR_PERIOD}) = {atr:.2f}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 <b>Market Analysis:</b>\n"
        f"{trend_emoji(trend)}\n"
        f"{ao_emoji(ao_signal)}\n"
        f"{div_emoji(ao_div)}\n\n"
        f"🎯 <b>Confidence: {conf}</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"👁 Monitoring live...\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}\n"
        f"⚠️ Paper trade first!"
    )

    row_num = log_to_gsheet(
        stock['name'], signal_type, price, atr,
        hard_sl, trail_sl, t1, t2, rr,
        trend, ao_signal, ao_div, conf
    )

    with active_trades_lock:
        active_trades[stock['symbol']] = {
            "name"     : stock['name'],
            "signal"   : signal_type,
            "entry"    : price,
            "hard_sl"  : hard_sl,
            "trail_sl" : trail_sl,
            "t1"       : t1,
            "t2"       : t2,
            "t1_hit"   : False,
            "row"      : row_num,
            "symbol"   : stock['symbol'],
        }
        bot_status['active_trades'] = len(active_trades)
    print(f"👁 Monitoring {stock['name']} live!")

def alert_startup():
    names = "\n".join([f"• {s['name']}" for s in STOCKS])
    send_telegram(
        f"📊 <b>#HLC3KAU Bot Started!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 Scanning {len(STOCKS)} stocks\n"
        f"🕐 {TRADE_START} – {TRADE_END} IST\n\n"
        f"✅ Active Filters:\n"
        f"• HLC3/KAU Crossover\n"
        f"• Trend filter (UPTREND/DOWNTREND only)\n"
        f"• AO confirmation (no contradiction)\n"
        f"• ATR {ATR_MULTIPLIER}x Hard SL\n"
        f"• bsma Trail SL\n"
        f"• Opening filter (skip 9:15-10:00 AM)\n"
        f"• Live Trade Monitoring\n\n"
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
    start  = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end    = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


# ──────────────────────────────────────────
#  📦 DATA FETCH
# ──────────────────────────────────────────
def fetch_data(symbol):
    for attempt in range(3):
        try:
            df = yf.download(symbol, interval=INTERVAL, period="5d", progress=False)
            if df.empty:
                return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df[['Open','High','Low','Close','Volume']].dropna()
            return df
        except Exception as e:
            print(f"⚠️ {symbol} attempt {attempt+1}: {e}")
            time.sleep(5)
    return None

def fetch_htf(symbol):
    for attempt in range(3):
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
            print(f"⚠️ HTF {symbol} attempt {attempt+1}: {e}")
            time.sleep(5)
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

def calculate_atr(df, period=14):
    high  = df['High']
    low   = df['Low']
    close = df['Close']
    tr    = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def awesome_oscillator(df):
    mid = (df['High'] + df['Low']) / 2
    return mid.rolling(5).mean() - mid.rolling(34).mean()


# ──────────────────────────────────────────
#  📊 MARKET STRUCTURE
# ──────────────────────────────────────────
def detect_market_structure(df):
    highs       = df['High'].values
    lows        = df['Low'].values
    n           = len(highs)
    lb          = SWING_LOOKBACK
    swing_highs = []
    swing_lows  = []
    for i in range(lb, n - lb):
        if highs[i] == max(highs[i-lb:i+lb+1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i-lb:i+lb+1]):
            swing_lows.append(lows[i])
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "SIDEWAYS"
    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1]  > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1]  < swing_lows[-2]
    if hh and hl:   return "UPTREND"
    elif lh and ll: return "DOWNTREND"
    else:           return "SIDEWAYS"


# ──────────────────────────────────────────
#  📊 AO ANALYSIS
# ──────────────────────────────────────────
def analyze_ao(df):
    ao       = awesome_oscillator(df)
    df       = df.copy()
    df['ao'] = ao
    df_clean = df.dropna(subset=['ao'])
    if len(df_clean) < 5:
        return "NEUTRAL", "NO_DIV"
    ao_v = df_clean['ao'].values
    cl   = df_clean['Close'].values
    ao_signal = "NEUTRAL"
    if len(ao_v) >= 2:
        if ao_v[-1] > 0 and ao_v[-2] <= 0:
            ao_signal = "BULLISH"
        elif ao_v[-1] < 0 and ao_v[-2] >= 0:
            ao_signal = "BEARISH"
        elif (len(ao_v) >= 3 and ao_v[-1] > 0 and ao_v[-2] > 0 and ao_v[-3] > 0 and
              ao_v[-1] > ao_v[-2] < ao_v[-3]):
            ao_signal = "BULLISH"
        elif (len(ao_v) >= 3 and ao_v[-1] < 0 and ao_v[-2] < 0 and ao_v[-3] < 0 and
              ao_v[-1] < ao_v[-2] > ao_v[-3]):
            ao_signal = "BEARISH"
    ao_div   = "NO_DIV"
    lookback = min(30, len(cl) - 1)
    rc = cl[-lookback:]
    ra = ao_v[-lookback:]
    p_lows  = [i for i in range(1, len(rc)-1) if rc[i] < rc[i-1] and rc[i] < rc[i+1]]
    p_highs = [i for i in range(1, len(rc)-1) if rc[i] > rc[i-1] and rc[i] > rc[i+1]]
    if len(p_lows) >= 2:
        pl1, pl2 = p_lows[-2], p_lows[-1]
        if rc[pl2] < rc[pl1] and ra[pl2] > ra[pl1]:
            ao_div = "BULLISH_DIV"
    if len(p_highs) >= 2:
        ph1, ph2 = p_highs[-2], p_highs[-1]
        if rc[ph2] > rc[ph1] and ra[ph2] < ra[ph1]:
            ao_div = "BEARISH_DIV"
    return ao_signal, ao_div


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
#  👁 LIVE TRADE MONITOR
# ──────────────────────────────────────────
def monitor_trades():
    while True:
        try:
            with active_trades_lock:
                symbols = list(active_trades.keys())
            market_closed = not is_trading_time()
            for symbol in symbols:
                with active_trades_lock:
                    if symbol not in active_trades:
                        continue
                    trade = active_trades[symbol].copy()
                price = get_current_price(symbol)
                if price is None:
                    continue
                name    = trade['name']
                signal  = trade['signal']
                entry   = trade['entry']
                hard_sl = trade['hard_sl']
                t1      = trade['t1']
                t2      = trade['t2']
                t1_hit  = trade['t1_hit']
                row     = trade['row']
                result     = None
                exit_price = price
                if signal == "BUY":
                    pnl = price - entry
                    if price >= t2:
                        result = "✅ WIN T2"
                        bot_status['wins'] += 1
                    elif price >= t1 and not t1_hit:
                        send_telegram(
                            f"📊 <b>#HLC3KAU T1 Hit</b>\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"🎯 <b>T1 HIT — {name}</b>\n\n"
                            f"Signal : BUY\n"
                            f"Entry  : {entry:.2f}\n"
                            f"T1 Hit : {price:.2f}\n"
                            f"P&L    : +{pnl:.2f} pts\n\n"
                            f"✅ Book 50% now!\n"
                            f"Move Hard SL to breakeven\n"
                            f"Watch Trail SL for rest\n\n"
                            f"⏰ {get_ist_time()}"
                        )
                        with active_trades_lock:
                            if symbol in active_trades:
                                active_trades[symbol]['t1_hit'] = True
                        continue
                    elif price <= hard_sl:
                        result = "❌ LOSS SL"
                        pnl    = price - entry
                        bot_status['losses'] += 1
                    elif market_closed:
                        result = "🔔 CLOSED EOD"
                        pnl    = price - entry
                else:
                    pnl = entry - price
                    if price <= t2:
                        result = "✅ WIN T2"
                        bot_status['wins'] += 1
                    elif price <= t1 and not t1_hit:
                        send_telegram(
                            f"📊 <b>#HLC3KAU T1 Hit</b>\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"🎯 <b>T1 HIT — {name}</b>\n\n"
                            f"Signal : SELL\n"
                            f"Entry  : {entry:.2f}\n"
                            f"T1 Hit : {price:.2f}\n"
                            f"P&L    : +{pnl:.2f} pts\n\n"
                            f"✅ Book 50% now!\n"
                            f"Move Hard SL to breakeven\n"
                            f"Watch Trail SL for rest\n\n"
                            f"⏰ {get_ist_time()}"
                        )
                        with active_trades_lock:
                            if symbol in active_trades:
                                active_trades[symbol]['t1_hit'] = True
                        continue
                    elif price >= hard_sl:
                        result = "❌ LOSS SL"
                        pnl    = entry - price
                        bot_status['losses'] += 1
                    elif market_closed:
                        result = "🔔 CLOSED EOD"
                        pnl    = entry - price
                if result:
                    emoji = "✅" if "WIN" in result else "❌" if "LOSS" in result else "🔔"
                    send_telegram(
                        f"📊 <b>#HLC3KAU Outcome</b>\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{emoji} <b>OUTCOME — {name}</b>\n\n"
                        f"Signal : {signal}\n"
                        f"Entry  : {entry:.2f}\n"
                        f"Exit   : {exit_price:.2f}\n"
                        f"P&L    : {pnl:+.2f} pts\n\n"
                        f"Result : <b>{result}</b>\n\n"
                        f"⏰ {get_ist_time()}"
                    )
                    update_outcome(row, exit_price, pnl, result)
                    with active_trades_lock:
                        active_trades.pop(symbol, None)
                        bot_status['active_trades'] = len(active_trades)
                    print(f"✅ Closed: {name} {result} P&L:{pnl:.2f}")
                time.sleep(3)
        except Exception as e:
            print(f"❌ Monitor error: {e}")
        time.sleep(60)


# ──────────────────────────────────────────
#  🔄 SCAN EACH STOCK
# ──────────────────────────────────────────
last_alerts = {}

def scan_stock(stock):
    symbol = stock['symbol']
    name   = stock['name']
    try:
        with active_trades_lock:
            if symbol in active_trades:
                return
        df  = fetch_data(symbol)
        d4h = fetch_htf(symbol)
        if df is None or d4h is None:
            return
        if len(df) < 40:
            return
        df   = build(df, d4h)
        last = df.iloc[-2]
        ct   = str(df.index[-2])
        print(f"  {name}: {last['Close']:.2f} BUY:{last['buy']} SELL:{last['sell']}")
        if last_alerts.get(symbol) == ct:
            return
        if not last['buy'] and not last['sell']:
            return

        signal_type = "BUY" if last['buy'] else "SELL"
        price       = float(last['Close'])
        bsma_val    = float(last['bsma'])
        atr         = calculate_atr(df, ATR_PERIOD)
        sl_dist     = ATR_MULTIPLIER * atr

        if signal_type == "BUY":
            hard_sl  = round(price - sl_dist, 2)
            trail_sl = round(bsma_val, 2)
            t1       = round(price + sl_dist * TARGET1_RATIO, 2)
            t2       = round(price + sl_dist * TARGET2_RATIO, 2)
        else:
            hard_sl  = round(price + sl_dist, 2)
            trail_sl = round(bsma_val, 2)
            t1       = round(price - sl_dist * TARGET1_RATIO, 2)
            t2       = round(price - sl_dist * TARGET2_RATIO, 2)

        trend             = detect_market_structure(df)
        ao_signal, ao_div = analyze_ao(df)

        # ── FILTER 1: Skip SIDEWAYS ──
        if trend == "SIDEWAYS":
            print(f"  ⏭ {name}: Skipped — SIDEWAYS market")
            last_alerts[symbol] = ct
            return

        # ── FILTER 2: Skip if AO contradicts signal ──
        if ao_contradicts(signal_type, ao_signal):
            print(f"  ⏭ {name}: Skipped — AO contradicts signal")
            bot_status['skipped_ao'] += 1
            last_alerts[symbol] = ct
            return

        print(f"  ✅ {signal_type} {name} | {trend} | AO:{ao_signal} | T1:{t1} T2:{t2}")
        alert_signal(stock, price, signal_type, atr, hard_sl, trail_sl, t1, t2, trend, ao_signal, ao_div)
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
        print("⏸  Outside trading hours (10:00 AM - 3:30 PM).")
        return
    print(f"Scanning {len(STOCKS)} stocks...")
    for stock in STOCKS:
        scan_stock(stock)
        time.sleep(4)

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
    monitor_thread = threading.Thread(target=monitor_trades)
    monitor_thread.daemon = True
    monitor_thread.start()
    bot_thread = threading.Thread(target=bot_loop)
    bot_thread.daemon = True
    bot_thread.start()
    init_gsheet()
    run_web_server()
