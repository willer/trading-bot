import configparser
import psycopg2
from flask import Flask, g, json, session
from flask_sqlalchemy import SQLAlchemy
import redis
from psycopg2 import pool
import datetime
from datetime import timedelta
import asyncio

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trade.db'
app.config['SECRET_KEY'] = 'your_secret_key_here'  # Add this line
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
    if 'db' not in g:
        g.db = db_pool.getconn()
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db_pool.putconn(db)

## ROUTES

# New function to check if user is logged in
def is_logged_in():
    return session.get('logged_in', False)

def get_signals():
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

def get_signal(id):
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
    
def update_signal(id, data_dict):
    db = get_db()
    sql = "UPDATE signals SET "
    for key, value in data_dict.items():
        sql += f"{key} = %s, "
    sql = sql[:-2] + " WHERE id = %s"
    cursor = db.cursor()
    cursor.execute(sql, tuple(data_dict.values()) + (id,))
    db.commit()

def should_skip_flat_signal(data_dict):
    """
    Check if this flat signal should be skipped due to recent directional signals
    Returns (should_skip, reason)
    """
    if data_dict['strategy'].get('market_position', '') != 'flat':
        return False, None
        
    # Look for recent non-flat signals for this symbol and bot
    db = get_db()
    cursor = db.cursor()
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

def schedule_signal_retry(data_dict, delay_seconds=30):
    """Schedule a signal to be re-sent after a delay"""
    retry_time = datetime.datetime.now() + timedelta(seconds=delay_seconds)
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO signal_retries 
        (original_signal_id, retry_time, signal_data, retries_remaining)
        VALUES (%s, %s, %s, %s)
    """, (data_dict['strategy'].get('id'), retry_time, json.dumps(data_dict), 1))
    db.commit()

def process_signal_retries():
    """Process any signal retries that are due"""
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
        
    db.commit()

def save_signal(data_dict):
    app.logger.info(f"Received signal: {json.dumps(data_dict, default=str)}")  # Debug log
    
    # Set retry time to 3 seconds from now
    retry_time = datetime.datetime.now() + timedelta(seconds=3)
    
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO signals 
            (ticker, bot, order_action, order_contracts, market_position, 
             market_position_size, order_price, order_message) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (data_dict['ticker'],
              data_dict['strategy'].get('bot', ''),
              data_dict['strategy'].get('order_action', ''),
              data_dict['strategy'].get('order_contracts', ''),
              data_dict['strategy'].get('market_position', ''),
              data_dict['strategy'].get('market_position_size', ''),
              data_dict['strategy'].get('order_price', ''),
              json.dumps(data_dict)))
        db.commit()
        id = cursor.fetchone()[0]
        app.logger.info(f"Signal recorded with ID: {id}")  # Debug log
        
        # Add the signal ID to the data
        data_dict['strategy']['id'] = id
        
        # Schedule for processing
        cursor.execute("""
            INSERT INTO signal_retries 
            (original_signal_id, retry_time, signal_data, retries_remaining)
            VALUES (%s, %s, %s, %s)
        """, (id, retry_time, json.dumps(data_dict), 1))
        db.commit()
        app.logger.info(f"Signal scheduled for processing at {retry_time}")  # Debug log

    except Exception as e:
        app.logger.info(f"Error processing signal: {str(e)}")  # Debug log
        db.rollback()



