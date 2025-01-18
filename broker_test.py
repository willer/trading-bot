import redis, json
import asyncio, datetime
import sys
import nest_asyncio
import configparser
import traceback

nest_asyncio.apply()

from broker_root import broker_root
from broker_ibkr import broker_ibkr
from broker_alpaca import broker_alpaca

for account in ["U8438939", "PA3I5VZDCGPF"]:
    print(f"Account: {account}")
    bot = "live"
    config = configparser.ConfigParser()

    print("HEALTH CHECK")
    config.read('config.ini')
    aconfig = config[account]
    if aconfig['driver'] == 'ibkr':
        driver = broker_ibkr(bot, account)
    elif aconfig['driver'] == 'alpaca':
        driver = broker_alpaca(bot, account)
    else:
        raise Exception("Unknown driver: " + aconfig['driver'])
    driver.health_check()

    print("GET POSITION SIZE")
    position_size = driver.get_position_size('ES1!')
    print(f"Position size: {position_size}")

    print("GET STOCK, CHECK FUTURES")
    stock = driver.get_stock("ES1!")
    print(f"Stock: {stock}, is_futures={stock.is_futures}")

    print("")
