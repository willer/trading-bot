
import configparser
import hashlib
import math
import os
import sqlite3
import time
from flask import Flask, g, session
from flask_sqlalchemy import SQLAlchemy
import redis


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

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('trade.db')
        g.db.row_factory = sqlite3.Row

    return g.db

# initial setup of db (if it doesn't exist)
conn = sqlite3.connect('trade.db')
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
        ticker,
        order_action,
        order_contracts,
        order_price,
        order_message text
    )
""")
conn.commit()

# migrations for db, if you have older schemas
cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN order_message text")
    conn.commit()
except: pass

cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN bot text")
    conn.commit()
except: pass

cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN market_position text")
    conn.commit()
except: pass

cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN market_position_size text")
    conn.commit()
except: pass


@app.context_processor
def add_imports():
    # Note: we only define the top-level module names!
    return dict(hashlib=hashlib, time=time, os=os, math=math)

## ROUTES

# New function to check if user is logged in
def is_logged_in():
    return session.get('logged_in', False)
