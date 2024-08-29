import configparser
import psycopg2
from flask import Flask, g, session
from flask_sqlalchemy import SQLAlchemy
import redis
from psycopg2 import pool

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

def publish_signal(data_dict):
    r.publish('tradingview', data_dict)

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO signals (ticker, bot, order_action, order_contracts, market_position, market_position_size, order_price, order_message) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (data_dict['ticker'], 
            data_dict['strategy']['bot'],
            data_dict['strategy']['order_action'], 
            data_dict['strategy']['order_contracts'],
            data_dict['strategy']['market_position'],))
    db.commit()
