import unittest
import datetime
import json
import os
import asyncio
import time
import sys
from unittest.mock import patch, MagicMock, call

# Patch sys.argv - we need to do this before importing broker
original_argv = sys.argv
sys.argv = ['broker.py', 'test']

# Create a patch for psycopg2 pool to avoid database connection
psycopg2_patch = patch('sqlite3.connect')
mock_pool = psycopg2_patch.start()

# Patch Redis
redis_patch = patch('redis.Redis')
mock_redis = redis_patch.start()

# Patch the config reading - need to do this before importing broker
config_mock = MagicMock()
mock_bot_config = {'accounts': 'test_account'}
mock_database = {
    'database-host': 'localhost',
    'database-port': '5432',
    'database-name': 'testdb',
    'database-user': 'testuser',
    'database-password': 'testpass'
}

def mock_getitem(key):
    if key == 'bot-test':
        return mock_bot_config
    elif key == 'database':
        return mock_database
    elif key == 'test_account':
        return {'driver': 'ibkr', 'default-pct': '100'}
    elif key == 'inverse-etfs':
        return {}
    else:
        return MagicMock()

config_mock.__getitem__ = MagicMock(side_effect=mock_getitem)
config_patch = patch('configparser.ConfigParser', return_value=config_mock)
config_patch.start()

# Now it's safe to import broker
import broker

# Restore original
sys.argv = original_argv
config_patch.stop()
redis_patch.stop()
psycopg2_patch.stop()

import logging

# Set up test logger to prevent logs from appearing in test output
test_logger = logging.getLogger('test_broker')
test_logger.setLevel(logging.DEBUG)
null_handler = logging.NullHandler()
test_logger.addHandler(null_handler)


class TestBrokerSignalProcessing(unittest.TestCase):
    """Test the signal processing logic in the broker"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock the Redis connection
        self.redis_patcher = patch('broker.r')
        self.mock_redis = self.redis_patcher.start()
        
        # Mock the DB connection and cursor
        self.mock_db = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_db.cursor.return_value = self.mock_cursor
        
        # Mock the get_db function
        self.get_db_patcher = patch('broker.get_db', return_value=self.mock_db)
        self.mock_get_db = self.get_db_patcher.start()
        
        # Mock the broker_root/broker_ibkr/broker_alpaca
        self.mock_broker = MagicMock()
        
        # Setup mock driver that returns position sizes and prices
        self.mock_driver = MagicMock()
        self.mock_driver.get_position_size.return_value = 0  # Default position
        self.mock_driver.get_price.return_value = 100.0  # Default price
        self.mock_driver.get_net_liquidity.return_value = 100000.0  # Default liquidity
        
        # Mock the stock object
        self.mock_stock = MagicMock()
        self.mock_stock.is_futures = False
        self.mock_stock.round_precision = 100
        self.mock_stock.market_order = False
        self.mock_driver.get_stock.return_value = self.mock_stock
        
        # Create a context that returns our mock driver when setup_trades_for_account is called
        self.setup_trades_patcher = patch.dict('broker.drivers', {'test_account': self.mock_driver})
        self.setup_trades_patcher.start()
        
        # Setup mock asyncio to avoid actual async execution
        self.asyncio_gather_patcher = patch('asyncio.gather')
        self.mock_asyncio_gather = self.asyncio_gather_patcher.start()
        self.mock_asyncio_gather.return_value = [(self.mock_driver, "order_id")]
        
        # Mock the asyncio.sleep function
        self.asyncio_sleep_patcher = patch('asyncio.sleep')
        self.mock_asyncio_sleep = self.asyncio_sleep_patcher.start()
        
        # Set up async trade execution mocks
        self.mock_driver.set_position_size.return_value = "order_id"
        self.mock_driver.is_trade_completed.return_value = True
        
        # Patch the db_pool to avoid database connection
        self.db_pool_patcher = patch('broker.db_pool')
        self.mock_db_pool = self.db_pool_patcher.start()
        
        # Mock get_account_config
        self.get_account_config_patcher = patch('broker.get_account_config')
        self.mock_get_account_config = self.get_account_config_patcher.start()
        self.mock_get_account_config.return_value = {'driver': 'ibkr', 'default-pct': '100'}
        
        # Helper function to create signal data
        def create_signal_data(market_position, prev_market_position, position_pct=None):
            """Helper to create signal data with different positions"""
            if position_pct is None:
                if market_position == 'flat':
                    position_pct = 0
                elif market_position == 'long':
                    position_pct = 100
                elif market_position == 'short':
                    position_pct = -100
            
            return {
                'data': json.dumps({
                    'ticker': 'SOXL',
                    'strategy': {
                        'bot': 'test',
                        'market_position': market_position,
                        'prev_market_position': prev_market_position,
                        'position_pct': position_pct,
                        'id': 123
                    }
                }),
                'type': 'message'
            }
        
        # Create signal data templates for different scenarios
        self.short_signal = create_signal_data('short', 'flat', -100)
        self.long_signal = create_signal_data('long', 'flat', 100)
        self.flat_signal = create_signal_data('flat', 'long', 0)
        self.flat_from_short_signal = create_signal_data('flat', 'short', 0)
        self.short_from_long_signal = create_signal_data('short', 'long', -100)
        self.long_from_short_signal = create_signal_data('long', 'short', 100)
        self.long_tp_signal = create_signal_data('long', 'long', 20)  # TP with 20% position
        self.short_tp_signal = create_signal_data('short', 'short', -20)  # TP with 20% position
        
        # Default test signal is short
        self.test_signal_data = self.short_signal
        
    def tearDown(self):
        """Tear down test fixtures"""
        # Stop all patches
        self.redis_patcher.stop()
        self.get_db_patcher.stop()
        self.setup_trades_patcher.stop()
        self.asyncio_gather_patcher.stop()
        self.asyncio_sleep_patcher.stop()
        self.get_account_config_patcher.stop()
        self.db_pool_patcher.stop()

    def test_setup_trades_for_account_short_position(self):
        """Test setting up a short position trade"""
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', -100, [], []
        )
        
        # Verify the driver's methods were called correctly
        self.mock_driver.get_stock.assert_called_with('SOXL')
        self.mock_driver.get_price.assert_called_with('SOXL')
        self.mock_driver.get_net_liquidity.assert_called()
        self.mock_driver.get_position_size.assert_called_with('SOXL')
        
        # Verify an opening trade was added
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][0], self.mock_driver)
        self.assertEqual(opening_trades[0][1], 'SOXL')
        # Position should be negative (short)
        self.assertTrue(opening_trades[0][2] < 0)
    
    def test_setup_trades_for_account_flat_position(self):
        """Test setting up a flat (close) position trade"""
        # Set current position to be non-zero
        self.mock_driver.get_position_size.return_value = 100
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 0, [], []
        )
        
        # Verify an opening trade was added to flatten the position
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][0], self.mock_driver)
        self.assertEqual(opening_trades[0][1], 'SOXL')
        self.assertEqual(opening_trades[0][2], 0)  # Flat position
    
    # Test different position transitions
    
    def test_long_to_flat(self):
        """Test transition from long to flat position"""
        # Set current position to long
        self.mock_driver.get_position_size.return_value = 100
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 0, [], []
        )
        
        # Should have a trade to go to 0
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][2], 0)
    
    def test_long_to_short(self):
        """Test transition from long to short position"""
        # Set current position to long
        self.mock_driver.get_position_size.return_value = 100
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', -100, [], []
        )
        
        # Should have a trade to go short (negative position)
        self.assertEqual(len(opening_trades), 1)
        self.assertTrue(opening_trades[0][2] < 0)
    
    def test_flat_to_long(self):
        """Test transition from flat to long position"""
        # Set current position to flat
        self.mock_driver.get_position_size.return_value = 0
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 100, [], []
        )
        
        # Should have a trade to go long (positive position)
        self.assertEqual(len(opening_trades), 1)
        self.assertTrue(opening_trades[0][2] > 0)
    
    def test_flat_to_short(self):
        """Test transition from flat to short position"""
        # Set current position to flat
        self.mock_driver.get_position_size.return_value = 0
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', -100, [], []
        )
        
        # Should have a trade to go short (negative position)
        self.assertEqual(len(opening_trades), 1)
        self.assertTrue(opening_trades[0][2] < 0)
    
    def test_short_to_flat(self):
        """Test transition from short to flat position"""
        # Set current position to short
        self.mock_driver.get_position_size.return_value = -100
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 0, [], []
        )
        
        # Should have a trade to go to 0
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][2], 0)
    
    def test_short_to_long(self):
        """Test transition from short to long position"""
        # Set current position to short
        self.mock_driver.get_position_size.return_value = -100
        
        # Call the function
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 100, [], []
        )
        
        # Should have a trade to go long (positive position)
        self.assertEqual(len(opening_trades), 1)
        self.assertTrue(opening_trades[0][2] > 0)
    
    # Test different current positions vs webhook quantity
    
    def test_long_below_webhook_qty(self):
        """Test when current long position is below webhook requested quantity"""
        # Set current position to long but smaller than webhook
        self.mock_driver.get_position_size.return_value = 50
        
        # Call the function with larger position
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 100, [], []
        )
        
        # Should have a trade to increase position
        self.assertEqual(len(opening_trades), 1)
        self.assertTrue(opening_trades[0][2] > 50)
    
    def test_long_above_webhook_qty(self):
        """Test when current long position is above webhook requested quantity"""
        # Set current position to long but larger than webhook
        self.mock_driver.get_position_size.return_value = 150
        
        # Call the function with smaller position
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 100, [], []
        )
        
        # Should have a trade to decrease position
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][2], 100)  # Reduce to 100
    
    def test_short_below_webhook_qty(self):
        """Test when current short position is below webhook requested quantity (less negative)"""
        # Set current position to short but smaller than webhook
        self.mock_driver.get_position_size.return_value = -50
        
        # Call the function with larger short position
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', -100, [], []
        )
        
        # Should have a trade to increase short position (more negative)
        self.assertEqual(len(opening_trades), 1)
        self.assertTrue(opening_trades[0][2] < -50)
    
    def test_short_above_webhook_qty(self):
        """Test when current short position is above webhook requested quantity (more negative)"""
        # Set current position to short but larger than webhook
        self.mock_driver.get_position_size.return_value = -150
        
        # Call the function with smaller short position
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', -100, [], []
        )
        
        # Should have a trade to decrease short position (less negative)
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][2], -100)  # Reduce to -100
    
    def test_same_qty_as_webhook(self):
        """Test when current position matches webhook requested quantity"""
        # Set current position to match webhook
        self.mock_driver.get_position_size.return_value = 100
        
        # Call the function with same position
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 100, [], []
        )
        
        # Should have no trades since position already matches
        self.assertEqual(len(opening_trades), 0)
    
    # Test take profit scenarios
    
    def test_long_take_profit(self):
        """Test a take profit order in a long position"""
        # Set current position to long
        self.mock_driver.get_position_size.return_value = 100
        
        # Call the function with TP (lower quantity)
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', 20, [], []
        )
        
        # Should have a trade to reduce position
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][2], 20)  # Reduce to 20
    
    def test_short_take_profit(self):
        """Test a take profit order in a short position"""
        # Set current position to short
        self.mock_driver.get_position_size.return_value = -100
        
        # Call the function with TP (lower quantity)
        closing_trades, opening_trades = broker.setup_trades_for_account(
            'test_account', 'SOXL', -20, [], []
        )
        
        # Should have a trade to reduce position
        self.assertEqual(len(opening_trades), 1)
        self.assertEqual(opening_trades[0][2], -20)  # Reduce to -20

if __name__ == '__main__':
    unittest.main()