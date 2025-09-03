#!/usr/bin/env python3
"""
Migrate from PostgreSQL back to SQLite
"""
import sqlite3
import psycopg2
import configparser
import json
from datetime import datetime

# Read config
config = configparser.ConfigParser()
config.read('config.ini')

def migrate_to_sqlite():
    print("Starting migration from PostgreSQL to SQLite...")
    
    # Connect to PostgreSQL
    pg_conn = psycopg2.connect(
        host=config['DEFAULT']['database-host'],
        port=config['DEFAULT']['database-port'],
        dbname=config['DEFAULT']['database-name'],
        user=config['DEFAULT']['database-user'],
        password=config['DEFAULT']['database-password']
    )
    pg_cur = pg_conn.cursor()
    
    # Create new SQLite database
    sqlite_conn = sqlite3.connect('trade_new.db')
    sqlite_cur = sqlite_conn.cursor()
    
    # Create signals table in SQLite
    sqlite_cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            bot TEXT,
            order_action TEXT,
            order_contracts TEXT,
            market_position TEXT,
            market_position_size TEXT,
            order_price TEXT,
            order_message TEXT,
            processed TIMESTAMP DEFAULT NULL,
            skipped TEXT DEFAULT NULL,
            position_pct REAL
        )
    """)
    
    # Create signal_retries table in SQLite
    sqlite_cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_retries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_signal_id INTEGER REFERENCES signals(id) ON DELETE CASCADE,
            retry_time TIMESTAMP NOT NULL,
            signal_data TEXT NOT NULL,
            retries_remaining INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create index on retry_time
    sqlite_cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_retries_retry_time 
        ON signal_retries(retry_time)
        WHERE retries_remaining > 0
    """)
    
    # Migrate signals table
    print("Migrating signals table...")
    pg_cur.execute("""
        SELECT id, timestamp, ticker, bot, order_action, order_contracts, 
               market_position, market_position_size, order_price, order_message,
               processed, skipped, position_pct
        FROM signals
        ORDER BY id
    """)
    
    rows = pg_cur.fetchall()
    print(f"Found {len(rows)} signals to migrate")
    
    for row in rows:
        # Handle NULL values and data types
        processed_row = list(row)
        # Convert timestamp to string if needed
        if processed_row[1]:
            processed_row[1] = str(processed_row[1])
        if processed_row[10]:  # processed timestamp
            processed_row[10] = str(processed_row[10])
            
        sqlite_cur.execute("""
            INSERT INTO signals (id, timestamp, ticker, bot, order_action, order_contracts,
                               market_position, market_position_size, order_price, order_message,
                               processed, skipped, position_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, processed_row)
    
    # Migrate signal_retries table
    print("Migrating signal_retries table...")
    pg_cur.execute("""
        SELECT id, original_signal_id, retry_time, signal_data, 
               retries_remaining, created_at
        FROM signal_retries
        ORDER BY id
    """)
    
    retry_rows = pg_cur.fetchall()
    print(f"Found {len(retry_rows)} signal retries to migrate")
    
    for row in retry_rows:
        processed_row = list(row)
        # Convert timestamps to strings
        if processed_row[2]:
            processed_row[2] = str(processed_row[2])
        if processed_row[5]:
            processed_row[5] = str(processed_row[5])
        # Convert JSONB to JSON string
        if processed_row[3]:
            processed_row[3] = json.dumps(processed_row[3])
            
        sqlite_cur.execute("""
            INSERT INTO signal_retries (id, original_signal_id, retry_time, signal_data,
                                      retries_remaining, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, processed_row)
    
    # Update SQLite sequence to match the last ID
    if rows:
        last_signal_id = rows[-1][0]
        sqlite_cur.execute(f"UPDATE sqlite_sequence SET seq = {last_signal_id} WHERE name = 'signals'")
    
    if retry_rows:
        last_retry_id = retry_rows[-1][0]
        sqlite_cur.execute(f"UPDATE sqlite_sequence SET seq = {last_retry_id} WHERE name = 'signal_retries'")
    
    # Commit and close connections
    sqlite_conn.commit()
    sqlite_conn.close()
    pg_conn.close()
    
    print("Migration completed successfully!")
    print("New SQLite database saved as: trade_new.db")
    print("\nNext steps:")
    print("1. Stop the trading services")
    print("2. Backup the old trade.db (if it exists)")
    print("3. Rename trade_new.db to trade.db")
    print("4. Update code to use SQLite instead of PostgreSQL")
    print("5. Test the system")

if __name__ == "__main__":
    migrate_to_sqlite()