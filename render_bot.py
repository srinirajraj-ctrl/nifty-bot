#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - PROFESSIONAL v2
SYNCHRONIZED WITH TRADINGVIEW "Sri Engulphy System v3"
Features: AO, Divergence, Time Filters, Confluence Scoring, Multiple Signal Types
"""

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import requests
import json
import os
import time
import base64
import random
from flask import Flask
import threading

# ════════════════════════════════════════════════════════════════════════════
# FLASK WEB SERVER
# ════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

@app.route('/')
def health_check():
    return {'status': 'ok', 'service': 'nifty-bot-pro', 'timestamp': datetime.now().isoformat()}, 200

@app.route('/health')
def health():
    return {'status': 'healthy'}, 200

# ════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ════════════════════════════════════════════════════════════════════════════

def setup_google_sheets():
    try:
        creds_json = os.getenv('GOOGLE_CREDS_JSON')
        sheet_id = os.getenv('GOOGLE_SHEET_ID')
        
        if not creds_json or not sheet_id:
            print("ERROR: Credentials not set")
            return None
        
        try:
            creds_dict = json.loads(base64.b64decode(creds_json))
        except:
            creds_dict = json.loads(creds_json)
        
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        
        print("✅ Google Sheets connected")
        return sheet
        
    except Exception as e:
        print(f"ERROR: {e}")
        return None

SHEET = setup_google_sheets()

# ════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

STOCKS = ['NIFTY 50', 'BANK NIFTY', 'SBIN', 'YES BANK', 'PNB', 'BANK OF BARODA', 'HFCL', 'ITI', 'NMDC', 'HIND COPPER', 'INFY', 'TCS']

PRICE_RANGES = {
    'NIFTY 50': (24000, 24500),
    'BANK NIFTY': (55500, 57000),
    'SBIN': (1050, 1150),
    'YES BANK': (19.5, 21),
    'PNB': (110, 115),
    'BANK OF BARODA': (265, 275),
    'HFCL': (100, 110),
    'ITI': (300, 320),
    'NMDC': (140, 160),
    'HIND COPPER': (1080, 1120),
    'INFY': (3180, 3250),
    'TCS': (3650, 3750)
}

# Time filters (IST)
LUNCH_START = 11 * 60 + 30
LUNCH_END = 12 * 60 + 0
EXPIRY_START = 14 * 60 + 45
EXPIRY_END = 15 * 60 + 30

OPEN_TRADES = {}

# ════════════════════════════════════════════════════════════════════════════
# MOCK DATA
# ════════════════════════════════════════════════════════════════════════════

def generate_mock_data(symbol, num_candles=500):
    price_min, price_max = PRICE_RANGES[symbol]
    base_price = (price_min + price_max) / 2
    data = []
    current_price = base_price
    
    for i in range(num_candles):
        change = random.uniform(-0.5, 0.5)
        current_price += change
        current_price = max(price_min, min(price_max, current_price))
        
        open_price = current_price + random.uniform(-0.2, 0.2)
        high_price = max(current_price, open_price) + random.uniform(0, 0.3)
        low_price = min(current_price, open_price) - random.uniform(0, 0.3)
        close_price = current_price
        
        data.append({
            'timestamp': datetime.now() - timedelta(minutes=num_candles-i),
            'open': round(open_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'close': round(close_price, 2),
            'volume': random.randint(100000, 500000)
        })
    
    return data

# ════════════════════════════════════════════════════════════════════════════
# AWESOME OSCILLATOR
# ════════════════════════════════════════════════════════════════════════════

def calculate_ao(data, fast=5, slow=34):
    """Calculate Awesome Oscillator: SMA5(HL2) - SMA34(HL2)"""
    if len(data) < slow:
        return [0] * len(data)
    
    hl2_values = [(c['high'] + c['low']) / 2 for c in data]
    
    ao_values = []
    for i in range(len(hl2_values)):
        fast_sma = sum(hl2_values[max(0, i-fast+1):i+1]) / min(i+1, fast)
        slow_sma = sum(hl2_values[max(0, i-slow+1):i+1]) / min(i+1, slow)
        ao_values.append(fast_sma - slow_sma)
    
    return ao_values

def is_ao_bullish(ao_values):
    """True if AO is above zero"""
    return ao_values[-1] > 0

def is_ao_rising(ao_values):
    """True if AO rising (green bar)"""
    if len(ao_values) < 2:
        return False
    return ao_values[-1] > ao_values[-2]

# ════════════════════════════════════════════════════════════════════════════
# DIVERGENCE DETECTION
# ════════════════════════════════════════════════════════════════════════════

def detect_divergence(data, ao_values, lookback=8):
    """Detect price + AO divergence"""
    if len(data) < lookback or len(ao_values) < lookback:
        return False, False
    
    # Bull divergence: lower low in price, higher low in AO
    recent_low_price = min([c['low'] for c in data[-lookback:]])
    recent_low_ao = min(ao_values[-lookback:])
    
    bull_div = (data[-1]['low'] > recent_low_price and 
                ao_values[-1] > recent_low_ao and 
                ao_values[-1] < 0)
    
    # Bear divergence: higher high in price, lower high in AO
    recent_high_price = max([c['high'] for c in data[-lookback:]])
    recent_high_ao = max(ao_values[-lookback:])
    
    bear_div = (data[-1]['high'] < recent_high_price and 
                ao_values[-1] < recent_high_ao and 
                ao_values[-1] > 0)
    
    return bull_div, bear_div

# ════════════════════════════════════════════════════════════════════════════
# TIME FILTERS
# ════════════════════════════════════════════════════════════════════════════

def is_in_lunch():
    """Check if in lunch time (11:30-12:00)"""
    ct = datetime.now().hour * 60 + datetime.now().minute
    return LUNCH_START <= ct <= LUNCH_END

def is_in_expiry():
    """Check if in expiry time (14:45-15:30)"""
    ct = datetime.now().hour * 60 + datetime.now().minute
    return EXPIRY_START <= ct <= EXPIRY_END

def is_london_session():
    """Check if in London session (13:25-15:25 IST)"""
    ct = datetime.now().hour * 60 + datetime.now().minute
    london_start = 13 * 60 + 25
    london_end = 15 * 60 + 25
    return london_start <= ct <= london_end

def can_trade():
    """Check if trading allowed"""
    return not (is_in_lunch() or is_in_expiry())

# ════════════════════════════════════════════════════════════════════════════
# SHEETS LOGGING
# ════════════════════════════════════════════════════════════════════════════

def log_signal_to_sheets(date, time_str, stock, signal, signal_type, entry, atr_threshold, 
                         opening_range, is_manipulated, pattern, sl, tp1, tp2, confidence, notes=''):
    if not SHEET:
        return None
    
    try:
        row_data = [
            date, time_str, stock, signal,
            round(entry, 2),
            round(atr_threshold, 2),
            round(opening_range, 2),
            "YES" if is_manipulated else "NO",
            pattern,
            round(sl, 2),
            round(tp1, 2),
            round(tp2, 2),
            "", "", f"{signal_type} [{confidence}/5]", notes,
            f'=HYPERLINK("https://www.tradingview.com/chart/NSE/{stock.replace(" ", "")}","View Chart")'
        ]
        
        SHEET.append_row(row_data, table_range='A1')
        all_values = SHEET.get_all_values()
        row_num = len(all_values)
        
        OPEN_TRADES[row_num] = {
            'symbol': stock,
            'entry': entry,
            'tp1': tp1,
            'tp2': tp2,
            'sl': sl,
            'signal': signal,
            'type': signal_type
        }
        
        print(f"  ✅ Logged {signal_type} to row {row_num} (confidence: {confidence}/5)")
        return row_num
        
    except Exception as e:
        print(f"  ❌ Error: {str(e)[:50]}")
        return None

# ════════════════════════════════════════════════════════════════════════════
# BOX CALCULATION
# ════════════════════════════════════════════════════════════════════════════

def calculate_box(historical_data):
    if not historical_data or len(historical_data) < 1:
        return None, None
    
    try:
        yesterday_data = historical_data[-390:] if len(historical_data) >= 390 else historical_data
        box_high = max([c['high'] for c in yesterday_data])
        box_low = min([c['low'] for c in yesterday_data])
        return box_high, box_low
    except:
        return None, None

# ════════════════════════════════════════════════════════════════════════════
# OPENING QUALIFICATION
# ════════════════════════════════════════════════════════════════════════════

def check_opening_qualification(today_data, box_high, box_low):
    if not today_data or len(today_data) < 3:
        return False, 0, 0
    
    try:
        opening_high = max([c['high'] for c in today_data[:3]])
        opening_low = min([c['low'] for c in today_data[:3]])
        opening_range = opening_high - opening_low
        box_range = box_high - box_low
        threshold = box_range * 0.20
        is_qualified = opening_range >= threshold
        return is_qualified, opening_range, threshold
    except:
        return False, 0, 0

# ════════════════════════════════════════════════════════════════════════════
# ZONE DETECTION
# ════════════════════════════════════════════════════════════════════════════

def check_if_at_zone(current_high, current_low, box_high, box_low, tolerance=0.02):
    try:
        box_range = box_high - box_low
        top_20_zone = box_high - (box_range * 0.20)
        bot_20_zone = box_low + (box_range * 0.20)
        
        at_top_zone = (current_high >= (top_20_zone * (1 - tolerance)) and 
                       current_high <= (top_20_zone * (1 + tolerance)))
        
        at_bot_zone = (current_low <= (bot_20_zone * (1 + tolerance)) and 
                       current_low >= (bot_20_zone * (1 - tolerance)))
        
        return at_top_zone, at_bot_zone, top_20_zone, bot_20_zone
    except:
        return False, False, 0, 0

# ════════════════════════════════════════════════════════════════════════════
# PATTERNS
# ════════════════════════════════════════════════════════════════════════════

def detect_reversal_pattern(current_candle, previous_candle):
    try:
        c_open = current_candle['open']
        c_close = current_candle['close']
        c_high = current_candle['high']
        c_low = current_candle['low']
        p_open = previous_candle['open']
        p_close = previous_candle['close']
        
        c_body = abs(c_close - c_open)
        c_range = c_high - c_low
        
        # Wick rejection
        if c_low < c_open and c_close > c_open:
            wick_size = (c_close - c_low) / (c_range + 0.001)
            if wick_size > 0.60:
                return 'BUY', 'WICK_REJECTION'
        
        if c_high > c_open and c_close < c_open:
            wick_size = (c_high - c_close) / (c_range + 0.001)
            if wick_size > 0.60:
                return 'SELL', 'WICK_REJECTION'
        
        # Engulfing
        if (p_close < p_open and c_close > p_open and c_open < p_close):
            return 'BUY', 'BULLISH_ENGULFING'
        
        if (p_close > p_open and c_close < p_open and c_open > p_close):
            return 'SELL', 'BEARISH_ENGULFING'
        
        return None, None
    except:
        return None, None

# ════════════════════════════════════════════════════════════════════════════
# CONFLUENCE SCORING
# ════════════════════════════════════════════════════════════════════════════

def calculate_confluence_score(signal_type, ao_bullish, divergence, is_london):
    """Score: 0-5 points based on confluence"""
    score = 0
    
    # Momentum confirmation (AO)
    if (signal_type == 'BUY' and ao_bullish) or (signal_type == 'SELL' and not ao_bullish):
        score += 1
    
    # Divergence (high probability)
    if divergence:
        score += 2
    
    # London session bonus
    if is_london:
        score += 1
    
    # Base pattern
    score += 1
    
    return min(score, 5)  # Max 5

# ════════════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified, ao_values, bull_div, bear_div):
    try:
        if not is_qualified or len(today_data) < 4 or not can_trade():
            return None
        
        box_range = box_high - box_low
        box_mid = (box_high + box_low) / 2
        
        for i in range(3, len(today_data)):
            current_candle = today_data[i]
            previous_candle = today_data[i-1]
            
            current_high = current_candle['high']
            current_low = current_candle['low']
            current_close = current_candle['close']
            
            at_top_zone, at_bot_zone, top_zone, bot_zone = check_if_at_zone(
                current_high, current_low, box_high, box_low
            )
            
            if not (at_top_zone or at_bot_zone):
                continue
            
            signal_type, pattern = detect_reversal_pattern(current_candle, previous_candle)
            
            if not signal_type or not pattern:
                continue
            
            ao_bullish = is_ao_bullish(ao_values)
            ao_rising = is_ao_rising(ao_values)
            london = is_london_session()
            
            # BUY SIGNALS
            if signal_type == 'BUY' and at_bot_zone:
                confidence = calculate_confluence_score('BUY', ao_bullish, bull_div, london)
                
                # Filter: Must have AO confirmation + pattern
                if not (ao_bullish and ao_rising):
                    continue
                
                signal_name = 'ULTIMATE BUY' if (bull_div and ao_bullish) else \
                              'STRONG BUY' if bull_div else \
                              'LONDON BUY' if london else \
                              'NORMAL BUY'
                
                return {
                    'symbol': symbol,
                    'signal': 'BUY',
                    'entry': current_close,
                    'tp1': box_mid,
                    'tp2': box_high,
                    'sl': bot_zone - (box_range * 0.25),
                    'pattern': pattern,
                    'type': signal_name,
                    'confidence': confidence
                }
            
            # SELL SIGNALS
            if signal_type == 'SELL' and at_top_zone:
                confidence = calculate_confluence_score('SELL', not ao_bullish, bear_div, london)
                
                # Filter: Must have AO confirmation + pattern
                if ao_bullish:
                    continue
                
                signal_name = 'ULTIMATE SELL' if (bear_div and not ao_bullish) else \
                              'STRONG SELL' if bear_div else \
                              'LONDON SELL' if london else \
                              'NORMAL SELL'
                
                return {
                    'symbol': symbol,
                    'signal': 'SELL',
                    'entry': current_close,
                    'tp1': box_mid,
                    'tp2': box_low,
                    'sl': top_zone + (box_range * 0.25),
                    'pattern': pattern,
                    'type': signal_name,
                    'confidence': confidence
                }
        
        return None
    except:
        return None

# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ════════════════════════════════════════════════════════════════════════════

def send_telegram_alert(signal, row_num):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        message = f"""
🎯 {signal['type']}

Stock: {signal['symbol']}
Signal: {signal['signal']}
Entry: {signal['entry']:.2f}
TP1: {signal['tp1']:.2f}
TP2: {signal['tp2']:.2f}
SL: {signal['sl']:.2f}
Pattern: {signal['pattern']}
Confidence: {signal['confidence']}/5

Row: {row_num}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}
"""
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=5)
    except:
        pass

# ════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*70)
    print("BOX REVERSAL STRATEGY - PROFESSIONAL v2")
    print("Synchronized with TradingView Sri Engulphy System v3")
    print("="*70 + "\n")
    
    if not SHEET:
        print("ERROR: Google Sheets not connected.")
        return
    
    signal_count = 0
    
    for idx, symbol in enumerate(STOCKS):
        try:
            print(f"[{idx+1}/{len(STOCKS)}] {symbol}")
            
            historical_data = generate_mock_data(symbol, num_candles=500)
            print(f"{symbol}: Generating mock data...", end=" ")
            
            if not historical_data or len(historical_data) == 0:
                print("NO DATA\n")
                continue
            
            print(f"✅ Got {len(historical_data)} candles")
            
            box_high, box_low = calculate_box(historical_data)
            if not box_high or not box_low:
                print(f"  └─ Box calculation failed\n")
                continue
            
            today_data = historical_data[-100:]
            is_qualified, opening_range, threshold = check_opening_qualification(today_data, box_high, box_low)
            
            if not is_qualified:
                print(f"  └─ NOT QUALIFIED\n")
                continue
            
            print(f"  └─ QUALIFIED ✅")
            
            # Calculate AO and divergence
            ao_values = calculate_ao(historical_data)
            bull_div, bear_div = detect_divergence(historical_data, ao_values)
            
            signal = generate_signal(symbol, today_data, box_high, box_low, is_qualified, ao_values, bull_div, bear_div)
            
            if signal:
                signal_count += 1
                print(f"      ➜ {signal['type']} @ {signal['entry']:.2f} (confidence: {signal['confidence']}/5)")
                
                now = datetime.now()
                date_str = now.strftime('%d-%b-%Y')
                time_str = now.strftime('%H:%M %p')
                
                row_num = log_signal_to_sheets(
                    date_str, time_str, symbol, signal['signal'],
                    signal['type'], signal['entry'], threshold, opening_range, is_qualified,
                    signal['pattern'], signal['sl'], signal['tp1'], signal['tp2'], signal['confidence']
                )
                
                send_telegram_alert(signal, row_num)
            else:
                print(f"      ➜ No signal")
            
            print()
            time.sleep(0.5)
        
        except Exception as e:
            print(f"  └─ ERROR - {str(e)[:40]}\n")
            continue
    
    print("="*70)
    print(f"Generated {signal_count} professional signals")
    print("="*70)

# ════════════════════════════════════════════════════════════════════════════
# BACKGROUND THREAD
# ════════════════════════════════════════════════════════════════════════════

def run_bot_loop():
    run_count = 0
    while True:
        run_count += 1
        print(f"\nRUN #{run_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        try:
            main()
        except Exception as e:
            print(f"ERROR: {e}")
        
        print(f"Next run in 1 hour\n")
        time.sleep(3600)

def start_bot_thread():
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()

# ════════════════════════════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("✅ Starting professional bot with Flask server...")
    start_bot_thread()
    
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Flask server on port {port}")
    print(f"✅ Bot processes every hour\n")
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
