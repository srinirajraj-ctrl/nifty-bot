#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - WITH FLASK WEB SERVER
For Render + Uptime Monitor
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
# FLASK WEB SERVER - FOR UPTIME MONITOR + RENDER
# ════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

@app.route('/')
def health_check():
    return {'status': 'ok', 'service': 'nifty-bot', 'timestamp': datetime.now().isoformat()}, 200

@app.route('/health')
def health():
    return {'status': 'healthy', 'uptime_check': 'ok'}, 200

# ════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS SETUP
# ════════════════════════════════════════════════════════════════════════════

def setup_google_sheets():
    try:
        creds_json = os.getenv('GOOGLE_CREDS_JSON')
        sheet_id = os.getenv('GOOGLE_SHEET_ID')
        
        if not creds_json or not sheet_id:
            print("ERROR: GOOGLE_CREDS_JSON or GOOGLE_SHEET_ID not set")
            return None, None
        
        try:
            creds_dict = json.loads(base64.b64decode(creds_json))
        except:
            creds_dict = json.loads(creds_json)
        
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        
        print("✅ Google Sheets connected")
        return sheet, sheet_id
        
    except Exception as e:
        print(f"ERROR: {e}")
        return None, None

SHEET, SHEET_ID = setup_google_sheets()

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
# SHEETS LOGGING
# ════════════════════════════════════════════════════════════════════════════

def log_signal_to_sheets(date, time, stock, signal, entry, atr_threshold, opening_range, is_manipulated, pattern, sl, tp1, tp2, notes=''):
    if not SHEET:
        return None
    
    try:
        row_data = [
            date, time, stock, signal,
            round(entry, 2),
            round(atr_threshold, 2),
            round(opening_range, 2),
            "YES" if is_manipulated else "NO",
            pattern,
            round(sl, 2),
            round(tp1, 2),
            round(tp2, 2),
            "", "", "MONITORING", notes,
            f'=HYPERLINK("https://www.tradingview.com/?symbol={stock}","View Chart")'
        ]
        
        SHEET.append_row(row_data, table_range='A1')
        all_values = SHEET.get_all_values()
        row_num = len(all_values)
        
        OPEN_TRADES[row_num] = {'symbol': stock, 'entry': entry, 'tp1': tp1, 'tp2': tp2, 'sl': sl, 'signal': signal}
        
        print(f"  ✅ Logged to sheet row {row_num}")
        return row_num
        
    except Exception as e:
        print(f"  ❌ Error: {str(e)[:50]}")
        return None

# ════════════════════════════════════════════════════════════════════════════
# CALCULATIONS
# ════════════════════════════════════════════════════════════════════════════

def calculate_box(historical_data):
    if not historical_data or len(historical_data) < 1:
        return None, None
    try:
        yesterday_data = historical_data[-390:] if len(historical_data) >= 390 else historical_data
        box_high = max([candle['high'] for candle in yesterday_data])
        box_low = min([candle['low'] for candle in yesterday_data])
        return box_high, box_low
    except:
        return None, None

def check_opening_qualification(today_data, box_high, box_low):
    if not today_data or len(today_data) < 3:
        return False, 0, 0
    try:
        opening_high = max([candle['high'] for candle in today_data[:3]])
        opening_low = min([candle['low'] for candle in today_data[:3]])
        opening_range = opening_high - opening_low
        box_range = box_high - box_low
        threshold = box_range * 0.20
        is_qualified = opening_range >= threshold
        return is_qualified, opening_range, threshold
    except:
        return False, 0, 0

def check_if_at_zone(current_high, current_low, box_high, box_low, tolerance=0.02):
    try:
        box_range = box_high - box_low
        top_20_zone = box_high - (box_range * 0.20)
        bot_20_zone = box_low + (box_range * 0.20)
        
        at_top_zone = (current_high >= (top_20_zone * (1 - tolerance)) and current_high <= (top_20_zone * (1 + tolerance)))
        at_bot_zone = (current_low <= (bot_20_zone * (1 + tolerance)) and current_low >= (bot_20_zone * (1 - tolerance)))
        
        return at_top_zone, at_bot_zone, top_20_zone, bot_20_zone
    except:
        return False, False, 0, 0

# ════════════════════════════════════════════════════════════════════════════
# PATTERNS
# ════════════════════════════════════════════════════════════════════════════

def detect_reversal_pattern(current_candle, previous_candle):
    try:
        current_open = current_candle['open']
        current_close = current_candle['close']
        current_high = current_candle['high']
        current_low = current_candle['low']
        prev_open = previous_candle['open']
        prev_close = previous_candle['close']
        
        if current_low < current_open and current_close > current_open:
            wick_size = (current_close - current_low) / (current_high - current_low + 0.001)
            if wick_size > 0.60:
                return 'BUY', 'WICK_REJECTION_AT_BOT'
        
        if current_high > current_open and current_close < current_open:
            wick_size = (current_high - current_close) / (current_high - current_low + 0.001)
            if wick_size > 0.60:
                return 'SELL', 'WICK_REJECTION_AT_TOP'
        
        if (prev_close < prev_open and current_close > prev_open and current_open < prev_close):
            return 'BUY', 'BULLISH_ENGULFING_AT_BOT'
        
        if (prev_close > prev_open and current_close < prev_open and current_open > prev_close):
            return 'SELL', 'BEARISH_ENGULFING_AT_TOP'
        
        return None, None
    except:
        return None, None

# ════════════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified):
    try:
        if not is_qualified or len(today_data) < 4:
            return None
        
        for i in range(3, len(today_data)):
            current_candle = today_data[i]
            previous_candle = today_data[i-1]
            
            current_high = current_candle['high']
            current_low = current_candle['low']
            current_close = current_candle['close']
            
            at_top_zone, at_bot_zone, top_zone, bot_zone = check_if_at_zone(current_high, current_low, box_high, box_low)
            
            if not (at_top_zone or at_bot_zone):
                continue
            
            signal_type, pattern = detect_reversal_pattern(current_candle, previous_candle)
            
            if signal_type and pattern:
                box_range = box_high - box_low
                
                if signal_type == 'BUY' and at_bot_zone:
                    return {
                        'symbol': symbol,
                        'signal': 'BUY',
                        'entry': current_close,
                        'tp1': (box_high + box_low) / 2,
                        'tp2': box_high,
                        'sl': bot_zone - (box_range * 0.25),
                        'pattern': pattern,
                        'at_zone': 'BOTTOM_20%'
                    }
                
                elif signal_type == 'SELL' and at_top_zone:
                    return {
                        'symbol': symbol,
                        'signal': 'SELL',
                        'entry': current_close,
                        'tp1': (box_high + box_low) / 2,
                        'tp2': box_low,
                        'sl': top_zone + (box_range * 0.25),
                        'pattern': pattern,
                        'at_zone': 'TOP_20%'
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
        message = f"🎯 BOX REVERSAL SIGNAL - ROW {row_num}\n\nStock: {signal['symbol']}\nSignal: {signal['signal']}\nEntry: {signal['entry']:.2f}\nTP1: {signal['tp1']:.2f}\nTP2: {signal['tp2']:.2f}\nSL: {signal['sl']:.2f}\nPattern: {signal['pattern']}\nZone: {signal['at_zone']}\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=5)
    except:
        pass

# ════════════════════════════════════════════════════════════════════════════
# MAIN TRADING LOOP
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*70)
    print("BOX REVERSAL STRATEGY - PRODUCTION")
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
            signal = generate_signal(symbol, today_data, box_high, box_low, is_qualified)
            
            if signal:
                signal_count += 1
                print(f"      ➜ SIGNAL: {signal['signal']} @ {signal['entry']:.2f}")
                
                now = datetime.now()
                date_str = now.strftime('%d-%b-%Y')
                time_str = now.strftime('%H:%M %p')
                
                row_num = log_signal_to_sheets(
                    date_str, time_str, symbol, signal['signal'],
                    signal['entry'], threshold, opening_range, is_qualified,
                    signal['pattern'], signal['sl'], signal['tp1'], signal['tp2']
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
    print(f"Generated {signal_count} signals")
    print("="*70)

# ════════════════════════════════════════════════════════════════════════════
# BACKGROUND BOT THREAD
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
# RUN EVERYTHING
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("✅ Starting bot with Flask web server...")
    start_bot_thread()
    
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Flask server on port {port}")
    print(f"✅ Bot processes every hour\n")
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
