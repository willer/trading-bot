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



def handle_ex(e):
    account_sid = config['DEFAULT'].get('twilio-account-sid')
    auth_token = config['DEFAULT'].get('twilio-auth-token')
    from_phone = config['DEFAULT'].get('twilio-from-phone')
    to_phone = config['DEFAULT'].get('twilio-to-phone')
    if account_sid and auth_token and from_phone and to_phone:
        client = Client(account_sid, auth_token)
        # if e is a string send it, otherwise send the first 300 chars of the traceback
        message_body = f"broker-ibkr {bot} FAIL "
        message_body += e if isinstance(e, str) else traceback.format_exc()[:300]
        message = client.messages.create(
            body=message_body,
            from_=from_phone,
            to=to_phone
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

async def check_messages():

    #print(f"{time.time()} - checking for tradingview webhook messages")

    message = p.get_message()
    if message is not None and message['type'] == 'message':
        print("*** ",datetime.datetime.now())
        print(message)

        if message['data'] == b'health check':
            try:
                print("health check received")
                drivers_checked = {}
                for account in accounts:
                    aconfig = get_account_config(account)
                    if aconfig['driver'] == 'ibkr':
                        driver = broker_ibkr(bot, account)
                    elif aconfig['driver'] == 'alpaca':
                        driver = broker_alpaca(bot, account)
                    else:
                        raise Exception("Unknown driver: " + aconfig['driver'])

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
                return
            # special case: a manual trade is treated like a live trade
            if data_dict['strategy']['bot'].strip() == 'human':
                data_dict['strategy']['bot'] = bot
            if bot != data_dict['strategy']['bot']:
                print("signal intended for different bot '",data_dict['strategy']['bot'],"', skipping")
                return

            config.read('config.ini')

            ## extract data from TV payload received via webhook
            order_symbol_orig          = data_dict['ticker']                             # ticker for which TV order was sent
            order_symbol_lower         = order_symbol_orig.lower()                       # config variables coming from aconfig are lowercase
            market_position_orig       = data_dict['strategy']['market_position']        # order direction: long, short, flat, halflong, or halfshort
            market_position_size_orig  = data_dict['strategy']['market_position_size']   # desired position after order per TV
            signal_id = data_dict['strategy'].get('id', None)


            trades = []
            for account in accounts:
                ## PLACING THE ORDER

                print("")

                aconfig = get_account_config(account)
                driver: broker_root = None
                if aconfig['driver'] == 'ibkr':
                    driver = broker_ibkr(bot, account)
                elif aconfig['driver'] == 'alpaca':
                    driver = broker_alpaca(bot, account)
                else:
                    raise Exception("Unknown driver: " + aconfig['driver'])

                # set up variables for this account, normalizing market position to be positive or negative based on long or short
                # also check for futures before even checking price, as Alpaca doesn't support them at all
                order_symbol = order_symbol_orig
                desired_position = market_position_size_orig
                if "short" in market_position_orig: desired_position = -market_position_size_orig
                if "half" in market_position_orig: desired_position = round(desired_position / 2)
                print(f"** WORKING ON TRADE for account {account} symbol {order_symbol} to position {desired_position}")

                # check for futures permissions (default is allow)
                order_stock = driver.get_stock(order_symbol)
                if order_stock.is_futures and aconfig.get('use-futures', 'no') == 'no':
                    print("this account doesn't allow futures; skipping")
                    continue

                order_price = driver.get_price(order_symbol)

                if order_price == 0:
                    print("*** PRICE IS 0, SKIPPING")
                    continue

                # if this account needs different ETF's for short vs long, close the other side
                # or both if we're going flat
                if aconfig.get('use-inverse-etf', 'no') == 'yes':
                    if desired_position >= 0:
                        short_symbol = config['inverse-etfs'].get(order_symbol)
                        if short_symbol is not None:
                            await driver.set_position_size(short_symbol, 0)
                    if desired_position <= 0:
                        await driver.set_position_size(order_symbol, 0)

                current_position = driver.get_position_size(order_symbol)

                # check for account and security specific percentage of net liquidity in config
                # (if it's not a goflat order)
                if not order_stock.is_futures and desired_position != 0 and (f"{order_symbol_lower}-pct" in aconfig or f"default-pct" in aconfig):
                    if f"{order_symbol_lower}-pct" in aconfig:
                        percent = float(aconfig[f"{order_symbol_lower}-pct"])
                    else:
                        percent = float(aconfig["default-pct"])
                    # first, we find the value of the desired position in dollars, and set up some tiers
                    # to support various levels of take-profits
                    if round(abs(desired_position) * order_price) < 5000:
                        # assume it's a 99% take-profit level
                        percent = percent * 0.01
                    elif round(abs(desired_position) * order_price) < 35000:
                        # assume it's a 80% take-profit level
                        percent = percent * 0.2
                    # otherwise just go with the default full buy

                    # now we find the net liquidity in dollars
                    net_liquidity = driver.get_net_liquidity()
                    # and then we find the desired position in shares
                    print(f"new_desired_position = round({net_liquidity} * ({percent}/100) / {order_price})")
                    new_desired_position = abs(round(net_liquidity * (percent/100) / order_price))
                    if desired_position < 0: new_desired_position = -new_desired_position
                    print(f"using account specific net liquidity {percent}% for {order_symbol}: {desired_position} -> {new_desired_position}")
                    desired_position = new_desired_position
                else:
                    print(f"not using account specific net liquidity: is_futures={order_stock.is_futures} desired_position={desired_position} pctconfig={f'{order_symbol} pct' in aconfig}")

                # check for security conversion (generally futures to ETF); format is "mult x ETF"
                if order_symbol_lower in aconfig:
                    print("switching from ", order_symbol_orig, " to ", aconfig[order_symbol_lower])
                    [switchmult, x, order_symbol] = aconfig[order_symbol_lower].split()
                    switchmult = float(switchmult)
                    desired_position = round(desired_position * switchmult)
                    order_stock = driver.get_stock(order_symbol)
                    order_price = driver.get_price(order_symbol)

                # check for overall multipliers on the account, vs whatever position sizes are coming in from TV
                if not order_stock.is_futures and aconfig.get("multiplier", "") != "":
                    print("multiplying position by ",float(aconfig["multiplier"]))
                    desired_position = round(desired_position * float(aconfig["multiplier"]))

                # switch from short a long ETF to long a short ETF, if this account needs it
                if desired_position < 0 and aconfig.get('use-inverse-etf', 'no') == 'yes':
                    long_price = driver.get_price(order_symbol)
                    long_symbol = order_symbol
                    short_symbol = config['inverse-etfs'][order_symbol_lower]

                    # now continue with the short ETF
                    order_symbol = short_symbol
                    short_price = driver.get_price(order_symbol)
                    order_price = short_price
                    desired_position = abs(round(desired_position * long_price / short_price))
                    print(f"switching to inverse ETF {order_symbol}, to position {desired_position} at price ", order_price)

                # skip if two signals came out of order and we got a goflat after a non-goflat order
                current_time = datetime.datetime.now()
                last_time = datetime.datetime(1970,1,1)
                if order_symbol+bot in last_time_traded:
                    last_time = last_time_traded[order_symbol+bot+account] 
                delta = current_time - last_time
                last_time_traded[order_symbol+bot+account] = current_time

                if delta.total_seconds() < 120:
                    if desired_position == 0:
                        print("skipping order, seems to be a direction changing exit")
                        return

                current_position = driver.get_position_size(order_symbol)

                # now let's go ahead and place the order to reach the desired position
                if market_position_orig == "bracket":
                    print(f"** PLACING BRACKET ORDER for account {account} symbol {order_symbol}")
                    await driver.set_bracket(order_symbol)
                else:
                    if desired_position != current_position:
                        print(f"sending order to reach desired position of {desired_position} shares")
                        trades.append((driver, order_symbol, desired_position))
                    else:
                        print('desired quantity is the same as the current quantity.  No order placed.')

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

