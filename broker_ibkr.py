import asyncio
import datetime
import os
from ib_insync import *
import time
import nest_asyncio
import configparser
import math

import pandas as pd
from broker_root import broker_root

nest_asyncio.apply()

ibconn_cache = {}
stock_cache = {}
ticker_cache = {}

# declare a class to represent the IB driver
class broker_ibkr(broker_root):
    def __init__(self, bot, account):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.bot = bot
        self.account = account
        self.aconfig = self.config[account]
        self.conn = None

    def load_conn(self):
        # pick up a cached IB connection if it exists
        ibcachekey = f"{self.aconfig['host']}:{self.aconfig['port']}"
        if ibcachekey in ibconn_cache:
            self.conn = ibconn_cache[ibcachekey]['conn']

        if self.conn is None:
            self.conn = IB()
            try:
                print(f"IB: Trying to connect...")
                self.conn.connect(self.aconfig['host'], self.aconfig['port'], clientId=1)
            except Exception as e:
                try:
                    self.conn.connect(self.aconfig['host'], self.aconfig['port'], clientId=3)
                except Exception as e:
                    try:
                        self.conn.connect(self.aconfig['host'], self.aconfig['port'], clientId=4)
                    except Exception as e:
                        try:
                            self.conn.connect(self.aconfig['host'], self.aconfig['port'], clientId=5)
                        except Exception as e:
                            self.handle_ex(e)
                            raise

            # cache the connection
            ibconn_cache[ibcachekey] = {'conn': self.conn, 'time': time.time()}
            print("IB: Connected")

    def get_stock(self, symbol, forhistory=False):
        self.load_conn()
        # keep a cache of stocks to avoid repeated calls to IB
        if symbol in stock_cache:
            stock = stock_cache[symbol]
        else:
            # remove the TV-style 1! suffix from the symbol (e.g. NQ1! -> NQ)
            symbol = symbol.replace('1!', '')
            if False:
                pass

            elif symbol in ['NQ', 'ES', 'MNQ', 'MES']:
                if not forhistory:
                    stock = Future(symbol, '20231215', 'CME')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CME', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 4
                stock.market_order = False

            elif symbol in ['RTY','M2K']:
                if not forhistory:
                    stock = Future(symbol, '20231215', 'CME')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CME', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 10
                stock.market_order = False

            elif symbol in ['YM','MYM']:
                if not forhistory:
                    stock = Future(symbol, '20231215', 'CBOT')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CBOT', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 100
                stock.market_order = True

            elif symbol in ['ZN']:
                if not forhistory:
                    stock = Future(symbol, '20230621', 'CBOT')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CBOT', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 100
                stock.market_order = False

            elif symbol in ['VX']:
                if not forhistory:
                    stock = Future('VIX', '20230517', 'CFE')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CFE', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 100
                stock.market_order = True

            # forex futures listed at https://www.interactivebrokers.com/en/trading/cme-wti-futures.php
            elif symbol in ['M6E', 'M6A', 'M6B', 'MJY', 'MSF', 'MIR', 'MNH']:
                if not forhistory:
                    stock = Future(symbol, '20230616', 'CME')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CME', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 10000
                stock.market_order = False

            elif symbol in ['MCD']:
                if not forhistory:
                    stock = Future(symbol, '20230620', 'CME')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CME', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 10000
                stock.market_order = False

            elif symbol in ['HE']:
                if not forhistory:
                    stock = Future(symbol, '20230417', 'CME')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='CME', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 4
                stock.market_order = False

            elif symbol == 'DX':
                if not forhistory:
                    stock = Future(symbol, '20230616', 'NYBOT')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='NYBOT', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 100
                stock.market_order = False

            elif symbol in ['CL', 'NG']:
                if not forhistory:
                    stock = Future(symbol, '20230522', 'NYMEX')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='NYMEX', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 10
                stock.market_order = False

            elif symbol in ['GC', 'HG', 'MGC', 'MHG']:
                if not forhistory:
                    stock = Future(symbol, '20230628', 'COMEX')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='COMEX', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 10
                stock.market_order = True

            elif symbol in ['SI','MSI']:
                if not forhistory:
                    stock = Future(symbol, '20230727', 'COMEX', currency='USD', multiplier='1000')
                else:
                    stock = Contract(symbol=symbol, secType='CONTFUT', exchange='COMEX', currency='USD', multiplier='1000', includeExpired=True)
                stock.is_futures = 1
                stock.round_precision = 10
                stock.market_order = True

            elif symbol in ['HXU', 'HXD', 'HQU', 'HQD', 'HEU', 'HED', 'HSU', 'HSD', 'HGU', 'HGD', 'HBU', 'HBD', 'HNU', 'HND', 'HOU', 'HOD', 'HCU', 'HCD']:
                #stock = Stock(symbol, 'SMART', 'CAD')
                stock = Stock(symbol, 'TSE')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = True

            elif symbol == 'NDX':
                stock = Index(symbol, 'NASDAQ')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = False

            elif symbol == 'VIX':
                stock = Index(symbol, 'CBOE')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = False

            elif symbol == 'BRK-B' or symbol == 'BRK/B' or symbol == 'BRK.B':
                stock = Index('BRK B', 'NYSE', 'USD')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = False

            elif symbol == 'JETS':
                stock = Index('JETS', 'NYSE')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = False

            elif symbol == 'WEAT':
                stock = Index('WEAT', 'NYSE')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = False

            else:
                stock = Stock(symbol, 'SMART', 'USD')
                stock.is_futures = 0
                stock.round_precision = 100
                stock.market_order = False

            stock_cache[symbol] = stock
        return stock

    def get_price(self, symbol):
        self.load_conn()
        stock = self.get_stock(symbol)

        # keep a cache of tickers to avoid repeated calls to IB, but only for 5s
        if symbol in ticker_cache and time.time() - ticker_cache[symbol]['time'] < 5:
            ticker = ticker_cache[symbol]['ticker']
        else:
            [ticker] = self.conn.reqTickers(stock)
            ticker_cache[symbol] = {'ticker': ticker, 'time': time.time()}

        if math.isnan(ticker.last):
            if math.isnan(ticker.close):
                raise Exception(f"error trying to retrieve stock price for {symbol}, last={ticker.last}, close={ticker.close}")
            else:
                price = ticker.close
        else:
            price = ticker.last
        print(f"  get_price({symbol}) -> {price}")
        return price

    # example: get_price_opt('SPY', datetime.date.today, 280, 'P', '20191016')
    def get_price_opt(self, symbol, expiry, strike, put_call):
        self.load_conn()

        datestr = expiry.strftime("%Y%m%d")
        contract = Option(symbol, expiry, strike, put_call, "SMART")
        ticker = self.conn.reqMktData(contract)

        #order = MarketOrder("Buy",2)
        #trade = self.conn.placeOrder(contract,order)
        #stock = self.get_stock(symbol)


        if math.isnan(ticker.last):
            if math.isnan(ticker.close):
                raise Exception("error trying to retrieve stock price for " + symbol)
            else:
                price = ticker.close
        else:
            price = ticker.last
        print(f"  get_price({symbol}) -> {price}")
        return price

    def get_net_liquidity(self):
        self.load_conn()
        # get the current net liquidity
        net_liquidity = 0
        accountSummary = self.conn.accountSummary(self.account)
        for value in accountSummary:
            if value.tag == 'NetLiquidation':
                net_liquidity = float(value.value)
                break

        print(f"  get_net_liquidity() -> {net_liquidity}")

        return net_liquidity

    def get_position_size(self, symbol):
        self.load_conn()
        # get the current position size
        stock = self.get_stock(symbol)
        psize = 0
        for p in self.conn.positions(self.account):
            if p.contract.symbol == stock.symbol:
                psize = int(p.position)

        print(f"  get_position_size({symbol}) -> {psize}")
        return psize

    async def set_position_size(self, symbol, amount):
        print(f"set_position_size({self.account},{symbol},{amount})")
        if False:
            print(f"  SKIPPING")
            return

        self.load_conn()
        stock = self.get_stock(symbol)

        # get the current position size
        position_size = self.get_position_size(symbol)

        # figure out how much to buy or sell
        position_variation = round(amount - position_size, 0)

        # if we need to buy or sell, do it with a limit order
        if position_variation != 0:

            if stock.market_order:
                if position_variation > 0:
                    order = MarketOrder('BUY', position_variation)
                else:
                    order = MarketOrder('SELL', abs(position_variation))

            else:
                price = self.get_price(symbol)
                high_limit_price = self.x_round(price * 1.005, stock.round_precision)
                low_limit_price  = self.x_round(price * 0.995, stock.round_precision)

                if position_variation > 0:
                    order = LimitOrder('BUY', position_variation, high_limit_price)
                else:
                    order = LimitOrder('SELL', abs(position_variation), low_limit_price)

            order.outsideRth = True
            order.account = self.account

            print("  placing order: ", order)
            trade = self.conn.placeOrder(stock, order)
            print("    trade: ", trade)

            # wait for the order to be filled, up to 30s
            maxloops = 15
            print("    waiting for trade1: ", trade)
            while trade.orderStatus.status not in ['Filled','Cancelled','ApiCancelled'] and maxloops > 0:
                #self.conn.sleep(1)
                await asyncio.sleep(1)
                print("    waiting for trade2: ", trade)
                maxloops -= 1

            await asyncio.sleep(1)

            # throw exception on order failure
            if trade.orderStatus.status not in ['Filled']:
                msg = f"ORDER FAILED in status {trade.orderStatus.status}: set_position_size({self.account},{symbol},{stock},{amount},{stock.round_precision}) -> {trade.orderStatus}"
                print(msg)
                self.handle_ex(msg)

            print("order filled")

    def download_data(self, symbol, end, duration, barlength, cachedata=False):
        print(f"download_data({symbol},{end},{duration},{barlength})")

        cachefile = f"cache/stockdata-{symbol}-{end.replace(' ','_')}-{duration.replace(' ','_')}-{barlength}.pkl"

        # check if we have a cached version of the data and it's not more than 1h old
        if cachedata and os.path.exists(cachefile) and time.time() - os.path.getmtime(cachefile) < 3600:
            print("  loading cached data")
            df = pd.read_pickle(cachefile)
            return df

        self.load_conn()
        stock = self.get_stock(symbol, forhistory=True)

        # request historical bars
        useRTH = False
        if 'day' in barlength or 'week' in barlength or 'month' in barlength:
            useRTH = True

        bars = self.conn.reqHistoricalData(
            stock,
            endDateTime=end,
            durationStr=duration,
            barSizeSetting=barlength,
            whatToShow='TRADES',
            useRTH=useRTH,
            formatDate=1,
            timeout = 300
        )
        # convert to df, and rename columns from 'open' to 'Open' etc to make it look like Yahoo data
        df = util.df(bars,labels=['date','open','high','low','close','volume'])
        df.columns = [c.capitalize() for c in df.columns]
        # make the date column the index
        df.set_index('Date', inplace=True)
        # convert date to pandas timestamp
        df.index = pd.to_datetime(df.index)

        # clear out last line if it's a partial bar
        # (IB gives us partial bars and doesn't identify them as such)
        if not stock.is_futures:
            nowisinRTH = datetime.datetime.now().time() >= datetime.time(9,30,0) and \
                datetime.datetime.now().time() < datetime.time(16,0,0)
            nowisinETH = datetime.datetime.now().time() >= datetime.time(4,0,0) and \
                datetime.datetime.now().time() < datetime.time(20,0,0)
            if 'day' in barlength:
                if nowisinRTH:
                    df = df[:-1]
            elif 'week' in barlength:
                pass
            elif 'month' in barlength:
                pass
            elif 'hour' in barlength:
                if not nowisinETH:
                    df = df[:-1]
            elif 'min' in barlength:
                if not nowisinETH:
                    df = df[:-1]
        else:
            # assume futures are always active (so the last record is always a partial bar)
            df = df[:-1]

        # special case: NDX doesn't give us volume, so we have to pick it up from QQQ
        if (symbol == 'NDX'):
            df['Volume'] = self.download_data('QQQ', end, duration, barlength)['Volume']

        print(f"  download_data({symbol},{end},{duration},{barlength}) -> {len(bars)} bars")

        if cachedata:
            # cache the data
            df.to_pickle(cachefile)

        return df


    def health_check(self):
        self.get_net_liquidity()
        self.get_price('SOXL')
        self.get_position_size('SOXL')
        self.get_position_size('SOXS')
