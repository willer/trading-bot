import configparser
from datadog import initialize, statsd
from datadog.api import Event
import traceback

class broker_root:
    def __init__(self, bot, account):
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

    def get_account_config(self, account):
        account_config = self.config[account]
        if 'group' in account_config:
            group = account_config['group']
            group_config = self.config[group]
            # Merge group config into account config, account config takes precedence
            merged_config = {**group_config, **account_config}
            return merged_config
        return account_config

    def handle_ex(self, e, context="unknown"):
        # Track error metric
        tags = [
            f'service:broker',
            f'bot:{self.bot}',
            f'account:{self.account}',
            f'error_context:{context}'
        ]
        statsd.increment('broker.errors', tags=tags)
        
        # Send detailed event
        error_text = str(e) if isinstance(e, str) else traceback.format_exc()
        Event.create(
            title=f'Broker Error: {self.bot}/{self.account}',
            text=f'Context: {context}\n\nError:\n{error_text}',
            alert_type='error',
            tags=tags
        )

    def track_trade(self, symbol, action, amount, success=True):
        """Track trading activity metrics"""
        tags = [
            f'service:broker',
            f'bot:{self.bot}',
            f'account:{self.account}',
            f'symbol:{symbol}',
            f'action:{action}'
        ]
        
        # Track trade count
        statsd.increment('broker.trades', tags=tags + [f'success:{success}'])
        
        # Track position size changes
        if success:
            statsd.gauge('broker.position_size', amount, tags=tags)

    def track_connection(self, connected):
        """Track broker connection status"""
        tags = [
            f'service:broker',
            f'bot:{self.bot}',
            f'account:{self.account}'
        ]
        statsd.gauge('broker.connected', 1 if connected else 0, tags=tags)

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
        pass

    async def is_trade_completed(self, trade):
        pass

    def download_data(self, symbol, end, duration, timeframe):
        pass

    def health_check(self):
        pass