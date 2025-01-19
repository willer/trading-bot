import configparser
from datadog import initialize, statsd
from datadog.api import Event
from core_error import handle_ex

class broker_root:
    def __init__(self, bot, account):
        try:
            self.config = configparser.ConfigParser()
            self.config.read('config.ini')
            self.bot = bot
            self.account = account
            self.aconfig = self.get_account_config(account)
            
            # Initialize Datadog
            initialize(
                api_key=self.config['DEFAULT'].get('datadog-api-key', ''),
                app_key=self.config['DEFAULT'].get('datadog-app-key', '')
            )
        except Exception as e:
            self.handle_ex(e, "initialization")
            raise

    def get_account_config(self, account):
        try:
            account_config = self.config[account]
            if 'group' in account_config:
                group = account_config['group']
                group_config = self.config[group]
                # Merge group config into account config, account config takes precedence
                merged_config = {**group_config, **account_config}
                return merged_config
            return account_config
        except Exception as e:
            self.handle_ex(e, "get_account_config")
            raise

    def handle_ex(self, e, context="unknown"):
        """Wrapper around core error handler with broker-specific tags"""
        return handle_ex(
            e,
            context=context,
            service="broker",
            extra_tags=[
                f'bot:{self.bot}',
                f'account:{self.account}'
            ]
        )

    def track_trade(self, symbol, action, amount, success=True):
        """Track trading activity metrics"""
        try:
            tags = [
                f'service:broker',
                f'bot:{self.bot}',
                f'account:{self.account}',
                f'symbol:{symbol}',
                f'action:{action}',
                f'success:{success}'
            ]
            
            # Track trade attempt
            statsd.increment('broker.trades', tags=tags)
            
            # Track trade volume
            statsd.histogram('broker.trade_volume', abs(amount), tags=tags)
            
            if not success:
                statsd.increment('broker.trade_failures', tags=tags)
        except Exception as e:
            self.handle_ex(e, "track_trade")

    def track_connection(self, connected):
        """Track broker connection status"""
        try:
            tags = [
                f'service:broker',
                f'bot:{self.bot}',
                f'account:{self.account}'
            ]
            
            gauge_value = 1 if connected else 0
            statsd.gauge('broker.connected', gauge_value, tags=tags)
            
            if not connected:
                self.handle_ex("Broker disconnected", "connection_lost")
        except Exception as e:
            self.handle_ex(e, "track_connection")

    # function to round to the nearest decimal. y=10 for dimes, y=4 for quarters, y=100 for pennies
    def x_round(self,x,y):
        return round(x*y)/y

    def get_stock(self, symbol):
        pass

    def get_price(self, symbol):
        pass

    def get_net_liquidity(self):
        pass

    def get_position_size(self, symbol):
        pass

    async def set_position_size(self, symbol, amount):
        try:
            return await self._set_position_size(symbol, amount)
        except Exception as e:
            self.handle_ex(e, f"set_position_{symbol}")
            raise

    async def is_trade_completed(self, trade):
        try:
            return await self._is_trade_completed(trade)
        except Exception as e:
            self.handle_ex(e, "check_trade_completion")
            raise

    def download_data(self, symbol, end, duration, timeframe):
        pass

    def health_check(self):
        pass

    def health_check_prices(self):
        try:
            return self._health_check_prices()
        except Exception as e:
            self.handle_ex(e, "health_check_prices")
            raise

    def health_check_positions(self):
        try:
            return self._health_check_positions()
        except Exception as e:
            self.handle_ex(e, "health_check_positions")
            raise