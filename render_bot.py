import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import pytz
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────
#  ⚙️ FILL THESE IN
# ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID_HERE"

SYMBOL       = "^NSEI"
SYMBOL_NAME  = "NIFTY 50"
INTERVAL     = "5m"

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


# ── Telegram ──
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        print("✅ Telegram sent!" if r.status_code == 200 else f"❌ {r.text}")
    except Exception as e:
        print(f"❌ {e}")

def get_ist_time():
    return datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%d-%b-%Y %I:%M %p IST")

def alert_buy(price, reasons):
    send_telegram(
        f"🟢 <b>BUY — {SYMBOL_NAME}</b>\n\n"
        f"📈 Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{price - STOP_LOSS_PTS:.2f}</b>\n"
        f"🎯 Target1: <b>{price + STOP_LOSS_PTS * TARGET1_RATIO:.2f}</b>\n"
        f"🎯 Target2: <b>{price + STOP_LOSS_PTS * TARGET2_RATIO:.2f}</b>\n\n"
        f"✅ Filters:\n{reasons}\n\n"
        f"⏰ {get_ist_time()}\n⚠️ Paper trade first!"
    )

def alert_sell(price, reasons):
    send_telegram(
        f"🔴 <b>SELL — {SYMBOL_NAME}</b>\n\n"
        f"📉 Entry  : <b>{price:.2f}</b>\n"
        f"🛑 SL     : <b>{price + STOP_LOSS_PTS:.2f}</b>\n"
        f"🎯 Target1: <b>{price - STOP_LOSS_PTS * TARGET1_RATIO:.2f}</b>\n"
        f"🎯 Target2: <b>{price - STOP_LOSS_PTS * TARGET2_RATIO:.2f}</b>\n\n"
        f"✅ Filters:\n{reasons}\n\n"
        f"⏰ {get_ist_time()}\n⚠️ Paper trade first!"
    )

def alert_skip(signal, reason):
    send_telegram(f"⚠️ <b>SKIPPED {signal} — {SYMBOL_NAME}</b>\n{reason}\n⏰ {get_ist_time()}")

def alert_startup():
    send_telegram(
        f"🚀 <b>Bot Started on Render!</b>\n\n"
        f"📊 {SYMBOL_NAME} | {INTERVAL}\n"
        f"🕐 {TRADE_START} – {TRADE_END} IST\n"
        f"✅ HLC3/KAU + 200EMA + VWAP + RSI\n"
        f"⏰ {get_ist_time()}"
    )


# ── Time Check ──
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


# ── Data Fetch ──
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


# ── Indicators ──
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


# ── Build Signals ──
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


# ── Filter Checks ──
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


# ── Strategy Loop ──
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
        alert_buy(last['Close'], reasons) if ok else alert_skip("BUY", reasons)
        last_alert["time"] = ct
    elif last['sell']:
        ok, reasons = check_sell(last)
        alert_sell(last['Close'], reasons) if ok else alert_skip("SELL", reasons)
        last_alert["time"] = ct
    else:
        print("😴 No signal.")


# ── Start ──
if "YOUR_BOT_TOKEN" in TELEGRAM_BOT_TOKEN:
    print("❌ Fill in your TELEGRAM_BOT_TOKEN first!")
elif "YOUR_CHAT_ID" in TELEGRAM_CHAT_ID:
    print("❌ Fill in your TELEGRAM_CHAT_ID first!")
else:
    print("🚀 Bot starting...")
    alert_startup()
    while True:
        try:
            run_strategy()
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(60)
