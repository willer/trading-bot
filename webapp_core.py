import configparser
import sqlite3
from flask import Flask, g, json, session
from flask_sqlalchemy import SQLAlchemy
import redis
# # SQLite doesn't need connection pooling  # Not needed for SQLite
import datetime
from datetime import timedelta
import asyncio
import pytz
from core_error import handle_ex

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trade.db'
app.config['SECRET_KEY'] = 'your_secret_key_here'
db = SQLAlchemy(app)

# Load user credentials from config file
config = configparser.ConfigParser()
config.read('config.ini')
USER_CREDENTIALS = config['users']

r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('health')
p.get_message(timeout=3)

# Eastern timezone for display purposes
EASTERN = pytz.timezone('US/Eastern')

def to_eastern_time(timestamp_input):
    """Convert timestamp to Eastern time for display, handling mixed database formats"""
    if isinstance(timestamp_input, str):
        # Parse string timestamp
        dt = datetime.datetime.fromisoformat(timestamp_input.replace('Z', '+00:00'))
    else:
        dt = timestamp_input
    
    # If it has timezone info, convert to Eastern
    if dt.tzinfo is not None:
        return dt.astimezone(EASTERN)
    
    # For naive timestamps, detect format based on server migration cutoff
    # Migration from Windows (Eastern) to Mac (UTC) happened at '2025-09-04 20:44:23'
    cutoff_timestamp = datetime.datetime(2025, 9, 4, 20, 44, 23)
    
    if dt < cutoff_timestamp:
        # Old format: already stored as Eastern time, just add timezone info
        return EASTERN.localize(dt, is_dst=None)
    else:
        # New format: stored as UTC, convert to Eastern
        utc_dt = pytz.UTC.localize(dt)
        return utc_dt.astimezone(EASTERN)

def eastern_now():
    """Get current time in Eastern timezone"""
    return datetime.datetime.now(EASTERN)

# SQLite connection (simpler than PostgreSQL)
def get_db():
    try:
        if 'db' not in g:
            g.db = sqlite3.connect('trade.db')
            g.db.row_factory = sqlite3.Row
        return g.db
    except Exception as e:
        handle_ex(e, context="database_connection", service="webapp", extra_tags=['component:core'])
        raise

@app.teardown_appcontext
def close_db(error):
    try:
        db = g.pop('db', None)
        if db is not None:
            db.close()
    except Exception as e:
        handle_ex(e, context="database_cleanup", service="webapp", extra_tags=['component:core'])
        raise

## ROUTES

# New function to check if user is logged in
def is_logged_in():
    return session.get('logged_in', False)

def get_signals():
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM signals ORDER BY timestamp DESC LIMIT 500")
        signals = cursor.fetchall()

        # Convert to a list of dicts with column names as keys
        column_names = [desc[0] for desc in cursor.description]
        signals = [dict(zip(column_names, signal)) for signal in signals]

        # Convert timestamps to Eastern time for display
        for signal in signals:
            if signal['timestamp']:
                # Convert timestamp to Eastern time using intelligent detection
                signal['timestamp'] = to_eastern_time(signal['timestamp'])
            
            if signal.get('processed'):
                # Convert processed timestamp to Eastern time
                signal['processed'] = to_eastern_time(signal['processed'])

        return signals
    except Exception as e:
        handle_ex(e, context="get_signals", service="webapp", extra_tags=['component:core'])
        raise

def get_signal(id):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM signals WHERE id = ?", (id,))
        signal = cursor.fetchone()

        if signal:
            # convert to a dict
            signal = dict(zip([desc[0] for desc in cursor.description], signal))
            # take out fractional seconds from timestamp
            signal['timestamp'] = signal['timestamp'].replace(microsecond=0)
            return signal
        else:
            return None
    except Exception as e:
        handle_ex(e, context="get_signal", service="webapp", extra_tags=['component:core'])
        raise
    
def update_signal(id, data_dict):
    try:
        db = get_db()
        sql = "UPDATE signals SET "
        for key, value in data_dict.items():
            sql += f"{key} = ?, "
        sql = sql[:-2] + " WHERE id = ?"
        cursor = db.cursor()
        cursor.execute(sql, tuple(data_dict.values()) + (id,))
        db.commit()
    except Exception as e:
        handle_ex(e, context="update_signal", service="webapp", extra_tags=['component:core'])
        raise

def should_skip_flat_signal(data_dict):
    """
    Check if this flat signal should be skipped. Cases to skip:
    1. Recent directional signal within 2 minutes
    2. Recent opposite directional signal (transition case) within 15 seconds
    Returns (should_skip, reason)
    """
    try:
        if data_dict['strategy'].get('market_position', '') != 'flat':
            return False, None
            
        # Get the previous position from the flat signal
        prev_position = data_dict['strategy'].get('prev_market_position', '')
        
        db = get_db()
        cursor = db.cursor()
        
        # First check: Look for any recent directional signal that's opposite to prev_position
        # This catches transition cases (long->short or short->long) where broker handles the flat
        if prev_position in ['long', 'short']:
            opposite_position = 'short' if prev_position == 'long' else 'long'
            cursor.execute("""
                SELECT * FROM signals 
                WHERE ticker = ? 
                AND bot = ? 
                AND market_position = ?
                AND timestamp > datetime(?, '-15 seconds')
                AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (
                data_dict['ticker'], 
                data_dict['strategy'].get('bot', ''),
                opposite_position,
                data_dict['strategy'].get('timestamp', datetime.datetime.now()),
                data_dict['strategy'].get('timestamp', datetime.datetime.now())
            ))
            
            transition_signal = cursor.fetchone()
            if transition_signal:
                return True, f"Skipping flat signal - found {opposite_position} transition signal"
        
        # Second check: Look for any recent non-flat signals (original check)
        cursor.execute("""
            SELECT * FROM signals 
            WHERE ticker = ? 
            AND bot = ? 
            AND market_position != 'flat'
            AND timestamp > datetime(?, '-2 minutes')
            AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (
            data_dict['ticker'], 
            data_dict['strategy'].get('bot', ''),
            data_dict['strategy'].get('timestamp', datetime.datetime.now()),
            data_dict['strategy'].get('timestamp', datetime.datetime.now())
        ))
        
        recent_signal = cursor.fetchone()
        if recent_signal:
            return True, f"Skipping flat signal - found recent {recent_signal[3]} signal from {recent_signal[1]}"
        
        return False, None
    except Exception as e:
        handle_ex(e, context="skip_flat_signal", service="webapp", extra_tags=['component:core'])
        raise

def schedule_signal_retry(data_dict, delay_seconds=30):
    """Schedule a signal to be re-sent after a delay"""
    try:
        retry_time = datetime.datetime.now() + timedelta(seconds=delay_seconds)
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO signal_retries 
            (original_signal_id, retry_time, signal_data, retries_remaining)
            VALUES (?, ?, ?, ?)
        """, (data_dict['strategy'].get('id'), retry_time, json.dumps(data_dict), 1))
        db.commit()
    except Exception as e:
        handle_ex(e, context="schedule_retry", service="webapp", extra_tags=['component:core'])
        raise

def process_signal_retries():
    """Process any signal retries that are due"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Get signals due for retry
        cursor.execute("""
            SELECT id, signal_data, retries_remaining, original_signal_id, retry_time
            FROM signal_retries 
            WHERE retry_time <= datetime('now') 
            AND retry_time >= datetime('now', '-3 minutes')
            AND retries_remaining > 0
        """)
        
        retries = cursor.fetchall()
        
        # Group retries by ticker and bot to find the most recent for each
        ticker_bot_retries = {}
        for retry in retries:
            retry_id, signal_data, retries_left, original_signal_id, retry_time = retry
            
            # Parse signal data
            signal_dict = json.loads(signal_data) if isinstance(signal_data, str) else signal_data
            
            ticker = signal_dict.get('ticker', '')
            bot = signal_dict['strategy'].get('bot', '')
            key = f"{ticker}_{bot}"
            
            # Get the original signal's timestamp from the database
            cursor.execute("SELECT timestamp FROM signals WHERE id = ?", (original_signal_id,))
            result = cursor.fetchone()
            if not result:
                continue
                
            original_timestamp = result[0]
            
            # Store each retry with its original signal timestamp
            if key not in ticker_bot_retries or original_timestamp > ticker_bot_retries[key]['timestamp']:
                ticker_bot_retries[key] = {
                    'retry': retry,
                    'timestamp': original_timestamp,
                    'signal_dict': signal_dict
                }
        
        # Process only the most recent signal retry for each ticker/bot combination
        for key, data in ticker_bot_retries.items():
            retry = data['retry']
            signal_dict = data['signal_dict']
            retry_id, signal_data, retries_left, original_signal_id, retry_time = retry
            
            try:
                # Skip if this is a flat signal and there's a directional signal within 10 seconds
                # Use the original signal timestamp, not the retry time
                if signal_dict['strategy'].get('market_position', '') == 'flat':
                    # Get original timestamp of this signal
                    cursor.execute("SELECT timestamp FROM signals WHERE id = ?", (original_signal_id,))
                    original_timestamp_result = cursor.fetchone()
                    if not original_timestamp_result:
                        continue
                    
                    original_timestamp = original_timestamp_result[0]
                    
                    cursor.execute("""
                        SELECT * FROM signals 
                        WHERE ticker = ? 
                        AND bot = ? 
                        AND market_position IN ('long', 'short')
                        AND timestamp BETWEEN datetime(?, '-10 seconds') AND datetime(?, '+10 seconds')
                        LIMIT 1
                    """, (
                        signal_dict['ticker'], 
                        signal_dict['strategy'].get('bot', ''),
                        original_timestamp,
                        original_timestamp
                    ))
                    
                    if cursor.fetchone():
                        app.logger.info(f"Skipping flat signal due to nearby directional signal")
                        cursor.execute("UPDATE signal_retries SET retries_remaining = 0 WHERE id = ?", (retry_id,))
                        db.commit()
                        continue
                
                # Add a log to show we're processing the most recent signal for this ticker/bot
                app.logger.info(f"Processing most recent signal retry for {signal_dict['ticker']}/{signal_dict['strategy'].get('bot', '')}")
                
                # Publish the signal
                signal_dict['is_retry'] = True
                app.logger.info(f"Publishing signal: {json.dumps(signal_dict, default=str)}")
                r.publish('tradingview', json.dumps(signal_dict))
                
                # Update retry count for this signal
                cursor.execute("""
                    UPDATE signal_retries 
                    SET retries_remaining = retries_remaining - 1
                    WHERE id = ?
                """, (retry_id,))
                
                # Mark ALL older signal retries for this ticker/bot as completed (0 retries)
                cursor.execute("""
                    UPDATE signal_retries sr
                    SET retries_remaining = 0
                    FROM signals s
                    WHERE sr.original_signal_id = s.id
                    AND s.ticker = ?
                    AND s.bot = ?
                    AND s.timestamp < ?
                    AND sr.retries_remaining > 0
                    AND sr.id != ?
                """, (signal_dict['ticker'], signal_dict['strategy'].get('bot', ''), data['timestamp'], retry_id))
                
            except Exception as e:
                handle_ex(e, context=f"process_retry_{retry_id}", service="webapp", extra_tags=['component:core'])
                continue
                
        db.commit()
    except Exception as e:
        handle_ex(e, context="process_retries", service="webapp", extra_tags=['component:core'])
        raise

def convert_to_position_pct_signal(data_dict):
    """Convert a TradingView signal to a position percentage signal"""
    signal = data_dict.copy()
    strategy = signal['strategy']
    
    # If the signal already has a position_pct defined, respect that value
    if 'position_pct' in strategy:
        # The signal already has a position percentage, so just return it as is
        return signal
    
    # Default to full position (100%) for standard entries
    position_pct = 100
    
    # Handle take-profit signals based on order comment
    if 'order_comment' in strategy:
        comment = strategy['order_comment']
        if comment == 'L1TPShort' or comment == 'L1TPLong':
            position_pct = 20  # TP1 = 20% of position
        elif comment == 'L2TPShort' or comment == 'L2TPLong':
            position_pct = 1   # TP2 = 1% of position
        # Handle explicit position size percentages in comment (e.g. "GoShort Stable 1% ")
        elif '%' in comment:
            try:
                # Extract the number before the % sign
                pct_str = comment.split('%')[0].split()[-1]
                position_pct = float(pct_str)
            except (ValueError, IndexError):
                # If we can't parse the percentage, use default
                pass
    
    # If going flat, set to 0%
    if strategy.get('market_position') == 'flat':
        position_pct = 0
        
    # Make position percentage negative for shorts
    if 'short' in strategy.get('market_position', '').lower():
        position_pct = -position_pct
        
    # Create new signal format
    signal['strategy']['position_pct'] = position_pct
    
    return signal

def save_signal(data_dict):
    try:
        # Convert signal to position percentage format
        data_dict = convert_to_position_pct_signal(data_dict)
        
        app.logger.info(f"Received signal: {json.dumps(data_dict, default=str)}")
        
        # Set retry times
        is_directional = data_dict['strategy'].get('market_position') in ['long', 'short']
        initial_retry_time = datetime.datetime.now() if is_directional else datetime.datetime.now() + timedelta(seconds=15)
        verification_retry_time = datetime.datetime.now() + timedelta(minutes=1)
        
        db = get_db()
        cursor = db.cursor()

        # If this is a directional signal, check for and invalidate recent flat signals
        if is_directional:
            cursor.execute("""
                WITH recent_flat AS (
                    SELECT id FROM signals 
                    WHERE ticker = ? 
                    AND bot = ? 
                    AND market_position = 'flat'
                    AND timestamp > datetime('now', '-15 seconds')
                )
                UPDATE signal_retries 
                SET retries_remaining = 0
                WHERE original_signal_id IN (SELECT id FROM recent_flat)
                AND retry_time > datetime('now')
            """, (
                data_dict['ticker'],
                data_dict['strategy'].get('bot', '')
            ))
            db.commit()
            app.logger.info(f"Invalidated any recent flat signals for {data_dict['ticker']}")
        
        # Cancel all pending verification retries for this ticker/bot combination
        # This ensures that if we get multiple signals in quick succession, only the most recent one will be verified
        cursor.execute("""
            UPDATE signal_retries
            SET retries_remaining = 0
            WHERE original_signal_id IN (
                SELECT id FROM signals
                WHERE ticker = ? AND bot = ?
            )
            AND retry_time > datetime('now')
        """, (
            data_dict['ticker'],
            data_dict['strategy'].get('bot', '')
        ))
        db.commit()
        app.logger.info(f"Cancelled any existing retry signals for {data_dict['ticker']}")
        
        cursor.execute("""
            INSERT INTO signals 
            (ticker, bot, order_action, order_contracts, market_position, 
             market_position_size, order_price, order_message, position_pct) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (data_dict['ticker'],
              data_dict['strategy'].get('bot', ''),
              data_dict['strategy'].get('order_action', ''),
              data_dict['strategy'].get('order_contracts', ''),
              data_dict['strategy'].get('market_position', ''),
              data_dict['strategy'].get('market_position_size', ''),
              data_dict['strategy'].get('order_price', ''),
              json.dumps(data_dict),
              data_dict['strategy'].get('position_pct')))
        id = cursor.lastrowid
        db.commit()
        app.logger.info(f"Signal recorded with ID: {id}")
        
        # Add the signal ID to the data
        data_dict['strategy']['id'] = id
        
        # Schedule initial execution
        cursor.execute("""
            INSERT INTO signal_retries 
            (original_signal_id, retry_time, signal_data, retries_remaining)
            VALUES (?, ?, ?, ?)
        """, (id, initial_retry_time, json.dumps(data_dict), 1))
        
        # Schedule verification retry
        verification_data = data_dict.copy()
        verification_data['is_retry'] = True
        cursor.execute("""
            INSERT INTO signal_retries 
            (original_signal_id, retry_time, signal_data, retries_remaining)
            VALUES (?, ?, ?, ?)
        """, (id, verification_retry_time, json.dumps(verification_data), 1))
        
        db.commit()
        app.logger.info(f"Signal scheduled for initial processing at {initial_retry_time} and verification at {verification_retry_time}")
        
        # Immediately publish directional signals to Redis
        if is_directional:
            signal_data = {
                'id': id,
                'ticker': data_dict['ticker'],
                'strategy': data_dict['strategy'],
                'timestamp': data_dict.get('timestamp', datetime.datetime.now().isoformat()),
                'is_retry': False
            }
            app.logger.info(f"Publishing directional signal immediately: {json.dumps(signal_data, default=str)}")
            r.publish('tradingview', json.dumps(signal_data, default=str))

    except Exception as e:
        handle_ex(e, context="save_signal", service="webapp", extra_tags=['component:core'])
        db.rollback()
        raise

