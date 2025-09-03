import sqlite3
# SQLite autocommits by default
import sqlite3
from webapp_core import config
# # SQLite doesn't need connection pooling  # Not needed for SQLite

def create_postgres_db():
    conn = psycopg2.connect(
        host=config['database']['database-host'],
        port=config['database']['database-port'],
        user=config['database']['database-admin-user'],
        password=config['database']['database-admin-password']
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE {config['database']['database-name']}")
    cur.close()
    conn.close()

def create_tables():
    conn = psycopg2.connect(
        host=config['database']['database-host'],
        port=config['database']['database-port'],
        dbname=config['database']['database-name'],
        user=config['database']['database-user'],
        password=config['database']['database-password']
    )
    cur = conn.cursor()
    
    # Create the signals table if it doesn't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            bot TEXT,
            order_action TEXT,
            order_contracts TEXT,
            market_position TEXT,
            market_position_size TEXT,
            order_price TEXT,
            order_message TEXT
        )
    """)
    
    # Check if the 'id' column exists, and add it if it doesn't
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='signals' AND column_name='id'
    """)
    if cur.fetchone() is None:
        cur.execute("""
            ALTER TABLE signals
            ADD COLUMN id SERIAL PRIMARY KEY
        """)
        print("Added 'id' column to signals table.")
        
        # Create a unique index on the id column
        cur.execute("""
            CREATE UNIQUE INDEX signals_id_idx ON signals (id)
        """)
        print("Created unique index on 'id' column.")
        
        # Seed existing records with unique id values
        cur.execute("""
            UPDATE signals
            SET id = DEFAULT
            WHERE id IS NULL
        """)
        print("Seeded existing records with unique id values.")
    
    # Check if the 'processed' column exists, and add it if it doesn't
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='signals' AND column_name='processed'
    """)
    if cur.fetchone() is None:
        cur.execute("""
            ALTER TABLE signals
            ADD COLUMN processed TIMESTAMP DEFAULT NULL
        """)
        print("Added 'processed' column to signals table.")

    # Check if the 'skipped' column exists, and add it if it doesn't
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='signals' AND column_name='skipped'
    """)
    if cur.fetchone() is None:
        cur.execute("""
            ALTER TABLE signals
            ADD COLUMN skipped TEXT DEFAULT NULL
        """)
        print("Added 'skipped' column to signals table.")

    # Create the signal_retries table if it doesn't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_retries (
            id SERIAL PRIMARY KEY,
            original_signal_id INTEGER REFERENCES signals(id) ON DELETE CASCADE,
            retry_time TIMESTAMP NOT NULL,
            signal_data JSONB NOT NULL,
            retries_remaining INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("Created signal_retries table if it didn't exist.")

    # Create index on retry_time for better performance
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_retries_retry_time 
        ON signal_retries(retry_time)
        WHERE retries_remaining > 0
    """)
    print("Created index on signal_retries retry_time if it didn't exist.")
    
    conn.commit()
    cur.close()
    conn.close()

def migrate_data():
    sqlite_conn = sqlite3.connect('trade.db')
    sqlite_cur = sqlite_conn.cursor()
    
    pg_conn = psycopg2.connect(
        host=config['database']['database-host'],
        port=config['database']['database-port'],
        dbname=config['database']['database-name'],
        user=config['database']['database-user'],
        password=config['database']['database-password']
    )
    pg_cur = pg_conn.cursor()
    
    # Check if the signals table is empty
    pg_cur.execute("SELECT COUNT(*) FROM signals")
    count = pg_cur.fetchone()[0]
    
    if count == 0:
        sqlite_cur.execute("SELECT timestamp, ticker, bot, order_action, order_contracts, market_position, market_position_size, order_price, order_message FROM signals")
        rows = sqlite_cur.fetchall()
        
        for row in rows:
            pg_cur.execute("""
                INSERT INTO signals (timestamp, ticker, bot, order_action, order_contracts, market_position, market_position_size, order_price, order_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
        
        pg_conn.commit()
        print("Data migration completed successfully.")
    else:
        print("Signals table is not empty. Skipping data migration.")
    
    sqlite_cur.close()
    sqlite_conn.close()
    pg_cur.close()
    pg_conn.close()

def run_migration():
    try:
        create_postgres_db()
    except psycopg2.errors.DuplicateDatabase:
        print("Database already exists, skipping creation.")
    
    create_tables()
    
    try:
        migrate_data()
        print("Data migration completed successfully.")
    except sqlite3.OperationalError:
        print("SQLite database not found or empty. Skipping data migration.")

if __name__ == "__main__":
    run_migration()