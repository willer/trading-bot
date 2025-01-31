import configparser
import psycopg2

# Load config
config = configparser.ConfigParser()
config.read('config.ini')

# Connect to database
conn = psycopg2.connect(
    host=config['database']['database-host'],
    port=config['database']['database-port'],
    dbname=config['database']['database-name'],
    user=config['database']['database-user'],
    password=config['database']['database-password']
)

try:
    with conn.cursor() as cur:
        # Read and execute the migration
        with open('migrations/add_position_pct.sql', 'r') as f:
            migration_sql = f.read()
            cur.execute(migration_sql)
        conn.commit()
        print("Migration completed successfully")
except Exception as e:
    print(f"Error running migration: {e}")
    conn.rollback()
finally:
    conn.close() 