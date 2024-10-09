import datetime
import hashlib
import os
import random
from flask import json, redirect, render_template, request, url_for
from webapp_core import app, get_db, get_signal, get_signals, is_logged_in, publish_signal, r
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
    return (dt_time(8, 20) <= now <= dt_time(9, 45)) or (dt_time(12, 0) <= now <= dt_time(16, 0))

@app.route('/confirm_action', methods=['GET'])
def confirm_action():
    if not is_logged_in():
        return redirect(url_for('login'))
    action = request.args.get('action')
    params = request.args.get('params')
    x = random.randint(-10, 30)
    y = random.randint(-10, 30)
    return render_template('confirm_action.html', action=action, params=params, x=x, y=y)

# POST /resend?id=xxx
# resend a signal to the broker
@app.post('/resend')
def resend():
    if not is_logged_in():
        return redirect(url_for('login'))
    if is_dangerous_time():
        return redirect(url_for('confirm_action', action='resend', params=request.form.get("hash")))

    id = int(request.form.get("id"))
    signal = get_signal(id)
    if signal:
        data_dict = json.loads(signal["order_message"])
        publish_signal(signal)
        return render_template('action_response.html', message="Signal resent successfully!", redirect_url=url_for('dashboard'))
    else:
        return render_template('action_response.html', message="Signal not found!", redirect_url=url_for('dashboard'))

# POST /order
# manual order submission
@app.post('/order')
def order():
    if not is_logged_in():
        return redirect(url_for('login'))
    if is_dangerous_time():
        params = f"{request.form.get('direction')},{request.form.get('ticker')}"
        return redirect(url_for('confirm_action', action='order', params=params))

    direction = request.form.get("direction")
    ticker = request.form.get("ticker")
    tickers = ticker.split(';')
    for ticker in tickers:
        process_order(direction, ticker)
    return render_template('action_response.html', message="Orders submitted and logged!", redirect_url=url_for('dashboard'))

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
            "bot": "human",  # Send 'live' to the broker
            "market_position": direction,
            "market_position_size": position_size,
        }
    }
    publish_signal(broker_message)


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
        tickers = ticker.split(';')
        for ticker in tickers:
            process_order(direction, ticker)
        return render_template('action_response.html', message="Orders submitted and logged!", redirect_url=url_for('dashboard'))
    else:
        return render_template('action_response.html', message=f"Unknown action '{action}'", redirect_url=url_for('dashboard'))

def resend_action(id):
    signal = get_signal(id)
    if signal:
        data_dict = json.loads(signal["order_message"])
        publish_signal(data_dict)
        return render_template('action_response.html', message="Signal resent successfully!", redirect_url=url_for('dashboard'))
    else:
        return render_template('action_response.html', message="Signal not found!", redirect_url=url_for('dashboard'))

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