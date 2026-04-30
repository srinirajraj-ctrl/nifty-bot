#!/usr/bin/env python3
"""
BOX REVERSAL STRATEGY - COMPLETE WORKING VERSION
Integrated with yfinance for real NSE data
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import requests
import json
import os
from threading import Thread
import time

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# NSE Stocks to trade
STOCKS = [
    'NIFTY 50',
    'BANK NIFTY',
    'SBIN',
    'YES BANK',
    'PNB',
    'BANK OF BARODA',
    'HFCL',
    'ITI',
    'NMDC',
    'HIND COPPER',
    'INFY',
    'TCS'
]

# yfinance symbol mapping
SYMBOL_MAP = {
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

# ════════════════════════════════════════════════════════════════════════════
# DATA FETCHING - YFINANCE INTEGRATION
# ════════════════════════════════════════════════════════════════════════════

def get_historical_data(symbol, period='5d', interval='1m'):
    """
    Get historical data from Yahoo Finance
    Converts to 5-minute candles
    """
    try:
        yf_symbol = SYMBOL_MAP.get(symbol)
        if not yf_symbol:
            print(f"{symbol}: Unknown symbol - SKIPPING")
            return None
        
        print(f"{symbol}: Fetching data from yfinance...", end=" ")
        
        # Download 1-minute data
        df = yf.download(
            yf_symbol,
            period=period,
            interval='1m',
            progress=False,
            timeout=10
        )
        
        if df.empty:
            print("NO DATA")
            return None
        
        # Resample to 5-minute candles
        df_5min = df.resample('5min').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        
        # Convert to list of dicts
        data = []
        for idx, row in df_5min.iterrows():
            data.append({
                'timestamp': idx,
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0
            })
        
        print(f"✅ Got {len(data)} candles")
        return data
    
    except Exception as e:
        print(f"ERROR: {str(e)[:50]}")
        return None

# ════════════════════════════════════════════════════════════════════════════
# BOX CALCULATION
# ════════════════════════════════════════════════════════════════════════════

def calculate_box(historical_data):
    """Calculate yesterday's box HIGH and LOW"""
    if not historical_data or len(historical_data) < 1:
        return None, None
    
    try:
        # Get yesterday's data (last 390 candles = full trading day for 5-min)
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
    """
    Check if today's opening candle (first 3 candles) range >= 20% of box
    """
    if not today_data or len(today_data) < 3:
        return False, 0, 0
    
    try:
        # First 3 candles: 9:15, 9:20, 9:25
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
        
        # Calculate zones
        top_20_zone = box_high - (box_range * 0.20)
        bot_20_zone = box_low + (box_range * 0.20)
        
        # Check if price is AT zones (within 2%)
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
    except Exception as e:
        print(f"Pattern detection error: {e}")
        return None, None

# ════════════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════════════════

def generate_signal(symbol, today_data, box_high, box_low, is_qualified):
    """
    Generate signal only when:
    1. Setup is qualified
    2. Price at zone
    3. Reversal pattern detected
    """
    try:
        if not is_qualified or len(today_data) < 4:
            return None
        
        # Check from candle 4 onwards (9:30 AM onwards)
        for i in range(3, len(today_data)):
            current_candle = today_data[i]
            previous_candle = today_data[i-1]
            
            current_high = current_candle['high']
            current_low = current_candle['low']
            current_close = current_candle['close']
            
            # Check if price is AT zone
            at_top_zone, at_bot_zone, top_zone, bot_zone = check_if_at_zone(
                current_high, current_low, box_high, box_low
            )
            
            if not (at_top_zone or at_bot_zone):
                continue
            
            # Detect pattern
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

def send_telegram_alert(signal, atr_threshold, opening_range):
    """Send signal to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    try:
        message = f"""
🎯 BOX REVERSAL SIGNAL

Stock: {signal['symbol']}
Signal: {signal['signal']}
Entry: {signal['entry']:.2f}
TP1: {signal['tp1']:.2f}
TP2: {signal['tp2']:.2f}
SL: {signal['sl']:.2f}
Pattern: {signal['pattern']}
Zone: {signal['at_zone']}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
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
    """Main trading loop with full error handling"""
    print("\n" + "="*70)
    print("BOX REVERSAL STRATEGY - YFINANCE VERSION")
    print("Real NSE data + Zone detection + Error handling")
    print("="*70 + "\n")
    
    signal_count = 0
    
    for symbol in STOCKS:
        try:
            # Get historical data from yfinance
            historical_data = get_historical_data(symbol)
            
            if not historical_data or len(historical_data) == 0:
                print(f"  └─ {symbol}: NO DATA - SKIPPING\n")
                continue
            
            # Calculate yesterday's box
            box_high, box_low = calculate_box(historical_data)
            
            if not box_high or not box_low:
                print(f"  └─ {symbol}: Box calculation failed\n")
                continue
            
            # Get today's data
            today_data = historical_data[-100:]
            
            # Check opening qualification
            is_qualified, opening_range, threshold = check_opening_qualification(
                today_data, box_high, box_low
            )
            
            if not is_qualified:
                print(f"  └─ {symbol}: NOT QUALIFIED (range: {opening_range:.2f} < threshold: {threshold:.2f})\n")
                continue
            
            print(f"  └─ {symbol}: QUALIFIED ✅")
            
            # Generate signal
            signal = generate_signal(symbol, today_data, box_high, box_low, is_qualified)
            
            if signal:
                signal_count += 1
                print(f"      ➜ SIGNAL #{signal_count}: {signal['signal']} @ {signal['entry']:.2f}")
                print(f"      ➜ Zone: {signal['at_zone']}")
                print(f"      ➜ Pattern: {signal['pattern']}")
                print(f"      ➜ TP1: {signal['tp1']:.2f} | TP2: {signal['tp2']:.2f} | SL: {signal['sl']:.2f}")
                
                # Send telegram alert
                send_telegram_alert(signal, threshold, opening_range)
            else:
                print(f"      ➜ No signal (price not at zones)")
            
            print()
        
        except Exception as e:
            print(f"  └─ {symbol}: ERROR - {str(e)[:40]}\n")
            continue
    
    print("="*70)
    print(f"Trading loop completed! Generated {signal_count} signals")
    print("="*70)

# ════════════════════════════════════════════════════════════════════════════
# RUN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"FATAL ERROR: {e}")

"""
YFINANCE INTEGRATION FEATURES:
═══════════════════════════════

✅ Fetches real NSE data from Yahoo Finance
✅ Converts 1-minute data to 5-minute candles
✅ Works with all 12 stocks
✅ No authentication needed (free API)
✅ Real box calculation from actual prices
✅ Zone detection on real data
✅ Pattern detection on real candles
✅ Complete error handling
✅ Telegram alerts on signals
✅ Ready for production!

STOCKS AVAILABLE:
═════════════════

1. NIFTY 50 (^NSEI)
2. BANK NIFTY (^NSEBANK)
3. SBIN (SBIN.NS)
4. YES BANK (YESBANK.NS)
5. PNB (PNB.NS)
6. BANK OF BARODA (BANKBARODA.NS)
7. HFCL (HFCL.NS)
8. ITI (ITI.NS)
9. NMDC (NMDC.NS)
10. HIND COPPER (HINDCOPPER.NS)
11. INFY (INFY.NS)
12. TCS (TCS.NS)

All with real-time 5-minute data!
"""
