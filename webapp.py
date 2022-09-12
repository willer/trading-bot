import redis, sqlite3, time, os

import asyncio, time, random
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from ib_insync import *
from flask import Flask, render_template, request, g, current_app

app = Flask(__name__)

run_ibkr = True
run_alpaca = True

if run_ibkr:
    # connect to Interactive Brokers (try all 4 options)
    ib = IB()
    print("Trying to connect to IBKR...")
    try:
        if not ib.isConnected(): ib.connect('127.0.0.1', 7496, clientId=1) # live account on IB TW
        print("connected to live TW")
    except: a=1
    try:
        if not ib.isConnected(): ib.connect('127.0.0.1', 4001, clientId=1) # live account on IB gateway
        print("connected to live Gateway")
    except: a=1
    try:
        if not ib.isConnected(): ib.connect('127.0.0.1', 7497, clientId=1) # paper account on IB TW
        print("connected to paper TW")
    except: a=1
    try:
        if not ib.isConnected(): ib.connect('127.0.0.1', 4002, clientId=1) # paper account on IB gateway
        print("connected to paper Gateway")
    except: a=1
    if not ib.isConnected():
        raise Exception("** IB TW and IB gateway are not running, in live or paper configurations")
    

conn = sqlite3.connect('trade.db')
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
        ticker,
        order_action,
        order_contracts,
        order_price
    )
""")
conn.commit()

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('trade.db')
        g.db.row_factory = sqlite3.Row

    return g.db

@app.get('/')
def dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM signals
    """)
    signals = cursor.fetchall()

    return render_template('dashboard.html', signals=signals)

@app.post("/webhook")
def webhook():
    data = request.data

    if data:
        #print('got message: ' + request.get_data())

        if run_ibkr:
            # Normalization -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
            if data['ticker'] == 'NQ1!':
                stock = Future('MNQ', '20220916', 'GLOBEX') # go with mini futures for Q's for now, keep risk managed
            elif data['ticker'] == 'QQQ': # assume QQQ->NQ (sometimes QQQ signals are helpful for gap plays)
                stock = Future('NQ', '20220916', 'GLOBEX')
                if (order_count > 0):
                    order_count = 1
                else:
                    order_count = -1
            elif data['ticker'] == 'ES1!':
                stock = Future('MES', '20220916', 'GLOBEX') # go with mini futures for now
            elif data['ticker'] == 'SPY': # assume SPY->ES
                stock = Future('ES', '20220916', 'GLOBEX')
                if (order_count > 0):
                    order_count = 1
                else:
                    order_count = -1
            elif data['ticker'] == 'RTY1!':
                stock = Future('M2K', '20220916', 'GLOBEX') # go with mini futures for now
            elif data['ticker'] == 'CL1!':
                stock = Future('CL', '20220920', 'NYMEX')
            elif data['ticker'] == 'NG1!':
                stock = Future('NG', '20220920', 'NYMEX')
            elif data['ticker'] == 'HG1!':
                stock = Future('HG', '20220928', 'NYMEX')
            elif data['ticker'] == '6J1!':
                stock = Future('J7', '20220919', 'GLOBEX')
            elif data['ticker'] == 'HEN2022':
                stock = Future('HE', '20220715', 'NYMEX')
            else:
                stock = Stock(data['ticker'], 'SMART', 'USD')

            order = MarketOrder(data['strategy']['order_action'], data['strategy']['order_contracts'])
            #ib.qualifyOrder(order)
            trade = ib.placeOrder(stock, order)
            print(trade)



        data_dict = request.json

        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO signals (ticker, order_action, order_contracts, order_price) 
            VALUES (?, ?, ?, ?)
        """, (data_dict['ticker'], 
                data_dict['strategy']['order_action'], 
                data_dict['strategy']['order_contracts'],
                data_dict['strategy']['order_price']))

        db.commit()

        return data

    return {
        "code": "success"
    }
