import asyncio
import datetime
import time
import configparser
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from broker_root import broker_root
import yfinance as yf

alpacaconn_cache = {}
ticker_cache = {}

class StockStub:
    def __init__(self, symbol):
        self.symbol = symbol
        self.is_futures = 0

# declare a class to represent the IB driver
class broker_alpaca(broker_root):
    def __init__(self, bot, account):
        try:
            self.config = configparser.ConfigParser()
            self.config.read('config.ini')
            self.bot = bot
            self.account = account
            self.aconfig = self.get_account_config(account)
            self.conn = None
            self.dataconn = None

            # pick up a cached IB connection if it exists; cache lifetime is 5 mins
            alcachekey = f"{self.aconfig['key']}"
            if alcachekey in alpacaconn_cache and alpacaconn_cache[alcachekey]['time'] > time.time() - 300:
                self.conn = alpacaconn_cache[alcachekey]['conn']
                self.dataconn = alpacaconn_cache[alcachekey]['dataconn']

            if self.conn is None:
                paper = True if self.aconfig['paper'] == 'yes' else False
                self.conn = TradingClient(api_key=self.aconfig['key'], secret_key=self.aconfig['secret'], paper=paper)
                self.dataconn = StockHistoricalDataClient(api_key=self.aconfig['key'], secret_key=self.aconfig['secret'])

                # cache the connection
                alpacaconn_cache[alcachekey] = {
                    'conn': self.conn,
                    'dataconn': self.dataconn,
                    'time': time.time()
                }
        except Exception as e:
            self.handle_ex(e, "init", extra_tags={"bot": bot, "account": account})
            raise

    def get_stock(self, symbol):
        try:
            # normalization of the symbol, from TV to Alpaca form
            if symbol.endswith('1!'):
                symbol = symbol[:-2]
            return StockStub(symbol)
        except Exception as e:
            self.handle_ex(e, f"get_stock_{symbol}")
            return None

    def get_price(self, symbol):
        try:
            stock = self.get_stock(symbol)
            if not stock:
                self.handle_ex(f"Unable to get stock info for {symbol}", "get_price")
                return 0

            request = StockLatestQuoteRequest(symbol=stock.symbol)
            quote = self.dataconn.get_stock_latest_quote(request)
            if not quote:
                self.handle_ex(f"Unable to get quote for {symbol}", "get_price")
                return 0

            return quote[stock.symbol].ask_price
        except Exception as e:
            self.handle_ex(e, f"get_price_{symbol}")
            return 0

    def get_net_liquidity(self):
        try:
            account = self.conn.get_account()
            return float(account.equity)
        except Exception as e:
            self.handle_ex(e, "get_net_liquidity")
            return 0

    def get_position_size(self, symbol):
        try:
            stock = self.get_stock(symbol)
            if not stock:
                self.handle_ex(f"Unable to get stock info for {symbol}", "get_position_size")
                return 0

            try:
                position = self.conn.get_position(stock.symbol)
                return int(position.qty)
            except:
                return 0
        except Exception as e:
            self.handle_ex(e, f"get_position_size_{symbol}")
            return 0

    async def set_position_size(self, symbol, amount):
        try:
            stock = self.get_stock(symbol)
            if not stock:
                self.handle_ex(f"Unable to get stock info for {symbol}", "set_position_size")
                return None

            current = self.get_position_size(symbol)
            if current == amount:
                return None

            side = OrderSide.BUY if amount > current else OrderSide.SELL
            qty = abs(amount - current)

            order = self.conn.submit_order(
                symbol=stock.symbol,
                qty=qty,
                side=side,
                type='market',
                time_in_force=TimeInForce.DAY
            )
            return order.id
        except Exception as e:
            self.handle_ex(e, f"set_position_size_{symbol}", extra_tags={"amount": amount})
            return None

    async def is_trade_completed(self, order_id):
        try:
            if not order_id:
                return True
            order = self.conn.get_order(order_id)
            return order.status in ['filled', 'canceled', 'expired']
        except Exception as e:
            self.handle_ex(e, "check_trade_completion")
            return False

    def download_data(self, symbol, end, duration, timeframe, cachedata=False):
        if end != "":
            raise Exception("Can only use blank end date")
        if timeframe != "1 day":
            raise Exception("Can only use 1 day timeframe")
        if 'Y' not in duration:
            raise Exception("Can only use years in duration, in IB format like '5 Y'")

        duration_years = int(duration.split(' ')[0])
        start = datetime.datetime.now() - datetime.timedelta(days=duration_years*365)

        request_params = StockBarsRequest(symbol_or_symbols=symbol, 
            start=start.strftime("%Y-%m-%d"), 
            timeframe = TimeFrame.Day)

        bars = self.dataconn.get_stock_bars(request_params)
        return bars.df

    def health_check_prices(self):
        try:
            self.get_price('TQQQ')
        except Exception as e:
            self.handle_ex(e, "health_check_prices")
            raise

    def health_check_positions(self):
        try:
            self.get_net_liquidity()
            positions = self.conn.get_all_positions()
        except Exception as e:
            self.handle_ex(e, "health_check_positions")
            raise
