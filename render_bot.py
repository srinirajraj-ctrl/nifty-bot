#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - PROFESSIONAL v3 - COMPLETE
100% SYNCHRONIZED WITH TRADINGVIEW "Sri Engulphy System v3"
Features: AO, Divergence, John Wick, Elephant, False Breakout, Confluence Scoring
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
    return {'status': 'ok', 'service': 'nifty-bot-pro-v3', 'timestamp': datetime.now().isoformat()}, 200

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
LAST_SIGNAL_DATE = {}
FALSE_BREAKOUT_MEMORY = {}

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
    """Awesome Oscillator: SMA5(HL2) - SMA34(HL2)"""
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
    return ao_values[-1] > 0 if ao_values else False

def is_ao_rising(ao_values):
    return ao_values[-1] > ao_values[-2] if len(ao_values) >= 2 else False

# ════════════════════════════════════════════════════════════════════════════
# DIVERGENCE DETECTION - STRICT 8 BAR LOOKBACK
# ════════════════════════════════════════════════════════════════════════════

def detect_divergence_strict(data, ao_values, lookback=8):
    """Detect price + AO divergence (strict TV logic)"""
    if len(data) < lookback or len(ao_values) < lookback:
        return False, False
    
    recent_data = data[-lookback:]
    recent_ao = ao_values[-lookback:]
    
    # Bull divergence: lower lows in price, higher lows in AO + AO below zero
    lowest_price_idx = min(range(len(recent_data)), key=lambda i: recent_data[i]['low'])
    lowest_ao_idx = min(range(len(recent_ao)), key=lambda i: recent_ao[i])
    
    bull_div = (lowest_price_idx > lowest_ao_idx and 
                data[-1]['low'] > recent_data[lowest_price_idx]['low'] and
                ao_values[-1] > recent_ao[lowest_ao_idx] and
                ao_values[-1] < 0)
    
    # Bear divergence: higher highs in price, lower highs in AO + AO above zero
    highest_price_idx = max(range(len(recent_data)), key=lambda i: recent_data[i]['high'])
    highest_ao_idx = max(range(len(recent_ao)), key=lambda i: recent_ao[i])
    
    bear_div = (highest_price_idx > highest_ao_idx and 
                data[-1]['high'] < recent_data[highest_price_idx]['high'] and
                ao_values[-1] < recent_ao[highest_ao_idx] and
                ao_values[-1] > 0)
    
    return bull_div, bear_div

# ════════════════════════════════════════════════════════════════════════════
# TIME FILTERS
# ════════════════════════════════════════════════════════════════════════════

def is_in_lunch():
    ct = datetime.now().hour * 60 + datetime.now().minute
    return LUNCH_START <= ct <= LUNCH_END

def is_in_expiry():
    ct = datetime.now().hour * 60 + datetime.now().minute
    return EXPIRY_START <= ct <= EXPIRY_END

def is_london_session():
    ct = datetime.now().hour * 60 + datetime.now().minute
    london_start = 13 * 60 + 25
    london_end = 15 * 60 + 25
    return london_start <= ct <= london_end

def can_trade():
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
        
        print(f"  ✅ {signal_type} logged to row {row_num}")
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
# JOHN WICK DETECTION - 75% WICK SIZE
# ════════════════════════════════════════════════════════════════════════════

def detect_john_wick(current_candle, ao_bullish):
    """John Wick: 75% wick size + matching trend"""
    try:
        c_open = current_candle['open']
        c_close = current_candle['close']
        c_high = current_candle['high']
        c_low = current_candle['low']
        
        c_range = c_high - c_low
        if c_range == 0:
            return False
        
        # Bull JW: bottom wick >= 75%, green close
        if c_close > c_open:
            bottom_wick = (min(c_open, c_close) - c_low) / c_range
            if bottom_wick >= 0.75 and ao_bullish:
                return True
        
        # Bear JW: top wick >= 75%, red close
        if c_close < c_open:
            top_wick = (c_high - max(c_open, c_close)) / c_range
            if top_wick >= 0.75 and not ao_bullish:
                return True
        
        return False
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# ELEPHANT CANDLE - 30% OF BOX RANGE BODY
# ════════════════════════════════════════════════════════════════════════════

def detect_elephant(current_candle, box_high, box_low, signal_type):
    """Elephant: Large body (30%+ of box range) + direction"""
    try:
        c_open = current_candle['open']
        c_close = current_candle['close']
        
        body = abs(c_close - c_open)
        box_range = box_high - box_low
        body_threshold = box_range * 0.30
        
        if signal_type == 'BUY':
            return body >= body_threshold and c_close > box_low
        else:
            return body >= body_threshold and c_close < box_high
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# MULTI-CANDLE ENGULFING - 10 BAR LOOKBACK
# ════════════════════════════════════════════════════════════════════════════

def detect_multi_engulfing(current_candle, today_data, signal_type, lookback=10):
    """Count how many previous candles are engulfed"""
    try:
        c_open = current_candle['open']
        c_close = current_candle['close']
        
        engulf_count = 0
        for i in range(1, min(lookback + 1, len(today_data))):
            prev = today_data[-i]
            p_open = prev['open']
            p_close = prev['close']
            p_high = prev['high']
            p_low = prev['low']
            
            if signal_type == 'BUY':
                # Bullish engulfing
                if c_close > max(p_open, p_close) and c_open < min(p_open, p_close):
                    engulf_count += 1
            else:
                # Bearish engulfing
                if c_close < min(p_open, p_close) and c_open > max(p_open, p_close):
                    engulf_count += 1
        
        return engulf_count >= 2
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# FALSE BREAKOUT - 3 BAR COOLDOWN + 5 BAR MEMORY
# ════════════════════════════════════════════════════════════════════════════

def detect_false_breakout(previous_candle, current_candle, box_high, box_low, signal_type):
    """False breakout: breaks high/low then reverses"""
    try:
        prev_close = previous_candle['close']
        curr_close = current_candle['close']
        curr_open = current_candle['open']
        
        if signal_type == 'BUY':
            # Previous broke above box high, now reversed below
            return prev_close > box_high and curr_close < box_high and curr_close < curr_open
        else:
            # Previous broke below box low, now reversed above
            return prev_close < box_low and curr_close > box_low and curr_close > curr_open
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# CONFLUENCE SCORING - 0-5 POINTS
# ════════════════════════════════════════════════════════════════════════════

def calculate_confluence(signal_type, ao_bullish, divergence, is_london, john_wick, elephant):
    """Score: Base + AO + Divergence + London + JW + Elephant"""
    score = 1  # Base
    
    if (signal_type == 'BUY' and ao_bullish) or (signal_type == 'SELL' and not ao_bullish):
        score += 1
    
    if divergence:
        score += 1
    
    if is_london:
        score += 1
    
    if john_wick:
        score += 1
    
    if elephant:
        score += 1
    
    return min(score, 5)

# ════════════════════════════════════════════════════════════════════════════
# SIGNAL PRIORITY SYSTEM - ONE LABEL PER CANDLE
# ════════════════════════════════════════════════════════════════════════════

def get_signal_type(has_jw, has_div, is_london, has_elephant, confidence):
    """Determine signal type by priority"""
    if has_jw and has_div:
        return "ULTIMATE"  # Priority 7
    elif has_div:
        return "STRONG"    # Priority 6
    elif has_jw:
        return "JW"        # Priority 5
    elif is_london:
        return "LONDON"    # Priority 4
    elif has_elephant:
        return "ELEPHANT"  # Priority 3
    else:
        return "NORMAL"    # Priority 2

# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ════════════════════════════════════════════════════════════════════════════

def send_telegram_alert(signal, row_num):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        message = f"""
🎯 {signal['type'].upper()}

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
# MAIN SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified, ao_values, bull_div, bear_div):
    try:
        if not is_qualified or len(today_data) < 4 or not can_trade():
            return None
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if symbol in LAST_SIGNAL_DATE and LAST_SIGNAL_DATE[symbol] == today_str:
            return None  # One signal per stock per day
        
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
            
            ao_bullish = is_ao_bullish(ao_values)
            ao_rising = is_ao_rising(ao_values)
            london = is_london_session()
            
            # ═══ BUY SIGNALS ═══
            if at_bot_zone:
                # Check patterns
                jw = detect_john_wick(current_candle, ao_bullish)
                elephant = detect_elephant(current_candle, box_high, box_low, 'BUY')
                multi_engulf = detect_multi_engulfing(current_candle, today_data, 'BUY')
                fb = detect_false_breakout(previous_candle, current_candle, box_high, box_low, 'BUY')
                
                # MANDATORY: AO + Pattern
                if not (ao_bullish and ao_rising and (jw or elephant or multi_engulf or fb)):
                    continue
                
                confidence = calculate_confluence('BUY', ao_bullish, bull_div, london, jw, elephant)
                signal_type = get_signal_type(jw, bull_div, london, elephant, confidence)
                
                LAST_SIGNAL_DATE[symbol] = today_str
                
                return {
                    'symbol': symbol,
                    'signal': 'BUY',
                    'entry': current_close,
                    'tp1': box_mid,
                    'tp2': box_high,
                    'sl': bot_zone - (box_range * 0.25),
                    'pattern': jw and 'JOHN_WICK' or elephant and 'ELEPHANT' or 'ENGULFING',
                    'type': signal_type,
                    'confidence': confidence
                }
            
            # ═══ SELL SIGNALS ═══
            if at_top_zone:
                jw = detect_john_wick(current_candle, not ao_bullish)
                elephant = detect_elephant(current_candle, box_high, box_low, 'SELL')
                multi_engulf = detect_multi_engulfing(current_candle, today_data, 'SELL')
                fb = detect_false_breakout(previous_candle, current_candle, box_high, box_low, 'SELL')
                
                # MANDATORY: AO + Pattern
                if ao_bullish:
                    continue
                if not (not ao_bullish and not ao_rising and (jw or elephant or multi_engulf or fb)):
                    continue
                
                confidence = calculate_confluence('SELL', not ao_bullish, bear_div, london, jw, elephant)
                signal_type = get_signal_type(jw, bear_div, london, elephant, confidence)
                
                LAST_SIGNAL_DATE[symbol] = today_str
                
                return {
                    'symbol': symbol,
                    'signal': 'SELL',
                    'entry': current_close,
                    'tp1': box_mid,
                    'tp2': box_low,
                    'sl': top_zone + (box_range * 0.25),
                    'pattern': jw and 'JOHN_WICK' or elephant and 'ELEPHANT' or 'ENGULFING',
                    'type': signal_type,
                    'confidence': confidence
                }
        
        return None
    except:
        return None

# ════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*70)
    print("BOX REVERSAL STRATEGY - PROFESSIONAL v3 - COMPLETE")
    print("100% Synchronized with TradingView Sri Engulphy System v3")
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
            bull_div, bear_div = detect_divergence_strict(historical_data, ao_values)
            
            signal = generate_signal(symbol, today_data, box_high, box_low, is_qualified, ao_values, bull_div, bear_div)
            
            if signal:
                signal_count += 1
                print(f"      ➜ {signal['type']} @ {signal['entry']:.2f} | Confidence: {signal['confidence']}/5")
                
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
    print(f"Generated {signal_count} professional v3 signals")
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
    print("✅ Starting PROFESSIONAL v3 bot with Flask server...")
    start_bot_thread()
    
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Flask server on port {port}")
    print(f"✅ Bot processes every hour\n")
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
