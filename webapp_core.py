import configparser
import psycopg2
from flask import Flask, g, json, session
from flask_sqlalchemy import SQLAlchemy
import redis
from psycopg2 import pool
import datetime
from datetime import timedelta
import asyncio
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

# Replace SQLite connection pool with PostgreSQL connection pool
db_pool = psycopg2.pool.SimpleConnectionPool(
    1, 20,
    host=config['database']['database-host'],
    port=config['database']['database-port'],
    dbname=config['database']['database-name'],
    user=config['database']['database-user'],
    password=config['database']['database-password']
)

def get_db():
    try:
        if 'db' not in g:
            g.db = db_pool.getconn()
        return g.db
    except Exception as e:
        handle_ex(e, context="database_connection", service="webapp", extra_tags=['component:core'])
        raise

@app.teardown_appcontext
def close_db(error):
    try:
        db = g.pop('db', None)
        if db is not None:
            db_pool.putconn(db)
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

        # Take out fractional seconds from timestamp
        for signal in signals:
            signal['timestamp'] = signal['timestamp'].replace(microsecond=0)

        return signals
    except Exception as e:
        handle_ex(e, context="get_signals", service="webapp", extra_tags=['component:core'])
        raise

def get_signal(id):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM signals WHERE id = %s", (id,))
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
            sql += f"{key} = %s, "
        sql = sql[:-2] + " WHERE id = %s"
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
                WHERE ticker = %s 
                AND bot = %s 
                AND market_position = %s
                AND timestamp > %s - INTERVAL '15 seconds'
                AND timestamp <= %s
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
            WHERE ticker = %s 
            AND bot = %s 
            AND market_position != 'flat'
            AND timestamp > %s - INTERVAL '2 minutes'
            AND timestamp <= %s
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
            VALUES (%s, %s, %s, %s)
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
            WHERE retry_time <= NOW() 
            AND retry_time >= NOW() - INTERVAL '3 minutes'
            AND retries_remaining > 0
        """)
        
        retries = cursor.fetchall()
        for retry in retries:
            try:
                retry_id, signal_data, retries_left, original_signal_id, retry_time = retry
                
                # Parse signal data
                signal_dict = json.loads(signal_data) if isinstance(signal_data, str) else signal_data
                
                # Skip if this is a flat signal and there's a directional signal within 3 seconds
                if signal_dict['strategy'].get('market_position', '') == 'flat':
                    cursor.execute("""
                        SELECT * FROM signals 
                        WHERE ticker = %s 
                        AND bot = %s 
                        AND market_position IN ('long', 'short')
                        AND timestamp BETWEEN %s - INTERVAL '3 seconds' AND %s + INTERVAL '3 seconds'
                        LIMIT 1
                    """, (
                        signal_dict['ticker'], 
                        signal_dict['strategy'].get('bot', ''),
                        retry_time,
                        retry_time
                    ))
                    
                    if cursor.fetchone():
                        app.logger.info(f"Skipping flat signal due to nearby directional signal")
                        cursor.execute("UPDATE signal_retries SET retries_remaining = 0 WHERE id = %s", (retry_id,))
                        db.commit()
                        continue
                
                # Publish the signal
                signal_dict['is_retry'] = True
                app.logger.info(f"Publishing signal: {json.dumps(signal_dict, default=str)}")
                r.publish('tradingview', json.dumps(signal_dict))
                
                # Update retry count
                cursor.execute("""
                    UPDATE signal_retries 
                    SET retries_remaining = retries_remaining - 1
                    WHERE id = %s
                """, (retry_id,))
                
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
        
        # Set retry time - immediate for directional signals, delayed for flat
        is_directional = data_dict['strategy'].get('market_position') in ['long', 'short']
        retry_time = datetime.datetime.now() if is_directional else datetime.datetime.now() + timedelta(seconds=15)
        
        db = get_db()
        cursor = db.cursor()

        # If this is a directional signal, check for and invalidate recent flat signals
        if is_directional:
            cursor.execute("""
                WITH recent_flat AS (
                    SELECT id FROM signals 
                    WHERE ticker = %s 
                    AND bot = %s 
                    AND market_position = 'flat'
                    AND timestamp > NOW() - INTERVAL '15 seconds'
                )
                UPDATE signal_retries 
                SET retries_remaining = 0
                WHERE original_signal_id IN (SELECT id FROM recent_flat)
                AND retry_time > NOW()
            """, (
                data_dict['ticker'],
                data_dict['strategy'].get('bot', '')
            ))
            db.commit()
            app.logger.info(f"Invalidated any recent flat signals for {data_dict['ticker']}")
        
        cursor.execute("""
            INSERT INTO signals 
            (ticker, bot, order_action, order_contracts, market_position, 
             market_position_size, order_price, order_message, position_pct) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (data_dict['ticker'],
              data_dict['strategy'].get('bot', ''),
              data_dict['strategy'].get('order_action', ''),
              data_dict['strategy'].get('order_contracts', ''),
              data_dict['strategy'].get('market_position', ''),
              data_dict['strategy'].get('market_position_size', ''),
              data_dict['strategy'].get('order_price', ''),
              json.dumps(data_dict),
              data_dict['strategy'].get('position_pct')))
        db.commit()
        id = cursor.fetchone()[0]
        app.logger.info(f"Signal recorded with ID: {id}")
        
        # Add the signal ID to the data
        data_dict['strategy']['id'] = id
        
        # Schedule for processing - directional signals get 1 retry, flat signals also get 1 retry
        cursor.execute("""
            INSERT INTO signal_retries 
            (original_signal_id, retry_time, signal_data, retries_remaining)
            VALUES (%s, %s, %s, %s)
        """, (id, retry_time, json.dumps(data_dict), 1))
        db.commit()
        app.logger.info(f"Signal scheduled for processing at {retry_time}")

    except Exception as e:
        handle_ex(e, context="save_signal", service="webapp", extra_tags=['component:core'])
        db.rollback()
        raise



