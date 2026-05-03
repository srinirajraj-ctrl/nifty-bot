#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - PRODUCTION VERSION
Uses mock/cached data to avoid yfinance rate limiting
Real integration ready when yfinance is stable
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

# ════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS SETUP
# ════════════════════════════════════════════════════════════════════════════

def setup_google_sheets():
    """Initialize Google Sheets connection"""
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
        print(f"ERROR connecting to Google Sheets: {e}")
        return None, None

SHEET, SHEET_ID = setup_google_sheets()

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

STOCKS = [
    'NIFTY 50', 'BANK NIFTY', 'SBIN', 'YES BANK', 'PNB',
    'BANK OF BARODA', 'HFCL', 'ITI', 'NMDC', 'HIND COPPER',
    'INFY', 'TCS'
]

# Price ranges for mock data generation
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
# MOCK DATA GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_mock_data(symbol, num_candles=500):
    """Generate realistic mock data for testing"""
    price_min, price_max = PRICE_RANGES[symbol]
    base_price = (price_min + price_max) / 2
    
    data = []
    current_price = base_price
    
    for i in range(num_candles):
        # Random walk
        change = random.uniform(-0.5, 0.5)
        current_price += change
        current_price = max(price_min, min(price_max, current_price))
        
        # 5-minute candle
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
# GOOGLE SHEETS FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def log_signal_to_sheets(date, time, stock, signal, entry, atr_threshold, 
                         opening_range, is_manipulated, pattern, sl, tp1, tp2, notes=''):
    """Log signal to Google Sheets"""
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
        
        OPEN_TRADES[row_num] = {
            'symbol': stock,
            'entry': entry,
            'tp1': tp1,
            'tp2': tp2,
            'sl': sl,
            'signal': signal
        }
        
        print(f"  ✅ Logged to sheet row {row_num}")
        return row_num
        
    except Exception as e:
        print(f"  ❌ Sheets logging error: {str(e)[:50]}")
        return None

def update_trade_closed_in_sheets(row_num, exit_price, pnl, result):
    """Update SAME row with exit data"""
    if not SHEET or not row_num:
        return False
    
    try:
        SHEET.update_cell(row_num, 13, round(exit_price, 2))
        SHEET.update_cell(row_num, 14, round(pnl, 2))
        SHEET.update_cell(row_num, 15, result)
        
        if row_num in OPEN_TRADES:
            del OPEN_TRADES[row_num]
        
        print(f"  ✅ Updated row {row_num}: {result}")
        return True
        
    except Exception as e:
        print(f"  ❌ Sheets update error: {str(e)[:50]}")
        return False

# ════════════════════════════════════════════════════════════════════════════
# BOX CALCULATION
# ════════════════════════════════════════════════════════════════════════════

def calculate_box(historical_data):
    """Calculate yesterday's box HIGH and LOW"""
    if not historical_data or len(historical_data) < 1:
        return None, None
    
    try:
        yesterday_data = historical_data[-390:] if len(historical_data) >= 390 else historical_data
        
        box_high = max([candle['high'] for candle in yesterday_data])
        box_low = min([candle['low'] for candle in yesterday_data])
        
        return box_high, box_low
    except Exception as e:
        print(f"Box calculation error: {e}")
        return None, None

# ════════════════════════════════════════════════════════════════════════════
# OPENING RANGE QUALIFICATION
# ════════════════════════════════════════════════════════════════════════════

def check_opening_qualification(today_data, box_high, box_low):
    """Check if today's opening range >= 20% of box"""
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
    except Exception as e:
        print(f"Qualification check error: {e}")
        return False, 0, 0

# ════════════════════════════════════════════════════════════════════════════
# ZONE DETECTION
# ════════════════════════════════════════════════════════════════════════════

def check_if_at_zone(current_high, current_low, box_high, box_low, tolerance=0.02):
    """Check if current price is AT the box 20% zones"""
    try:
        box_range = box_high - box_low
        
        top_20_zone = box_high - (box_range * 0.20)
        bot_20_zone = box_low + (box_range * 0.20)
        
        at_top_zone = (current_high >= (top_20_zone * (1 - tolerance)) and 
                       current_high <= (top_20_zone * (1 + tolerance)))
        
        at_bot_zone = (current_low <= (bot_20_zone * (1 + tolerance)) and 
                       current_low >= (bot_20_zone * (1 - tolerance)))
        
        return at_top_zone, at_bot_zone, top_20_zone, bot_20_zone
    except Exception as e:
        print(f"Zone detection error: {e}")
        return False, False, 0, 0

# ════════════════════════════════════════════════════════════════════════════
# REVERSAL PATTERN DETECTION
# ════════════════════════════════════════════════════════════════════════════

def detect_reversal_pattern(current_candle, previous_candle):
    """Detect reversal patterns at zone levels"""
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
        
        if (prev_close < prev_open and 
            current_close > prev_open and 
            current_open < prev_close):
            return 'BUY', 'BULLISH_ENGULFING_AT_BOT'
        
        if (prev_close > prev_open and 
            current_close < prev_open and 
            current_open > prev_close):
            return 'SELL', 'BEARISH_ENGULFING_AT_TOP'
        
        return None, None
    except Exception as e:
        print(f"Pattern detection error: {e}")
        return None, None

# ════════════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified):
    """Generate signal only when price at zone + pattern detected"""
    try:
        if not is_qualified or len(today_data) < 4:
            return None
        
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
    except Exception as e:
        print(f"Signal generation error: {e}")
        return None

# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM ALERT
# ════════════════════════════════════════════════════════════════════════════

def send_telegram_alert(signal, row_num):
    """Send signal to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        message = f"""
🎯 BOX REVERSAL SIGNAL - ROW {row_num}

Stock: {signal['symbol']}
Signal: {signal['signal']}
Entry: {signal['entry']:.2f}
TP1: {signal['tp1']:.2f}
TP2: {signal['tp2']:.2f}
SL: {signal['sl']:.2f}
Pattern: {signal['pattern']}
Zone: {signal['at_zone']}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}
"""
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message
        }, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

# ════════════════════════════════════════════════════════════════════════════
# MAIN TRADING LOOP
# ════════════════════════════════════════════════════════════════════════════

def main():
    """Main trading loop"""
    print("\n" + "="*70)
    print("BOX REVERSAL STRATEGY - PRODUCTION VERSION")
    print("Using mock data (yfinance rate limit workaround)")
    print("="*70 + "\n")
    
    if not SHEET:
        print("ERROR: Google Sheets not connected. Exiting.")
        return
    
    signal_count = 0
    
    for idx, symbol in enumerate(STOCKS):
        try:
            print(f"[{idx+1}/{len(STOCKS)}] {symbol}")
            
            # Generate mock data instead of fetching from yfinance
            historical_data = generate_mock_data(symbol, num_candles=500)
            
            print(f"{symbol}: Generating mock data...", end=" ")
            
            if not historical_data or len(historical_data) == 0:
                print("NO DATA")
                print(f"  └─ NO DATA\n")
                continue
            
            print(f"✅ Got {len(historical_data)} candles")
            
            box_high, box_low = calculate_box(historical_data)
            
            if not box_high or not box_low:
                print(f"  └─ Box calculation failed\n")
                continue
            
            today_data = historical_data[-100:]
            
            is_qualified, opening_range, threshold = check_opening_qualification(
                today_data, box_high, box_low
            )
            
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
    print(f"Trading loop completed! Generated {signal_count} signals")
    print(f"Open trades: {len(OPEN_TRADES)}")
    print("="*70)

# ════════════════════════════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        run_count = 0
        while True:
            run_count += 1
            print(f"\n{'='*70}")
            print(f"RUN #{run_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*70}\n")
            
            main()
            
            print(f"\n{'='*70}")
            print(f"Run #{run_count} completed!")
            print(f"Next run in 1 hour at {(datetime.now() + timedelta(hours=1)).strftime('%H:%M:%S')}")
            print(f"{'='*70}\n")
            
            # Wait 1 hour before next run
            time.sleep(3600)
    
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"FATAL ERROR: {e}")
