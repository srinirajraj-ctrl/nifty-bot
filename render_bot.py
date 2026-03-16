import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import pytz
import os
import json
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────
#  ⚙️ CREDENTIALS — Set in Render Environment
# ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Google Sheets settings
# SHEET_ID = your Google Sheet ID from URL
# Example: https://docs.google.com/spreadsheets/d/SHEET_ID/edit
GOOGLE_SHEET_ID    = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_NAME  = "Alerts"  # Sheet tab name

# Google Service Account credentials JSON (paste as environment variable)
GOOGLE_CREDS_JSON  = os.environ.get("GOOGLE_CREDS_JSON", "")

SYMBOL       = "^NSEI"
SYMBOL_NAME  = "NIFTY 50"
TV_SYMBOL    = "NSE:NIFTY"   # TradingView symbol
INTERVAL     = "5m"
TV_INTERVAL  = "5"           # TradingView interval

HLC3_SHIFT      = 1
SLOW_EMA_PERIOD = 20
KAMA_LENGTH     = 5
KAMA_FASTEND    = 2.5
KAMA_SLOWEND    = 20

EMA_PERIOD   = 200
RSI_PERIOD   = 14
RSI_BUY_MIN  = 50
RSI_BUY_MAX  = 70
RSI_SELL_MIN = 30
RSI_SELL_MAX = 50

STOP_LOSS_PTS = 20
TARGET1_RATIO = 1.5
TARGET2_RATIO = 2.0

TRADE_START = "10:00"
TRADE_END   = "14:30"


# ──────────────────────────────────────────
#  📊 GOOGLE SHEETS
# ──────────────────────────────────────────
gsheet_client = None

def init_gsheet():
    """Initialize Google Sheets client."""
    global gsheet_client
    if not GOOGLE_CREDS_JSON or not GOOGLE_SHEET_ID:
        print("⚠️ Google Sheets not configured — skipping")
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
        print("✅ Google Sheets connected!")
        # Create header if sheet is empty
        sh = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws = sh.worksheet(GOOGLE_SHEET_NAME)
        if ws.row_count < 2 or ws.cell(1,1).value != "Date":
            ws.update('A1:K1', [[
                "Date", "Time", "Signal", "Entry",
                "Stop Loss", "Target1", "Target2",
                "VWAP", "EMA200", "RSI", "Chart Link"
            ]])
            ws.format('A1:K1', {"textFormat": {"bold": True}})
        return True
    except Exception as e:
        print(f"❌ Google Sheets init error: {e}")
        return False

def log_to_gsheet(signal, price, sl, t1, t2, vwap, ema200, rsi, chart_link):
    """Log alert to Google Sheet."""
    if not gsheet_client:
        return
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        sh  = gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        ws  = sh.worksheet(GOOGLE_SHEET_NAME)
        ws.append_row([
            now.strftime("%d-%b-%Y"),
            now.strftime("%I:%M %p"),
            signal,
            round(price, 2),
            round(sl, 2),
            round(t1, 2),
            round(t2, 2),
            round(vwap, 2),
            round(ema200, 2),
            round(rsi, 1),
            chart_link
        ])
        print(f"✅ Logged to Google Sheets!")
    except Exception as e:
        print(f"❌ Sheets log error: {e}")


# ──────────────────────────────────────────
#  📈 TRADINGVIEW CHART LINK
# ──────────────────────────────────────────
def get_chart_link():
    """Generate TradingView chart link for current symbol."""
    return f"https://www.tradingview.com/chart/?symbol={TV_SYMBOL}&interval={TV_INTERVAL}"


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

def alert_buy(price, reasons, vwap, ema200, rsi):
    sl  = price - STOP_LOSS_PTS
    t1  = price + (STOP_LOSS_PTS * TARGET1_RATIO)
    t2  = price + (STOP_LOSS_PTS * TARGET2_RATIO)
    chart = get_chart_link()
    send_telegram(
        f"🟢 <b>BUY — {SYMBOL_NAME}</b>\n\n"
        f"📈 Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{sl:.2f}</b>  (-{STOP_LOSS_PTS} pts)\n"
        f"🎯 Target1: <b>{t1:.2f}</b>  (+{STOP_LOSS_PTS * TARGET1_RATIO:.0f} pts)\n"
        f"🎯 Target2: <b>{t2:.2f}</b>  (+{STOP_LOSS_PTS * TARGET2_RATIO:.0f} pts)\n\n"
        f"✅ Filters:\n{reasons}\n\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}\n"
        f"⚠️ Paper trade first!"
    )
    log_to_gsheet("BUY", price, sl, t1, t2, vwap, ema200, rsi, chart)

def alert_sell(price, reasons, vwap, ema200, rsi):
    sl  = price + STOP_LOSS_PTS
    t1  = price - (STOP_LOSS_PTS * TARGET1_RATIO)
    t2  = price - (STOP_LOSS_PTS * TARGET2_RATIO)
    chart = get_chart_link()
    send_telegram(
        f"🔴 <b>SELL — {SYMBOL_NAME}</b>\n\n"
        f"📉 Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{sl:.2f}</b>  (+{STOP_LOSS_PTS} pts)\n"
        f"🎯 Target1: <b>{t1:.2f}</b>  (-{STOP_LOSS_PTS * TARGET1_RATIO:.0f} pts)\n"
        f"🎯 Target2: <b>{t2:.2f}</b>  (-{STOP_LOSS_PTS * TARGET2_RATIO:.0f} pts)\n\n"
        f"✅ Filters:\n{reasons}\n\n"
        f"📊 <a href='{chart}'>Open TradingView Chart</a>\n\n"
        f"⏰ {get_ist_time()}\n"
        f"⚠️ Paper trade first!"
    )
    log_to_gsheet("SELL", price, sl, t1, t2, vwap, ema200, rsi, chart)

def alert_skip(signal, reason):
    send_telegram(
        f"⚠️ <b>SKIPPED {signal} — {SYMBOL_NAME}</b>\n"
        f"{reason}\n"
        f"📊 <a href='{get_chart_link()}'>Open Chart</a>\n"
        f"⏰ {get_ist_time()}"
    )

def alert_startup():
    send_telegram(
        f"🚀 <b>Bot Started — 24/7 Auto!</b>\n\n"
        f"📊 {SYMBOL_NAME} | {INTERVAL}\n"
        f"🕐 {TRADE_START} – {TRADE_END} IST\n"
        f"✅ HLC3/KAU + 200EMA + VWAP + RSI\n"
        f"📊 <a href='{get_chart_link()}'>Open TradingView Chart</a>\n\n"
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
        print(f"✅ {len(df)} candles | Close: {df['Close'].iloc[-1]:.2f}")
        return df
    except Exception as e:
        print(f"❌ {e}")
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
        print(f"❌ HTF: {e}")
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

def rsi_calc(series, n=14):
    d  = series.diff()
    ag = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    al = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    return 100 - 100 / (1 + ag / al)

def vwap_calc(df):
    df = df.copy()
    df['hlc3']    = (df['High'] + df['Low'] + df['Close']) / 3
    df['tpv']     = df['hlc3'] * df['Volume']
    df['cum_tpv'] = df['tpv'].cumsum()
    df['cum_vol'] = df['Volume'].cumsum()
    return df['cum_tpv'] / df['cum_vol']


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
    df['ema200']   = ema(df['Close'], EMA_PERIOD)
    df['rsi']      = rsi_calc(df['Close'], RSI_PERIOD)
    df['vwap']     = vwap_calc(df)
    return df


# ──────────────────────────────────────────
#  🔍 FILTER CHECKS
# ──────────────────────────────────────────
def check_buy(row):
    p, f = [], []
    (p if row['Close'] > row['vwap']   else f).append(f"{'✅' if row['Close'] > row['vwap']   else '❌'} VWAP {row['vwap']:.0f}")
    (p if row['Close'] > row['ema200'] else f).append(f"{'✅' if row['Close'] > row['ema200'] else '❌'} 200 EMA {row['ema200']:.0f}")
    ok = RSI_BUY_MIN <= row['rsi'] <= RSI_BUY_MAX
    (p if ok else f).append(f"{'✅' if ok else '❌'} RSI {row['rsi']:.1f}")
    return len(f) == 0, "\n".join(p + f)

def check_sell(row):
    p, f = [], []
    (p if row['Close'] < row['vwap']   else f).append(f"{'✅' if row['Close'] < row['vwap']   else '❌'} VWAP {row['vwap']:.0f}")
    (p if row['Close'] < row['ema200'] else f).append(f"{'✅' if row['Close'] < row['ema200'] else '❌'} 200 EMA {row['ema200']:.0f}")
    ok = RSI_SELL_MIN <= row['rsi'] <= RSI_SELL_MAX
    (p if ok else f).append(f"{'✅' if ok else '❌'} RSI {row['rsi']:.1f}")
    return len(f) == 0, "\n".join(p + f)


# ──────────────────────────────────────────
#  🔄 STRATEGY LOOP
# ──────────────────────────────────────────
last_alert = {"time": None}

def run_strategy():
    print(f"\n{'='*40}\n🔄 {get_ist_time()}")
    if not is_trading_time():
        print("⏸  Outside trading hours.")
        return
    df  = fetch_data(SYMBOL, INTERVAL, "5d")
    d4h = fetch_htf(SYMBOL)
    if df is None or d4h is None:
        print("❌ Data error")
        return
    if len(df) < EMA_PERIOD + 10:
        print("❌ Not enough data")
        return
    df   = build(df, d4h)
    last = df.iloc[-2]
    ct   = str(df.index[-2])
    print(f"Close:{last['Close']:.0f} VWAP:{last['vwap']:.0f} EMA:{last['ema200']:.0f} RSI:{last['rsi']:.1f}")
    print(f"BUY:{last['buy']} SELL:{last['sell']}")
    if last_alert["time"] == ct:
        print("ℹ️  Already sent for this candle.")
        return
    if last['buy']:
        ok, reasons = check_buy(last)
        if ok:
            alert_buy(last['Close'], reasons, last['vwap'], last['ema200'], last['rsi'])
        else:
            alert_skip("BUY", reasons)
        last_alert["time"] = ct
    elif last['sell']:
        ok, reasons = check_sell(last)
        if ok:
            alert_sell(last['Close'], reasons, last['vwap'], last['ema200'], last['rsi'])
        else:
            alert_skip("SELL", reasons)
        last_alert["time"] = ct
    else:
        print("😴 No signal.")


# ──────────────────────────────────────────
#  ▶️ START
# ──────────────────────────────────────────
if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set!")
elif not TELEGRAM_CHAT_ID:
    print("❌ TELEGRAM_CHAT_ID not set!")
else:
    print("🚀 Bot starting...")
    init_gsheet()
    alert_startup()
    while True:
        try:
            run_strategy()
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(60)
