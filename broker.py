import time
import psycopg2
from psycopg2 import pool
import redis, json
import asyncio, datetime
import sys
import nest_asyncio
import configparser
import traceback
import core_error

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
    core_error.handle_ex(e, "broker", context)


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
        handle_ex(error_msg)

async def check_messages():
    message = p.get_message()
    if message is not None and message['type'] == 'message':
        print("*** ",datetime.datetime.now())
        print(message)

        if message['data'] == b'health check':
            try:
                print("health check received")
                drivers_checked = {}
                for account in accounts:
                    driver = drivers[account]
                    aconfig = get_account_config(account)

                    if aconfig['driver'] not in drivers_checked:
                        drivers_checked[aconfig['driver']] = True
                        print(f"health check for prices with driver {aconfig['driver']}")
                        driver.health_check_prices()

                    print("checking positions for account",account)
                    driver.health_check_positions()

                r.publish('health', 'ok')
            except Exception as e:
                print(f"health check failed: {e}, {traceback.format_exc()}")
            return

        try:
            try:
                data_dict = json.loads(message['data'])
            except Exception as e:
                print("Error loading json: ",e)
                return

            if 'bot' not in data_dict['strategy']:
                raise Exception("You need to indicate the bot in the strategy portion of the json payload")
            # special case: a manual trade is treated like a live trade
            if data_dict['strategy']['bot'].strip() == 'human':
                data_dict['strategy']['bot'] = bot
            if bot != data_dict['strategy']['bot']:
                print("signal intended for different bot '",data_dict['strategy']['bot'],"', skipping")
                return

            if 'ticker' not in data_dict:
                raise Exception("No ticker found in signal data")

            config.read('config.ini')

            ## extract data from TV payload received via webhook
            order_symbol_orig = data_dict['ticker']                             # ticker for which TV order was sent
            order_symbol = order_symbol_orig  # Initialize order_symbol with original ticker
            order_symbol_lower = order_symbol_orig.lower()                      # config variables coming from aconfig are lowercase
            signal_position_pct = data_dict['strategy'].get('position_pct', 0)  # desired position percentage (-100 to 100)
            signal_id = data_dict['strategy'].get('id', None)

            trades = []
            for account in accounts:
                print("")

                aconfig = get_account_config(account)
                driver = drivers[account]

                # Reset order symbol and position percentage for each account
                order_symbol = order_symbol_orig
                position_pct = signal_position_pct

                # Initialize order_stock and price with original symbol first
                order_stock = driver.get_stock(order_symbol)
                order_price = driver.get_price(order_symbol)

                # Get the max configured percentage for this security and scale the signal
                if f"{order_symbol_lower}-pct" in aconfig:
                    config_value = aconfig[f"{order_symbol_lower}-pct"]
                    if ',' in config_value and aconfig.get('use-futures', 'no') == 'yes':
                        # Parse format like "1.5, NQ" into percentage and target symbol
                        pct_str, target_symbol = [x.strip() for x in config_value.split(',')]
                        # For flat positions, use 0. Otherwise preserve the sign from the signal
                        position_pct = 0 if signal_position_pct == 0 else float(pct_str) * (-1 if signal_position_pct < 0 else 1)
                        order_symbol = target_symbol
                        order_stock = driver.get_stock(order_symbol)
                        order_price = driver.get_price(order_symbol)
                    else:
                        max_pct = float(config_value.split(',')[0])
                        # Scale the position percentage by the max allowed percentage
                        position_pct = signal_position_pct * (max_pct / 100.0)
                else:
                    max_pct = float(aconfig.get("default-pct", "100"))
                    # Scale the position percentage by the max allowed percentage
                    position_pct = signal_position_pct * (max_pct / 100.0)
                
                print(f"Using position size of {position_pct}% for {order_symbol}")

                # check if the resulting order is for futures and if they're allowed
                if order_stock.is_futures and aconfig.get('use-futures', 'no') == 'no':
                    print("this account doesn't allow futures; skipping to inverse ETF logic")
                    order_symbol = order_symbol_orig  # Reset to original symbol
                    order_stock = driver.get_stock(order_symbol)  # Reset to original stock
                    order_price = driver.get_price(order_symbol)  # Reset to original price

                # if this account needs different ETF's for short vs long, close the other side
                # or both if we're going flat
                if aconfig.get('use-inverse-etf', 'no') == 'yes':
                    if position_pct >= 0:
                        short_symbol = config['inverse-etfs'].get(order_symbol)
                        if short_symbol is not None:
                            await driver.set_position_size(short_symbol, 0)
                    if position_pct <= 0:
                        await driver.set_position_size(order_symbol, 0)
                    
                    # If we're going flat (position_pct = 0), we've already closed everything
                    # so we can skip to the next account
                    if position_pct == 0:
                        print("Position closed via inverse ETF logic")
                        continue

                # check for overall multipliers on the account
                if not order_stock.is_futures and aconfig.get("multiplier", "") != "":
                    print("multiplying position by ",float(aconfig["multiplier"]))
                    position_pct = position_pct * float(aconfig["multiplier"])

                # switch from short a long ETF to long a short ETF, if this account needs it
                if position_pct < 0 and aconfig.get('use-inverse-etf', 'no') == 'yes':
                    long_price = driver.get_price(order_symbol)
                    long_symbol = order_symbol
                    short_symbol = config['inverse-etfs'][order_symbol_lower]

                    # now continue with the short ETF
                    order_symbol = short_symbol
                    short_price = driver.get_price(order_symbol)
                    order_price = short_price
                    position_pct = abs(position_pct)
                    print(f"switching to inverse ETF {order_symbol}, to position {position_pct}% at price ", order_price)

                # Calculate desired position size based on net liquidity and position percentage
                net_liquidity = driver.get_net_liquidity()
                
                # For micro futures, adjust the price to be 1/10th
                effective_price = order_price
                if order_stock.is_futures and order_symbol.startswith('M'):
                    effective_price = order_price / 10
                
                raw_position = (net_liquidity * (position_pct/100.0)) / effective_price
                desired_position = round(raw_position)
                
                print(f"Position calculation: {net_liquidity} * {position_pct}% / {effective_price} = {raw_position} -> {desired_position}")
                
                current_position = driver.get_position_size(order_symbol)

                # now let's go ahead and place the order to reach the desired position
                if desired_position != current_position:
                    print(f"sending order to reach desired position of {desired_position} shares")
                    trades.append((driver, order_symbol, desired_position))
                else:
                    print('desired quantity is the same as the current quantity. No order placed.')

            if trades:
                print("executing trades")
                drivers_and_orders = await execute_trades(trades)
                print("waiting for trades to complete")
                all_completed = await wait_for_trades(drivers_and_orders, signal_id)

                if not all_completed:
                    incomplete_accounts = [account for (driver, _), account in zip(drivers_and_orders, accounts) if not await driver.is_trade_completed(_)]
                    error_msg = f"ORDER FAILED: Timeout reached for accounts: {', '.join(incomplete_accounts)}"
                    print(error_msg)
                    handle_ex(error_msg)
                else:
                    print("All orders filled successfully")

        except Exception as e:
            handle_ex(e)
            raise

runcount = 1
async def run_periodically(interval, periodic_function):
    global runcount
    while runcount < 3600:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        runcount = runcount + 1
    sys.exit()
asyncio.run(run_periodically(1, check_messages))

