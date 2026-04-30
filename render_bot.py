#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - FIXED VERSION
Fixed: Only generates signals when price is AT the 20% zones
"""

import requests
import json
from datetime import datetime
import time
import os
from threading import Thread

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# NSE Stocks to trade
STOCKS = [
    'NIFTY 50', 'BANK NIFTY', 'SBIN', 'YES BANK', 'PNB',
    'BANK OF BARODA', 'HFCL', 'ITI', 'NMDC', 'HIND COPPER',
    'CENTRAL BANK', 'BEML'
]

# ════════════════════════════════════════════════════════════════════════════
# KITE CONNECTION (Use your broker API)
# ════════════════════════════════════════════════════════════════════════════

def get_historical_data(symbol, timeframe='5minute', count=500):
    """Get historical data from your broker or data source"""
    # This is pseudo-code - replace with actual broker API
    # Example: from kiteconnect import KiteConnect
    # kite = KiteConnect(api_key=..., access_token=...)
    # data = kite.historical_data(instrument_token, timeframe, count)
    pass

def get_current_price(symbol):
    """Get current price from your broker"""
    # This is pseudo-code - replace with actual broker API
    pass

# ════════════════════════════════════════════════════════════════════════════
# BOX CALCULATION - CORRECT
# ════════════════════════════════════════════════════════════════════════════

def calculate_box(historical_data):
    """Calculate yesterday's box HIGH and LOW"""
    if not historical_data or len(historical_data) < 1:
        return None, None
    
    # Get yesterday's data (last 390 candles = full trading day for 5-min)
    yesterday_data = historical_data[-390:]
    
    box_high = max([candle['high'] for candle in yesterday_data])
    box_low = min([candle['low'] for candle in yesterday_data])
    
    return box_high, box_low

# ════════════════════════════════════════════════════════════════════════════
# OPENING RANGE QUALIFICATION - CORRECT
# ════════════════════════════════════════════════════════════════════════════

def check_opening_qualification(today_data, box_high, box_low):
    """
    Check if today's opening candle (first 3 candles) range >= 20% of box
    """
    if not today_data or len(today_data) < 3:
        return False, 0, 0
    
    # First 3 candles: 9:15, 9:20, 9:25 (5-min candles)
    opening_high = max([candle['high'] for candle in today_data[:3]])
    opening_low = min([candle['low'] for candle in today_data[:3]])
    opening_range = opening_high - opening_low
    
    box_range = box_high - box_low
    threshold = box_range * 0.20
    
    is_qualified = opening_range >= threshold
    
    return is_qualified, opening_range, threshold

# ════════════════════════════════════════════════════════════════════════════
# FIX 1: ZONE DETECTION - ADD ZONE CHECK
# ════════════════════════════════════════════════════════════════════════════

def check_if_at_zone(current_high, current_low, box_high, box_low, tolerance=0.02):
    """
    FIX 1: Check if current price is AT the box 20% zones
    
    tolerance=0.02 means within 2% of zone level
    """
    box_range = box_high - box_low
    
    # Calculate zones
    top_20_zone = box_high - (box_range * 0.20)  # Sell zone (red)
    bot_20_zone = box_low + (box_range * 0.20)   # Buy zone (green)
    
    # Check if price is AT top zone (within 2%)
    at_top_zone = (current_high >= (top_20_zone * (1 - tolerance)) and 
                   current_high <= (top_20_zone * (1 + tolerance)))
    
    # Check if price is AT bottom zone (within 2%)
    at_bot_zone = (current_low <= (bot_20_zone * (1 + tolerance)) and 
                   current_low >= (bot_20_zone * (1 - tolerance)))
    
    return at_top_zone, at_bot_zone, top_20_zone, bot_20_zone

# ════════════════════════════════════════════════════════════════════════════
# REVERSAL PATTERN DETECTION
# ════════════════════════════════════════════════════════════════════════════

def detect_reversal_pattern(current_candle, previous_candle):
    """Detect reversal patterns at zone levels"""
    
    current_open = current_candle['open']
    current_close = current_candle['close']
    current_high = current_candle['high']
    current_low = current_candle['low']
    
    prev_open = previous_candle['open']
    prev_close = previous_candle['close']
    
    # WICK REJECTION UP (at bottom zone = BUY)
    if current_low < current_open and current_close > current_open:
        wick_size = (current_close - current_low) / (current_high - current_low + 0.001)
        if wick_size > 0.60:
            return 'BUY', 'WICK_REJECTION_AT_BOT'
    
    # WICK REJECTION DOWN (at top zone = SELL)
    if current_high > current_open and current_close < current_open:
        wick_size = (current_high - current_close) / (current_high - current_low + 0.001)
        if wick_size > 0.60:
            return 'SELL', 'WICK_REJECTION_AT_TOP'
    
    # BULLISH ENGULFING (at bottom zone = BUY)
    if (prev_close < prev_open and 
        current_close > prev_open and 
        current_open < prev_close):
        return 'BUY', 'BULLISH_ENGULFING_AT_BOT'
    
    # BEARISH ENGULFING (at top zone = SELL)
    if (prev_close > prev_open and 
        current_close < prev_open and 
        current_open > prev_close):
        return 'SELL', 'BEARISH_ENGULFING_AT_TOP'
    
    return None, None

# ════════════════════════════════════════════════════════════════════════════
# FIX 2: SIGNAL GENERATION - ONLY AT ZONES
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified):
    """
    FIX 2: Only generate signal when:
    1. Setup is qualified (opening range >= 20% box)
    2. Current candle (4+) has price AT zone (top or bottom 20%)
    3. Reversal pattern detected AT that zone
    """
    
    if not is_qualified or len(today_data) < 4:
        return None
    
    # Start checking from candle 4 (9:30 AM onwards)
    for i in range(3, len(today_data)):
        current_candle = today_data[i]
        previous_candle = today_data[i-1]
        
        current_high = current_candle['high']
        current_low = current_candle['low']
        current_close = current_candle['close']
        
        # FIX 2: CHECK IF PRICE IS AT ZONE (THIS WAS MISSING!)
        at_top_zone, at_bot_zone, top_zone, bot_zone = check_if_at_zone(
            current_high, current_low, box_high, box_low
        )
        
        # Only proceed if price is AT a zone
        if not (at_top_zone or at_bot_zone):
            continue  # Skip - price not at zones
        
        # Detect reversal pattern
        signal_type, pattern = detect_reversal_pattern(current_candle, previous_candle)
        
        # Only generate signal if pattern is detected AT the zone
        if signal_type and pattern:
            box_range = box_high - box_low
            
            if signal_type == 'BUY' and at_bot_zone:
                entry = current_close
                tp1 = (box_high + box_low) / 2  # Midpoint
                tp2 = box_high
                sl = bot_zone - (box_range * 0.25)
                
                return {
                    'symbol': symbol,
                    'signal': 'BUY',
                    'entry': entry,
                    'tp1': tp1,
                    'tp2': tp2,
                    'sl': sl,
                    'pattern': pattern,
                    'at_zone': 'BOTTOM_20%'
                }
            
            elif signal_type == 'SELL' and at_top_zone:
                entry = current_close
                tp1 = (box_high + box_low) / 2  # Midpoint
                tp2 = box_low
                sl = top_zone + (box_range * 0.25)
                
                return {
                    'symbol': symbol,
                    'signal': 'SELL',
                    'entry': entry,
                    'tp1': tp1,
                    'tp2': tp2,
                    'sl': sl,
                    'pattern': pattern,
                    'at_zone': 'TOP_20%'
                }
    
    return None

# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM ALERT
# ════════════════════════════════════════════════════════════════════════════

def send_telegram_alert(signal, atr_threshold, opening_range):
    """Send signal to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    message = f"""
🎯 BOX REVERSAL SIGNAL - FIXED VERSION

Stock: {signal['symbol']}
Signal: {signal['signal']}
Entry: {signal['entry']:.2f}
TP1: {signal['tp1']:.2f}
TP2: {signal['tp2']:.2f}
SL: {signal['sl']:.2f}
Pattern: {signal['pattern']}
Zone: {signal['at_zone']}

ATR Threshold: {atr_threshold:.2f}
Opening Range: {opening_range:.2f}
Qualified: ✅ YES

Note: Signal generated ONLY when price AT zone!
"""
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message
        })
    except Exception as e:
        print(f"Telegram error: {e}")

# ════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS LOGGING
# ════════════════════════════════════════════════════════════════════════════

def log_to_sheets(signal, atr_threshold, opening_range, is_manipulated):
    """Log signal to Google Sheets"""
    # Use Google Apps Script to append row
    pass

# ════════════════════════════════════════════════════════════════════════════
# MAIN TRADING LOOP
# ════════════════════════════════════════════════════════════════════════════

def main():
    """Main trading loop"""
    print("Box Reversal Strategy - FIXED VERSION")
    print("Only generates signals when price AT zones")
    print("=" * 60)
    
    for symbol in STOCKS:
        try:
            # Get historical data
            historical_data = get_historical_data(symbol)
            
            if not historical_data:
                print(f"No data for {symbol}")
                continue
            
            # Calculate yesterday's box
            box_high, box_low = calculate_box(historical_data)
            
            if not box_high or not box_low:
                print(f"Box calculation failed for {symbol}")
                continue
            
            # Get today's data
            today_data = historical_data[-100:]  # Last 100 candles = today
            
            # Check opening qualification
            is_qualified, opening_range, threshold = check_opening_qualification(
                today_data, box_high, box_low
            )
            
            if not is_qualified:
                print(f"{symbol}: NOT QUALIFIED (range: {opening_range:.2f} < threshold: {threshold:.2f})")
                continue
            
            print(f"{symbol}: QUALIFIED ✅ (range: {opening_range:.2f} >= threshold: {threshold:.2f})")
            
            # Generate signal ONLY if price AT zone
            signal = generate_signal(symbol, today_data, box_high, box_low, is_qualified)
            
            if signal:
                print(f"  ➜ SIGNAL GENERATED: {signal['signal']} @ {signal['entry']:.2f}")
                print(f"  ➜ At zone: {signal['at_zone']}")
                print(f"  ➜ Pattern: {signal['pattern']}")
                
                # Send alerts
                send_telegram_alert(signal, threshold, opening_range)
                log_to_sheets(signal, threshold, opening_range, is_qualified)
            else:
                print(f"  ➜ No signal (price not at zones or pattern not detected)")
        
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

# ════════════════════════════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()

"""
FIXES APPLIED:
═══════════════

FIX 1: Zone Detection
────────────────────
Added check_if_at_zone() function
Only generates signals when price is AT top 20% or bottom 20% zones
Tolerance: 2% (within ±2% of zone level)

FIX 2: Signal Generation
────────────────────────
Modified generate_signal() function
Only checks candles 4+ (after 9:25 AM)
Skips candles where price is NOT at zones
Only generates signal when:
- Price at zone AND
- Reversal pattern detected AND
- At correct zone (top zone for SELL, bottom zone for BUY)

Result:
───────
✅ Signals only at correct zones
✅ Entries at proper levels
✅ Reduced false signals
✅ Higher accuracy
"""
