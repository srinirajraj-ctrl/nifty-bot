#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - PROFESSIONAL v3 - REAL DATA + AUTO-CLOSING
100% SYNCHRONIZED WITH TRADINGVIEW "Sri Engulphy System v3"
Features: AO, Divergence, John Wick, Elephant, False Breakout, Confluence Scoring
AUTO-CLOSING: Tracks TP/SL hits, auto-closes, updates P&L in Google Sheets
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
import yfinance as yf

# ════════════════════════════════════════════════════════════════════════════
# FLASK WEB SERVER
# ════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

@app.route('/')
def health_check():
    return {'status': 'ok', 'service': 'nifty-bot-pro-v3-auto', 'timestamp': datetime.now().isoformat()}, 200

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

# NSE stock symbols with .NS suffix
STOCKS = {
    'NIFTY 50': '^NSEI',
    'BANK NIFTY': '^NSEBANK',
    'SBIN': 'SBIN.NS',
    'YES BANK': 'YESBANK.NS',
    'PNB': 'PNB.NS',
    'BANK OF BARODA': 'BANKBARODA.NS',
    'HFCL': 'HFCL.NS',
    'ITI': 'ITI.NS',
    'NMDC': 'NMDC.NS',
    'HIND COPPER': 'HINDCOPPER.NS',
    'INFY': 'INFY.NS',
    'TCS': 'TCS.NS'
}

# Time filters (IST)
LUNCH_START = 11 * 60 + 30
LUNCH_END = 12 * 60 + 0
EXPIRY_START = 14 * 60 + 45
EXPIRY_END = 15 * 60 + 30
MARKET_CLOSE = 15 * 60 + 15  # 3:15 PM

OPEN_TRADES = {}  # {row_num: {symbol, entry, tp1, tp2, sl, signal, type, open_time}}
LAST_SIGNAL_DATE = {}
DATA_CACHE = {}
CACHE_TIME = {}
BOT_STATS = {'wins': 0, 'losses': 0, 'total_pnl': 0}

# ════════════════════════════════════════════════════════════════════════════
# YFINANCE WITH RATE LIMITING FIX
# ════════════════════════════════════════════════════════════════════════════

def fetch_stock_data(symbol_name, symbol_code, retries=3, delay=2):
    """Fetch real data from yfinance with retry logic and caching"""
    cache_key = symbol_code
    current_time = datetime.now()
    
    # Use cache if < 5 minutes old
    if cache_key in DATA_CACHE and cache_key in CACHE_TIME:
        cache_age = (current_time - CACHE_TIME[cache_key]).total_seconds()
        if cache_age < 300:  # 5 minutes
            return DATA_CACHE[cache_key]
    
    for attempt in range(retries):
        try:
            # Fetch 5-minute data for last 7 days
            data = yf.download(
                symbol_code,
                period='7d',
                interval='5m',
                progress=False,
                timeout=10
            )
            
            if data is None or len(data) == 0:
                return None
            
            # Convert to list of dicts
            candles = []
            for idx, row in data.iterrows():
                candles.append({
                    'timestamp': idx,
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': int(row['Volume'])
                })
            
            # Cache the data
            DATA_CACHE[cache_key] = candles
            CACHE_TIME[cache_key] = current_time
            
            return candles
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Too Many" in error_msg or "rate" in error_msg.lower():
                time.sleep(delay)
                delay *= 2
            else:
                return None
    
    return None

# ════════════════════════════════════════════════════════════════════════════
# AUTO-CLOSING LOGIC
# ════════════════════════════════════════════════════════════════════════════

def check_and_close_trades():
    """Check all open trades for TP/SL hits and close if needed"""
    if not SHEET or not OPEN_TRADES:
        return
    
    closed_trades = []
    current_time = datetime.now()
    current_minute = current_time.hour * 60 + current_time.minute
    
    for row_num, trade in list(OPEN_TRADES.items()):
        try:
            symbol_name = trade['symbol']
            symbol_code = [v for k, v in STOCKS.items() if k == symbol_name][0] if symbol_name in STOCKS.values() else None
            
            if not symbol_code:
                continue
            
            # Fetch current price
            current_data = yf.download(symbol_code, period='1d', interval='1m', progress=False)
            if current_data is None or len(current_data) == 0:
                continue
            
            current_price = float(current_data.iloc[-1]['Close'])
            entry = trade['entry']
            tp1 = trade['tp1']
            tp2 = trade['tp2']
            sl = trade['sl']
            signal_type = trade['signal']
            
            # Determine if trade should close
            should_close = False
            exit_price = None
            result = None
            
            if signal_type == 'BUY':
                if current_price >= tp2:  # Hit TP2
                    should_close = True
                    exit_price = tp2
                    pnl = tp2 - entry
                    result = "WIN - TP2"
                    BOT_STATS['wins'] += 1
                elif current_price >= tp1:  # Hit TP1
                    should_close = True
                    exit_price = tp1
                    pnl = tp1 - entry
                    result = "WIN - TP1"
                    BOT_STATS['wins'] += 1
                elif current_price <= sl:  # Hit SL
                    should_close = True
                    exit_price = sl
                    pnl = sl - entry
                    result = "LOSS - SL"
                    BOT_STATS['losses'] += 1
            
            elif signal_type == 'SELL':
                if current_price <= tp2:  # Hit TP2
                    should_close = True
                    exit_price = tp2
                    pnl = entry - tp2
                    result = "WIN - TP2"
                    BOT_STATS['wins'] += 1
                elif current_price <= tp1:  # Hit TP1
                    should_close = True
                    exit_price = tp1
                    pnl = entry - tp1
                    result = "WIN - TP1"
                    BOT_STATS['wins'] += 1
                elif current_price >= sl:  # Hit SL
                    should_close = True
                    exit_price = sl
                    pnl = entry - sl
                    result = "LOSS - SL"
                    BOT_STATS['losses'] += 1
            
            # Auto-close at market close (3:15 PM)
            if current_minute >= MARKET_CLOSE:
                should_close = True
                exit_price = current_price
                pnl = (entry - exit_price) if signal_type == 'SELL' else (exit_price - entry)
                if pnl >= 0:
                    result = "WIN - MARKET CLOSE"
                    BOT_STATS['wins'] += 1
                else:
                    result = "LOSS - MARKET CLOSE"
                    BOT_STATS['losses'] += 1
            
            # Update Google Sheets if closed
            if should_close and exit_price:
                update_trade_in_sheets(row_num, exit_price, pnl, result)
                closed_trades.append((symbol_name, result, pnl))
                BOT_STATS['total_pnl'] += pnl
                
        except Exception as e:
            continue
    
    return closed_trades

def update_trade_in_sheets(row_num, exit_price, pnl, result):
    """Update trade row in Google Sheets with exit data"""
    if not SHEET:
        return
    
    try:
        # Column M (13) = Exit Price, Column N (14) = P&L, Column O (15) = Result
        SHEET.update_cell(row_num, 13, round(exit_price, 2))
        SHEET.update_cell(row_num, 14, round(pnl, 2))
        SHEET.update_cell(row_num, 15, result)
        
        if row_num in OPEN_TRADES:
            del OPEN_TRADES[row_num]
        
        print(f"    ✅ Trade closed: {result} | P&L: {pnl:.2f}")
        
    except Exception as e:
        print(f"    ❌ Error updating sheets: {str(e)[:50]}")

# ════════════════════════════════════════════════════════════════════════════
# AWESOME OSCILLATOR
# ════════════════════════════════════════════════════════════════════════════

def calculate_ao(data, fast=5, slow=34):
    """Awesome Oscillator: SMA5(HL2) - SMA34(HL2)"""
    if not data or len(data) < slow:
        return [0] * len(data) if data else []
    
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
# DIVERGENCE DETECTION
# ════════════════════════════════════════════════════════════════════════════

def detect_divergence_strict(data, ao_values, lookback=8):
    """Detect price + AO divergence (strict TV logic)"""
    if not data or len(data) < lookback or len(ao_values) < lookback:
        return False, False
    
    recent_data = data[-lookback:]
    recent_ao = ao_values[-lookback:]
    
    lowest_price_idx = min(range(len(recent_data)), key=lambda i: recent_data[i]['low'])
    lowest_ao_idx = min(range(len(recent_ao)), key=lambda i: recent_ao[i])
    
    bull_div = (lowest_price_idx > lowest_ao_idx and 
                data[-1]['low'] > recent_data[lowest_price_idx]['low'] and
                ao_values[-1] > recent_ao[lowest_ao_idx] and
                ao_values[-1] < 0)
    
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
            'type': signal_type,
            'open_time': datetime.now()
        }
        
        print(f"  ✅ {signal_type} logged to row {row_num} @ {time_str}")
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
# JOHN WICK DETECTION
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
        
        if c_close > c_open:
            bottom_wick = (min(c_open, c_close) - c_low) / c_range
            if bottom_wick >= 0.75 and ao_bullish:
                return True
        
        if c_close < c_open:
            top_wick = (c_high - max(c_open, c_close)) / c_range
            if top_wick >= 0.75 and not ao_bullish:
                return True
        
        return False
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# ELEPHANT CANDLE
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
# MULTI-CANDLE ENGULFING
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
            
            if signal_type == 'BUY':
                if c_close > max(p_open, p_close) and c_open < min(p_open, p_close):
                    engulf_count += 1
            else:
                if c_close < min(p_open, p_close) and c_open > max(p_open, p_close):
                    engulf_count += 1
        
        return engulf_count >= 2
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# CONFLUENCE SCORING
# ════════════════════════════════════════════════════════════════════════════

def calculate_confluence(signal_type, ao_bullish, divergence, is_london, john_wick, elephant):
    """Score: Base + AO + Divergence + London + JW + Elephant"""
    score = 1
    
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
# SIGNAL PRIORITY
# ════════════════════════════════════════════════════════════════════════════

def get_signal_type(has_jw, has_div, is_london, has_elephant, confidence):
    """Determine signal type by priority"""
    if has_jw and has_div:
        return "ULTIMATE"
    elif has_div:
        return "STRONG"
    elif has_jw:
        return "JW"
    elif is_london:
        return "LONDON"
    elif has_elephant:
        return "ELEPHANT"
    else:
        return "NORMAL"

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
# SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified, ao_values, bull_div, bear_div):
    try:
        if not is_qualified or len(today_data) < 4 or not can_trade():
            return None
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if symbol in LAST_SIGNAL_DATE and LAST_SIGNAL_DATE[symbol] == today_str:
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
            
            ao_bullish = is_ao_bullish(ao_values)
            ao_rising = is_ao_rising(ao_values)
            london = is_london_session()
            
            # BUY SIGNALS
            if at_bot_zone:
                jw = detect_john_wick(current_candle, ao_bullish)
                elephant = detect_elephant(current_candle, box_high, box_low, 'BUY')
                multi_engulf = detect_multi_engulfing(current_candle, today_data, 'BUY')
                
                if not (ao_bullish and ao_rising and (jw or elephant or multi_engulf)):
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
            
            # SELL SIGNALS
            if at_top_zone:
                jw = detect_john_wick(current_candle, not ao_bullish)
                elephant = detect_elephant(current_candle, box_high, box_low, 'SELL')
                multi_engulf = detect_multi_engulfing(current_candle, today_data, 'SELL')
                
                if ao_bullish:
                    continue
                if not (not ao_bullish and not ao_rising and (jw or elephant or multi_engulf)):
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
    print("BOX REVERSAL STRATEGY - PROFESSIONAL v3 - REAL DATA + AUTO-CLOSING")
    print("100% Synchronized with TradingView Sri Engulphy System v3")
    print("="*70 + "\n")
    
    if not SHEET:
        print("ERROR: Google Sheets not connected.")
        return
    
    # Check and close existing trades first
    print("Checking for trades to close...")
    closed = check_and_close_trades()
    if closed:
        for symbol, result, pnl in closed:
            print(f"  ✅ {symbol}: {result} | P&L: {pnl:.2f}")
    print()
    
    signal_count = 0
    
    for symbol_name, symbol_code in STOCKS.items():
        try:
            print(f"{symbol_name}:")
            
            historical_data = fetch_stock_data(symbol_name, symbol_code)
            
            if not historical_data or len(historical_data) == 0:
                print(f"  └─ NO DATA\n")
                continue
            
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
            
            ao_values = calculate_ao(historical_data)
            bull_div, bear_div = detect_divergence_strict(historical_data, ao_values)
            
            signal = generate_signal(symbol_name, today_data, box_high, box_low, is_qualified, ao_values, bull_div, bear_div)
            
            if signal:
                signal_count += 1
                print(f"      ➜ {signal['type']} @ {signal['entry']:.2f} | Confidence: {signal['confidence']}/5")
                
                now = datetime.now()
                date_str = now.strftime('%d-%b-%Y')
                time_str = now.strftime('%H:%M %p')
                
                row_num = log_signal_to_sheets(
                    date_str, time_str, symbol_name, signal['signal'],
                    signal['type'], signal['entry'], threshold, opening_range, is_qualified,
                    signal['pattern'], signal['sl'], signal['tp1'], signal['tp2'], signal['confidence']
                )
                
                send_telegram_alert(signal, row_num)
            else:
                print(f"      ➜ No signal")
            
            print()
            time.sleep(1)
        
        except Exception as e:
            print(f"  └─ ERROR - {str(e)[:40]}\n")
            continue
    
    print("="*70)
    print(f"Generated {signal_count} professional signals")
    print(f"Open trades: {len(OPEN_TRADES)}")
    print(f"Bot Stats: Wins={BOT_STATS['wins']}, Losses={BOT_STATS['losses']}, P&L={BOT_STATS['total_pnl']:.2f}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("="*70)

# ════════════════════════════════════════════════════════════════════════════
# BACKGROUND THREAD
# ════════════════════════════════════════════════════════════════════════════

def run_bot_loop():
    """Run bot every hour at minute 0-5 (reliable timing)"""
    run_count = 0
    last_run_hour = -1
    
    while True:
        current_time = datetime.now()
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        if current_hour != last_run_hour and current_minute < 5:
            run_count += 1
            print(f"\n{'='*70}")
            print(f"RUN #{run_count} - {current_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
            print(f"{'='*70}\n")
            
            try:
                main()
            except Exception as e:
                print(f"ERROR in run #{run_count}: {e}")
            
            last_run_hour = current_hour
            
            print(f"\n{'='*70}")
            print(f"Run #{run_count} completed at {current_time.strftime('%H:%M:%S IST')}")
            next_run = current_time + timedelta(hours=1)
            print(f"Next run at: {next_run.strftime('%H:%M:%S IST')}")
            print(f"{'='*70}\n")
        
        time.sleep(30)

def start_bot_thread():
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()

# ════════════════════════════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("✅ Starting PROFESSIONAL v3 REAL DATA + AUTO-CLOSING bot...")
    print("✅ Features: yfinance + Auto-close + P&L tracking")
    start_bot_thread()
    
    port = int(os.environ.get('PORT', 10000))
    print(f"✅ Flask server on port {port}")
    print(f"✅ Bot runs hourly at minute 0-5")
    print(f"✅ Auto-closing enabled\n")
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
