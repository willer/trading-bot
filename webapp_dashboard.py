import datetime
import hashlib
import os
import random
from flask import json, redirect, render_template, request, url_for
from webapp_core import app, get_db, get_signals, is_logged_in, r
from datetime import datetime, time as dt_time

@app.route('/dashboard')
def dashboard_page():
    return redirect('/dashboard/')

@app.get('/dashboard/')
def dashboard():
    if not is_logged_in():
        return redirect(url_for('login'))
    signals = get_signals()
    return render_template('dashboard.html', signals=signals, hashlib=hashlib, date=datetime)

def is_dangerous_time():
    now = datetime.now().time()
    return (dt_time(8, 25) <= now <= dt_time(10, 0)) or (dt_time(12, 0) <= now <= dt_time(16, 0))

@app.route('/confirm_action', methods=['GET'])
def confirm_action():
    if not is_logged_in():
        return redirect(url_for('login'))
    action = request.args.get('action')
    params = request.args.get('params')
    x = random.randint(-10, 30)
    y = random.randint(-10, 30)
    return render_template('confirm_action.html', action=action, params=params, x=x, y=y)

# POST /resend?hash=xxx
@app.post('/resend')
def resend():
    if not is_logged_in():
        return redirect(url_for('login'))
    if is_dangerous_time():
        return redirect(url_for('confirm_action', action='resend', params=request.form.get("hash")))

    signals = get_signals()
    for row in signals:
        if isinstance(row["order_message"], str):
            sha1hash = hashlib.sha1(row["order_message"].encode('utf-8')).hexdigest()
        else:
            sha1hash = hashlib.sha1(row["order_message"]).hexdigest()
        if request.form.get("hash") == sha1hash:
            r.publish('tradingview', row["order_message"])
            return "<html><body>Found it!<br><br><a href=/>Back to Home</a></body></html>"
    return "<html><body>Didn't find it!<br><br><a href=/>Back to Home</a></body></html>"

@app.post('/order')
def order():
    if not is_logged_in():
        return redirect(url_for('login'))
    if is_dangerous_time():
        params = f"{request.form.get('direction')},{request.form.get('ticker')}"
        return redirect(url_for('confirm_action', action='order', params=params))

    direction = request.form.get("direction")
    ticker = request.form.get("ticker")
    return process_order(direction, ticker)

def process_order(direction, ticker):
    position_size = 1000000
    if direction == "flat":
        position_size = 0
    # special case for futures, for now
    if direction != "flat":
        if ticker in ["NQ1!", "ES1!", "GC1!"]:
            position_size = 1

    # Message to send to the broker
    broker_message = {
        "ticker": ticker.upper(),
        "strategy": {
            "bot": "live",  # Send 'live' to the broker
            "market_position": direction,
            "market_position_size": position_size,
        }
    }
    r.publish('tradingview', json.dumps(broker_message))

    # Log the manual activity in the signals table
    db = get_db()
    cursor = db.cursor()
    
    # Message to log in the database
    log_message = {
        "ticker": ticker.upper(),
        "strategy": {
            "bot": "human",  # Log as 'human' in the database
            "market_position": direction,
            "market_position_size": position_size,
        }
    }
    
    cursor.execute("""
        INSERT INTO signals (ticker, bot, market_position, market_position_size, order_price, order_message) 
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (ticker.upper(), 
          "human",
          direction,
          position_size,
          "N/A",  # Placeholder for price
          json.dumps(log_message)))
    db.commit()

    return f"<html><body>Order submitted and logged!<br>{log_message}<br><a href=/>Back to Home</a></body></html>"

@app.route('/execute_action', methods=['POST'])
def execute_action():
    if not is_logged_in():
        return redirect(url_for('login'))
    action = request.form.get('action')
    params = request.form.get('params')

    if action == 'resend':
        return resend_action(params)
    elif action == 'order':
        direction, ticker = params.split(',')
        return process_order(direction, ticker)
    else:
        return f"<html><body>Unknown action '{action}'<br><br><a href=/>Back to Home</a></body></html>"

def resend_action(hash_value):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT order_message
        FROM signals
        order by timestamp desc
    """)
    signals = cursor.fetchall()
    for row in signals:
        if isinstance(row["order_message"], str):
            sha1hash = hashlib.sha1(row["order_message"].encode('utf-8')).hexdigest()
        else:
            sha1hash = hashlib.sha1(row["order_message"]).hexdigest()
        if hash_value == sha1hash:
            r.publish('tradingview', row["order_message"])
            return "<html><body>Found it!<br><br><a href=/>Back to Home</a></body></html>"
    return "<html><body>Didn't find it!<br><br><a href=/>Back to Home</a></body></html>"

# Modify these routes to require login
@app.post("/stop-backend")
def stop_backend():
    if not is_logged_in():
        return redirect(url_for('login'))
    # find the broker processes and kill them
    os.system("pkill -f start-broker-live.sh")
    os.system("pkill -f broker.py")

    return "<html><body>Done<br><br><a href=/>Back to Home</a></body></html>"

@app.post("/start-backend")
def start_backend():
    if not is_logged_in():
        return redirect(url_for('login'))
    # find the broker processes and kill them
    os.system("pkill -f start-broker-live.sh")
    os.system("pkill -f broker.py")

    # start the broker processes in the background
    if os.system("sh start-broker-live.sh &") != 0:
        return "<html><body>Failed to start IBKR broker<br><br><a href=/>Back to Home</a></body></html>"

    return "<html><body>Done<br><br><a href=/>Back to Home</a></body></html>"

# GET /show-logs-broker?tail=xxx
@app.get("/show-logs-broker")
def show_logs_ibkr():
    if not is_logged_in():
        return redirect(url_for('login'))
    tail = request.args.get("tail")
    if tail == None:
        tail = 100
    else:
        tail = int(tail)

    fname = "start-broker.sh.log"
    if os.path.exists(fname):
        with open(fname) as f:
            # read the last n lines
            lines = f.readlines()
            lines = lines[-tail:]
            lines = "".join(lines)
            return f"<html><body><h1>Broker Logs</h1><br><br><a href=/>Back to Home</a><br><br><pre>{lines}</pre></body></html>"
    else:
        return "<html><body>File not found<br><br><a href=/>Back to Home</a></body></html>"