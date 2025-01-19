import time
import psycopg2
from psycopg2 import pool
import redis, json
import asyncio, datetime
import sys
import nest_asyncio
import configparser
import traceback
from twilio.rest import Client
from datadog import initialize, statsd
from datadog.api import Event

nest_asyncio.apply()

from broker_root import broker_root
from broker_ibkr import broker_ibkr
from broker_alpaca import broker_alpaca


# arguments: broker.py [bot]
if len(sys.argv) != 2:
    print("Usage: " + sys.argv[0] + " [bot]")
    quit()

bot = sys.argv[1]

last_time_traded = {}

config = configparser.ConfigParser()
config.read('config.ini')


# Replace SQLite connection pool with PostgreSQL connection pool
db_pool = psycopg2.pool.SimpleConnectionPool(
    1, 20,
    host=config['database']['database-host'],
    port=config['database']['database-port'],
    dbname=config['database']['database-name'],
    user=config['database']['database-user'],
    password=config['database']['database-password']
)

dbconn = None
def get_db():
    global dbconn
    if dbconn is None:
        dbconn = db_pool.getconn()
    return dbconn

def update_signal(id, data_dict):
    db = get_db()
    sql = "UPDATE signals SET "
    for key, value in data_dict.items():
        sql += f"{key} = %s, "
    sql = sql[:-2] + " WHERE id = %s"
    cursor = db.cursor()
    cursor.execute(sql, tuple(data_dict.values()) + (id,))
    db.commit()



def handle_ex(e, context="unknown"):
    # Track error metric
    tags = [
        'service:broker',
        'error_context:' + context
    ]
    statsd.increment('broker.errors', tags=tags)
    
    # Send detailed event
    error_text = str(e) if isinstance(e, str) else traceback.format_exc()
    Event.create(
        title='Broker Error',
        text=f'Context: {context}\n\nError:\n{error_text}',
        alert_type='error',
        tags=tags
    )

# connect to Redis and subscribe to tradingview messages
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')

# figure out what account list to use, if any is specified
accountlist = config[f"bot-{bot}"]['accounts']
accounts = accountlist.split(",")


print("Waiting for webhook messages...")
async def execute_trades(trades):
    tasks = [driver.set_position_size(symbol, amount) for driver, symbol, amount in trades]
    order_ids = await asyncio.gather(*tasks)
    return list(zip([driver for driver, _, _ in trades], order_ids))

async def wait_for_trades(drivers_and_orders, signal_id, timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        incomplete_trades = []
        for driver, order_id in drivers_and_orders:
            if not await driver.is_trade_completed(order_id):
                incomplete_trades.append((driver, order_id))
        
        if not incomplete_trades:
            if signal_id:
                update_signal(signal_id, {'processed': datetime.datetime.now().isoformat()})
            print(f"All trades for signal {signal_id} completed")
            return True  # All trades completed
        
        drivers_and_orders = incomplete_trades
        await asyncio.sleep(1)
    
    return False  # Timeout reached, some trades incomplete

def get_account_config(account):
    config.read('config.ini')
    account_config = config[account]
    if 'group' in account_config:
        group = account_config['group']
        group_config = config[group]
        # Merge group config into account config, account config takes precedence
        merged_config = {**group_config, **account_config}
        return merged_config
    return account_config

# After setting up accounts list but before the message loop...

print("Initializing broker connections...")
drivers = {}
drivers_checked = {}  # Initialize the drivers_checked dictionary
connection_errors = []

for account in accounts:
    try:
        aconfig = get_account_config(account)
        print(f"\nInitializing connection for account {account} using {aconfig['driver']} driver...")
        
        if aconfig['driver'] == 'ibkr':
            driver = broker_ibkr(bot, account)
        elif aconfig['driver'] == 'alpaca':
            driver = broker_alpaca(bot, account)
        else:
            raise Exception(f"Unknown driver: {aconfig['driver']}")
            
        # Cache the driver instance
        drivers[account] = driver
        
    except Exception as e:
        error_msg = f"Failed to initialize {account}: {str(e)}"
        print(error_msg)
        handle_ex(e, f"broker_init_{account}")
        connection_errors.append((account, str(e)))

if connection_errors:
    error_summary = "\n".join([f"{account}: {error}" for account, error in connection_errors])
    handle_ex(
        f"Failed to initialize some broker connections:\n{error_summary}",
        "broker_initialization"
    )

async def check_messages():
    # Initialize Datadog
    config = configparser.ConfigParser()
    config.read('config.ini')
    initialize(
        api_key=config['DEFAULT'].get('datadog-api-key', ''),
        app_key=config['DEFAULT'].get('datadog-app-key', '')
    )

    try:
        message = p.get_message()
        if not message:
            return

        if message['type'] == 'message':
            try:
                if message['data'] == b'health check':
                    print("health check received")
                    health_check_errors = []
                    drivers_checked.clear()  # Reset the checked drivers for each health check

                    for account in accounts:
                        driver = drivers[account]
                        aconfig = get_account_config(account)

                        if aconfig['driver'] not in drivers_checked:
                            drivers_checked[aconfig['driver']] = True
                            print(f"health check for prices with driver {aconfig['driver']}")
                            try:
                                driver.health_check_prices()
                            except Exception as e:
                                error = f"Price check failed for {aconfig['driver']}: {str(e)}"
                                health_check_errors.append(error)
                                handle_ex(e, f"health_check_prices_{aconfig['driver']}")
                                print(f"health check failed: {e}, {traceback.format_exc()}")

                        print("checking positions for account",account)
                        try:
                            driver.health_check_positions()
                        except Exception as e:
                            error = f"Position check failed for {account}: {str(e)}"
                            health_check_errors.append(error)
                            handle_ex(e, f"health_check_positions_{account}")
                            print(f"health check failed: {e}, {traceback.format_exc()}")

                    if health_check_errors:
                        error_summary = "\n".join(health_check_errors)
                        handle_ex(
                            f"Health check failed with multiple errors:\n{error_summary}",
                            "health_check_summary"
                        )
                        r.publish('health', f'error: {error_summary}')
                    else:
                        r.publish('health', 'ok')
            except Exception as e:
                handle_ex(e, "health_check")
                print(f"health check failed: {e}, {traceback.format_exc()}")
                r.publish('health', f'error: {str(e)}')
    except Exception as e:
        handle_ex(e, "message_processing")
        print(f"Error processing message: {e}, {traceback.format_exc()}")

    return

runcount = 1
async def run_periodically(interval, periodic_function):
    global runcount
    while runcount < 3600:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        runcount = runcount + 1
    sys.exit()
asyncio.run(run_periodically(1, check_messages))

