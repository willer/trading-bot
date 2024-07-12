import streamlit as st
import json
import pandas as pd
import redis
import sqlite3
import os
import hashlib

# Initialize Redis
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('health')
p.get_message(timeout=3)

# Function to get the database connection
def get_db():
    conn = sqlite3.connect('trade.db')
    conn.row_factory = sqlite3.Row
    return conn

# Function to display the dashboard
def dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT datetime(timestamp, 'localtime') as timestamp,
        ticker,
        bot,
        order_action,
        order_contracts,
        market_position,
        market_position_size,
        order_price,
        order_message
        FROM signals
        order by timestamp desc
        LIMIT 500
    """)
    signals = cursor.fetchall()
    st.title("Dashboard")
    df = pd.DataFrame(signals)
    st.dataframe(df)

# Function to handle resend
def resend():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT order_message
        FROM signals
        order by timestamp desc
    """)
    signals = cursor.fetchall()
    hash_to_find = st.text_input("Enter hash to resend:")
    if st.button("Resend"):
        for row in signals:
            if hash_to_find == hashlib.sha1(row["order_message"]).hexdigest():
                r.publish('tradingview', row["order_message"])
                st.write("Found it!")
                return
        st.write("Didn't find it!")

# Function to handle order
def order():
    direction = st.selectbox("Direction", ["long", "short", "none"])
    ticker = st.text_input("Ticker")
    if direction in ["long", "short"]:
        position_size = 1000000
    else:
        position_size = 0

    message = {
        "ticker": ticker.upper(),
        "strategy": {
            "bot": "live",
            "market_position": direction,
            "market_position_size": position_size,
        }
    }
    if st.button("Send Order"):
        r.publish('tradingview', json.dumps(message))
        st.write("Sent!", message)

# Function to handle webhook
def webhook():
    query_params = st.experimental_get_query_params()
    data = query_params.get("data", [None])[0]
    if data:
        r.publish('tradingview', data)
        data_dict = json.loads(data)
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO signals (ticker, bot, order_action, order_contracts, market_position, market_position_size, order_price, order_message) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (data_dict['ticker'], 
                data_dict['strategy']['bot'],
                data_dict['strategy']['order_action'], 
                data_dict['strategy']['order_contracts'],
                data_dict['strategy']['market_position'],
                data_dict['strategy']['market_position_size'],
                data_dict['strategy']['order_price'],
                data))
        db.commit()
        st.write("Webhook data sent and saved!")
    else:
        st.write("No webhook data received.")

# Function to check health
def health():
    r.publish('tradingview', 'health check')
    message = p.get_message(timeout=15)
    if message and message['type'] == 'message':
        st.write({"code": "success"})
    elif message:
        st.write({"code": "failure", "message-type": message['type'], "message": message['data']}, 500)
    else:
        st.write({"code": "failure", "message-type": "timeout", "message": "no message received"}, 500)

# Streamlit app layout
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Resend", "Order", "Webhook", "Health"])

if page == "Dashboard":
    dashboard()
elif page == "Resend":
    resend()
elif page == "Order":
    order()
elif page == "Webhook":
    webhook()
elif page == "Health":
    health()
