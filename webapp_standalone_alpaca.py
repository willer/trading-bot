from flask import Flask, request, jsonify
import json
import datetime
import alpaca_trade_api as tradeapi
import requests
import pytz
import asyncio
import logging

# Create Flask object called app.
app = Flask(__name__)

# authentication requires your API credentials
import os

alpkey     = os.getenv('SK_KEY')
alpsec     = os.getenv('SK_SECRET')


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


########################################################################
#### Print current time in CST
########################################################################

def print_current_time_cst():
    cst = pytz.timezone('US/Central')
    current_time = datetime.datetime.now(cst)
    print(current_time.strftime("%Y-%m-%d %H:%M:%S %Z%z"))

def nearest_lower_multiple(f,n):
    return (int(f) // n) * n

########################################################################
#### Class to encapsulate information in the JSON request
########################################################################

class OrderRequest:
    def __init__(self, json_data):
        #self.data_dict = None
        self.order_symbol = None
        self.inverse_symbol = None
        self.prev_market_position = None
        self.prev_market_position_size = None
        self.market_position = None
        self.market_position_size = None
        self.order_price = None
        self.order_id = None
        self.current_long_qty = None
        self.current_inverse_qty = None
        self.trade_symbol = None
        self.trade_desired_qty = None
        self.trade_current_qty = None
        self.trade_symbol_bid = None
        self.trade_symbol_ask = None
        self.position_value = None
        self.buying_power = None

        data_dict = self.validate_request(json_data)

        if not data_dict is None and self.is_valid_symbol(data_dict) and self.is_strategy(data_dict) and self.has_complete_structure(data_dict):
            self.parse_dict(data_dict)
            #self.data_dict = data_dict
            #print('order object after parsing')
            #print(self.__dict__)

    def print(self):
            print(self.__dict__)
            print(' ')

    def is_invalid(self):
        return (self.order_symbol == None)

    def inconsistent_order(self):
        order_is_to_close_long  = self.prev_market_position == "long"  and self.market_position == "flat"
        order_is_to_close_short = self.prev_market_position == "short" and self.market_position == "flat"

        if self.current_long_qty > 0 and order_is_to_close_short:
            print("inconsistent order: trying to close short when holding long position.")
            return True
        elif self.current_inverse_qty > 0 and order_is_to_close_long:
            print("inconsistent order: trying to close long when holdint short position.")
            return True
        else:
            return False

    def dictionary(self):
        return self.__dict__

    def validate_request(self, json_request):
        try:
            data_dict = json.loads(json_request)
            return data_dict
        except json.JSONDecodeError:
            return None

    def is_valid_symbol(self, data):
        if "ticker" not in data:
            return False
        elif data['ticker'] in ["SOXL"]:
            return True

    def is_strategy(self, data):
        if not isinstance(data, dict) or not data:
            return False
        return data.get("type") == "strategy"

    def has_complete_structure(self, data):
        if not isinstance(data, dict):
            return False

        required_keys = ["type", "time", "exchange", "ticker", "bar", "strategy"]
        for key in required_keys:
            if key not in data:
                return False

        if not isinstance(data["bar"], dict):
            return False
        required_bar_keys = ["time", "open", "high", "low", "close", "volume"]
        for key in required_bar_keys:
            if key not in data["bar"]:
                return False

        if not isinstance(data["strategy"], dict):
            return False
        required_strategy_keys = ["position_size", "order_action", "order_contracts", "order_price", "order_id", "market_position", "market_position_size", "prev_market_position", "prev_market_position_size"]
        for key in required_strategy_keys:
            if key not in data["strategy"]:
                return False

        return True

    def parse_dict(self, data):
        self.order_symbol              = data['ticker']
        self.inverse_symbol            = get_inverse_symbol(self.order_symbol)
        self.prev_market_position      = data['strategy']['prev_market_position']
        self.prev_market_position_size = float(data['strategy']['prev_market_position_size'])
        self.market_position           = data['strategy']['market_position']
        self.market_position_size      = float(data['strategy']['market_position_size'])
        self.order_price               = float(data['strategy']['order_price'])
        self.order_id                  = data['strategy']['order_id']
        self.position_value            = self.calculate_position_value()

    def read_broker_account_info(self, api, api_key, api_secret):
        self.buying_power        = get_buying_power(api_key, api_secret)
        self.current_long_qty    = get_open_position_size(api, self.order_symbol)
        self.current_inverse_qty = get_open_position_size(api, self.inverse_symbol)

    def calculate_position_value(self):
        if self.market_position_size is None or self.order_price is None:
            return None
        else:
            value = round(self.market_position_size * self.order_price, 2)
            return value

    # use update_position to change position size
    # for example, if you want to use all the buying power
    def update_position_value(self, new_value):
        self.market_position_size = round(new_value / self.order_price, 0)

########################################################################
#### Place order on Alpaca
########################################################################

# Submit an order if quantity is above 0.
# Figure out when the market will close so we can prepare to sell beforehand.

def ok_to_place_market_order(api):

    clock = api.get_clock()

    if clock.is_open:
        closing_time = clock.next_close.replace(tzinfo = datetime.timezone.utc).timestamp()
        current_time = clock.timestamp.replace(tzinfo = datetime.timezone.utc).timestamp()

        time_to_close = closing_time - current_time

        # placing order when less than 2 minutes to market close.
        # don't place market order

        if(time_to_close < (60 * 2)):
            return False
        else:
            return True
    else:
       return False

################################################################################################################

def get_real_time_quote(symbol):
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
    headers = {
        "APCA-API-KEY-ID": alpkey,
        "APCA-API-SECRET-KEY": alpsec
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raises an HTTPError for bad responses

        data = response.json()
        quote = data['quote']
        bid_price = quote['bp']
        ask_price = quote['ap']
        return [bid_price, ask_price]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching quote for {symbol}: {e}")
        return []

################################################################################################################


def get_buying_power(api_key, api_secret):

    base_url = 'https://api.alpaca.markets'

    headers = {
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': api_secret
    }

    # Endpoint to get account information
    account_url = f"{base_url}/v2/account"

    try:
        # Make the request
        response = requests.get(account_url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses

        # Extract the buying power
        account_data = response.json()
        buying_power = float(account_data['buying_power'])
        return buying_power

    except requests.exceptions.RequestException as e:
        print(f"Error fetching buying power: {e}")
        return None

################################################################################################################

def get_account_equity(api):
    #get account information
    account = api.get_account()
    account_equity = float(account.equity)

    #return account value
    return account_equity

################################################################################################################

async def place_order_alpaca(api, stock, qty, side, limit_price):

    print('place_order_alpaca: ', stock, qty, side, limit_price)

    if(qty > 0):
        try:
            if ok_to_place_market_order(api):
                print('placing market order')
                order = api.submit_order(symbol = stock,
                                               qty = qty,
                                               side = side,
                                               type = 'market',
                                               time_in_force = 'day',
                                               )

                print("Market order of | " + side + " " + str(qty) + " shares of " + stock + " | placed.")
            else:
                print('placing limit order')
                order = api.submit_order(symbol = stock,
                                               qty = qty,
                                               side = side,
                                               type = 'limit',
                                               time_in_force = 'day',
                                               limit_price = limit_price,
                                               extended_hours = True
                                               )

                print("Limit order of | " + side + " " + str(qty) + " shares of " + stock + " at price " + str(limit_price) + " | placed.")

            # wait for the order to be filled, up to 30s
            maxloops = 10
            while maxloops > 0 and order.status not in ['filled', 'rejected']:
                await asyncio.sleep(1)
                order = api.get_order(order.id)
                maxloops -= 1

            # throw exception on order failure
            if order.status in ['filled']:
                print('order succcessfully executed on Alpaca: ', order.filled_at)
            else:
                print("order failed to execute on Alpaca")

        except Exception as e:
            print("Failed to submit order:", e)
            print("Order of | " + str(qty) + " " + stock + " " + side + " | did not go through.")
    else:
        print("Quantity is not > 0, order of | " + str(qty) + " " + stock + " " + side + " | not completed.")

    return

#######################################################################
#### cancel if there are open orders for the order_symbol
#######################################################################

def cancel_open_orders_for_symbol(api, symbol):

    print('canceling open orders for: ', symbol)
    orders = api.list_orders(status="open")

    for order in orders:
        if (order.symbol == symbol):
            api.cancel_order(order.id)

    return

#######################################################################
#### check if there is already a position for the order_symbol
#######################################################################

def get_open_position_size(api, symbol):
    try:
        position      = api.get_position(symbol)
        current_qty   = float(position.qty)

    except:
        current_qty = 0.0

    return current_qty

#######################################################################
#### Close any open positions for the given symbol
#######################################################################

async def liquidate_open_position(api, symbol):

    qty = get_open_position_size(api, symbol)

    if (qty == 0):
        return False

    [bid, ask] = get_real_time_quote(symbol)

    if qty < 0:
        side = "buy"
        limit_price = round(ask + 0.05, 2)
    else:
        side = "sell"
        limit_price = round(bid - 0.05, 2)

    await place_order_alpaca(api, symbol, abs(qty), side, limit_price)

    return True

########################################################################
## Get the inverse symbol if one exists
########################################################################

def is_short_symbol(symbol):
    return symbol in ['SQQQ', 'SOXS']

def is_long_symbol(symbol):
    return symbol in ['TQQQ', 'SOXL']

def get_inverse_symbol(order_symbol):

    inverse_symbol = ''

    if (order_symbol == 'SOXL'):
        inverse_symbol = 'SOXS'
    elif (order_symbol == 'TQQQ'):
        inverse_symbol = 'SQQQ'

    return inverse_symbol

########################################################################
# Helper functions

def is_valid_symbol(data):
    if "ticker" not in data:
        return False
    return data["ticker"] in ["SOXL"]

def is_strategy(data):
    if not isinstance(data, dict) or not data:
        return False
    return data.get("type") == "strategy"

###
#This function checks if the payload dictionary has the following structure:
# 1. It's a dictionary
# 2. It has the required top-level keys: "type", "time", "exchange", "ticker", "bar", and "strategy"
# 3. The "bar" value is a dictionary with the required keys: "time", "open", "high", "low", "close", and "volume"
# 4. The "strategy" value is a dictionary with the required keys: "position_size", "order_action", "order_contracts", "order_price", "order_id", "market_position", "market_position_size", "prev_market_position", and "prev_market_position_size"
#
# If all these conditions are met, the function returns True, otherwise it returns False.
###

def has_complete_structure(data):
    if not isinstance(data, dict):
        return False

    required_keys = ["type", "time", "exchange", "ticker", "bar", "strategy"]
    for key in required_keys:
        if key not in data:
            return False

    if not isinstance(data["bar"], dict):
        return False
    required_bar_keys = ["time", "open", "high", "low", "close", "volume"]
    for key in required_bar_keys:
        if key not in data["bar"]:
            return False

    if not isinstance(data["strategy"], dict):
        return False
    required_strategy_keys = ["position_size", "order_action", "order_contracts", "order_price", "order_id", "market_position", "market_position_size", "prev_market_position", "prev_market_position_size"]
    for key in required_strategy_keys:
        if key not in data["strategy"]:
            return False

    return True

########################################################################

def cancel_open_orders(api, order):
    if not order.order_symbol is None:
        cancel_open_orders_for_symbol(api, order.order_symbol)
        #print(f"Canceled open orders for {order.order_symbol}")
    if not order.inverse_symbol is None:
        cancel_open_orders_for_symbol(api, order.inverse_symbol)
        #print(f"Canceled open orders for {order.inverse_symbol}")

#######

async def prepare_order_for_execution_on_alpaca(api, order):
    cancel_open_orders(api, order)
    if order.market_position == 'long':
        print('market position is long')
        print(f"liquidated any position in {order.inverse_symbol}")
        await liquidate_open_position(api, order.inverse_symbol)
        order.trade_symbol = order.order_symbol
    elif order.market_position == 'short':
        print('market position is short')
        print(f"liquidated any position in {order.order_symbol}")
        await liquidate_open_position(api, order.order_symbol)
        order.trade_symbol = order.inverse_symbol
    else: # market_position is flat
        print('market position is flat')
        print(f"liquidated any position in {order.order_symbol}")
        print(f"liquidated any position in {order.inverse_symbol}")
        await liquidate_open_position(api, order.order_symbol)
        await liquidate_open_position(api, order.inverse_symbol)
        print('no additional action to take.  Exiting.')
        return False

    if order.market_position != 'Flat':
        order.trade_current_qty = get_open_position_size(api, order.trade_symbol)
        [order.trade_symbol_bid, order.trade_symbol_ask] = get_real_time_quote(order.trade_symbol)
        print(f"Real-time Quote for {order.trade_symbol}:")
        print(f"  Bid: ${order.trade_symbol_bid:.2f}")
        print(f"  Ask: ${order.trade_symbol_ask:.2f}")
        if not ('TP' in order.order_id):
            account_equity = get_account_equity(api)
            account_equity_available_to_trade = nearest_lower_multiple(account_equity, 2000) - 1000
            order.trade_desired_qty = round(account_equity_available_to_trade / order.trade_symbol_ask,0)
        else:
            order.trade_desired_qty = round(order.market_position_size * order.order_price / order.trade_symbol_ask,0)
        print('capital allocated to trade = ', order.trade_desired_qty * order.trade_symbol_ask)
        print('current quantity = ', order.trade_current_qty)
        print('desired quantity = ', order.trade_desired_qty)
        return True

async def execute_order_on_alpaca(api, order):
    is_long_TP_order = (order.market_position == 'long') and ('TP' in order.order_id)
    is_short_TP_order = (order.market_position == 'short') and ('TP' in order.order_id)

    print('trade symbol = ', order.trade_symbol, 'desired quantity = ', order.trade_desired_qty, 'current quantity = ', order.trade_current_qty)
    if order.trade_desired_qty == order.trade_current_qty:
        return False
    elif is_long_symbol(order.trade_symbol) and order.market_position == 'short':
        print('long symbol but market position is short.  Corrupted order.')
        return False
    elif is_short_symbol(order.trade_symbol) and order.market_position == 'long':
        print('short symbol but market position is long.  Corrupted order.')
        return False
    elif is_long_symbol(order.trade_symbol) and order.trade_desired_qty > order.trade_current_qty and is_long_TP_order:
        print("Will not increase long position when order is Long TP.")
        return False
    elif is_short_symbol(order.trade_symbol) and order.trade_desired_qty > order.trade_current_qty and is_short_TP_order:
        print("Will not increase short position when order is Short TP.")
        return False
    elif order.trade_desired_qty > order.trade_current_qty:
        order_side = "buy"
        limit_order = round(order.trade_symbol_ask + 0.05, 2)
    else:
        order_side = "sell"
        limit_order = round(order.trade_symbol_bid - 0.05, 2)

    order_qty = order.trade_desired_qty - order.trade_current_qty
    await place_order_alpaca(api, order.trade_symbol, order_qty, order_side, limit_order)
    return True

########################################################################

import time
import threading

# Store the last received webhook in memory
last_webhook = {"data": None, "timestamp": 0}
processing_lock = threading.Lock()  # Create a lock to prevent concurrent processing

# Time threshold in seconds (e.g., 30 seconds)
TIME_THRESHOLD = 30

# Create root to easily let us know its on/working.
@app.route("/")
def root():
    return 'Online'

@app.route("/webhook", methods=['GET', 'POST'])
async def webhook():
    try:

        global last_webhook

        new_webhook_data = request.get_json()
        current_time = time.time()

        # Acquire the lock to prevent simultaneous processing of the same webhook
        with processing_lock:
            # Check if this webhook is a duplicate within the threshold
            if new_webhook_data == last_webhook["data"] and (current_time - last_webhook["timestamp"]) < TIME_THRESHOLD:
                print("Duplicate webhook skipped")
                return jsonify({"status": "Duplicate webhook skipped"}), 200

            # Update the last webhook data and timestamp
            last_webhook = {"data": new_webhook_data, "timestamp": current_time}

            if request.method == 'POST':

                print('*******************************')
                print_current_time_cst()

                order = OrderRequest(request.data)

                if order.is_invalid():
                    print("Received an invalid json payload. Exiting without action.")
                    return {"code": "Unknown json payload."}
                else:
                    print('Received the following valid json payload.')
                    order.print()
                print('*******************************')


                api = tradeapi.REST(alpkey, alpsec, base_url='https://api.alpaca.markets')

                order.read_broker_account_info(api, alpkey, alpsec)

                if order.inconsistent_order():
                    print("Inconsistent order. Exiting without action.")
                else:
                    order_prepared = await prepare_order_for_execution_on_alpaca(api, order)
                    if not order_prepared:
                        print('Nothing more to do')
                    else:
                        order.print()
                        execution_order_status = await execute_order_on_alpaca(api, order)
                        if not execution_order_status:
                            print("Not placing the order.")

                print_current_time_cst()
                print("**************** Done.  Exiting. ****************")
                return jsonify({"status": "OK"}), 200
            else:
                print("Not Post Method")
                return jsonify({"status": "Not POST"}), 200
    except Exception as e:
        logging.error(f"Error processing webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

