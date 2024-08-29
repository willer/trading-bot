from twilio.rest import Client
import traceback

class broker_root:
    def __init__(self, bot, account):
        pass

    def handle_ex(self, e):
        account_sid = self.config['DEFAULT'].get('twilio-account-sid', '')
        auth_token = self.config['DEFAULT'].get('twilio-auth-token', '')
        from_phone = self.config['DEFAULT'].get('twilio-from-phone', '')
        to_phone = self.config['DEFAULT'].get('twilio-to-phone', '')
        if account_sid and auth_token and from_phone and to_phone:
            client = Client(account_sid, auth_token)
            # if e is a string send it, otherwise send the first 300 chars of the traceback
            message_body = f"broker-ibkr {self.bot} FAIL "
            message_body += e if isinstance(e, str) else traceback.format_exc()[:300]
            message = client.messages.create(
                body=message_body,
                from_=from_phone,
                to=to_phone
            )

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