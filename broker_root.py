from unittest import skip
from textmagic.rest import TextmagicRestClient
import traceback

class broker_root:
    def __init__(self, bot, account):
        pass

    def handle_ex(self, e):
        tmu = self.config['DEFAULT'].get('textmagic-username','')
        tmk = self.config['DEFAULT'].get('textmagic-key','')
        tmp = self.config['DEFAULT'].get('textmagic-phone','')
        if tmu != '' and tmk != '' and tmp != '':
            tmc = TextmagicRestClient(tmu, tmk)
            # if e is a string send it, otherwise send the first 300 chars of the traceback
            if isinstance(e, str):
                message = tmc.messages.create(phones=tmp, text=f"broker-ibkr " + self.bot + " FAIL " + e)
            else:
                message = tmc.messages.create(phones=tmp, text=f"broker-ibkr " + self.bot + " FAIL " + traceback.format_exc()[0:300])

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