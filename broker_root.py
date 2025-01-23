import configparser
import core_error

class broker_root:
    def __init__(self, bot, account):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.bot = bot
        self.account = account
        self.aconfig = self.get_account_config(account)

    def get_account_config(self, account):
        account_config = self.config[account]
        if 'group' in account_config:
            group = account_config['group']
            group_config = self.config[group]
            # Merge group config into account config, account config takes precedence
            merged_config = {**group_config, **account_config}
            #print(f"merged_config({account}): {merged_config}")
            return merged_config
        return account_config

    def handle_ex(self, e, context="unknown"):
        core_error.handle_ex(e, context, "broker")

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