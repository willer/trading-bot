import unittest
import datetime
import json
import os
import tempfile
import sqlite3
import configparser
from unittest.mock import patch, MagicMock, call
from flask import Flask
import webapp_core
import logging

# Set up test logger to prevent logs from appearing in test output
test_logger = logging.getLogger('test_webapp')
test_logger.setLevel(logging.DEBUG)
null_handler = logging.NullHandler()
test_logger.addHandler(null_handler)


class TestWebappSignalProcessing(unittest.TestCase):
    """Test the signal processing logic in the webapp"""

    def setUp(self):
        """Set up test fixtures, creating a test Flask app and DB connection"""
        # Create a test Flask app
        self.app = Flask(__name__)
        self.app.logger = test_logger
        self.app.config['TESTING'] = True
        
        # Patch the app in webapp_core
        self.original_app = webapp_core.app
        webapp_core.app = self.app
        
        # Mock the Redis connection
        self.redis_patcher = patch('webapp_core.r')
        self.mock_redis = self.redis_patcher.start()
        
        # Mock the DB connection and cursor
        self.mock_db = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_db.cursor.return_value = self.mock_cursor
        
        # Create a context that returns our mock DB when get_db is called
        self.get_db_patcher = patch('webapp_core.get_db', return_value=self.mock_db)
        self.mock_get_db = self.get_db_patcher.start()
        
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
                'ticker': 'SOXL',
                'strategy': {
                    'bot': 'test_bot',
                    'market_position': market_position,
                    'prev_market_position': prev_market_position,
                    'position_pct': position_pct,
                    'id': 123,
                    'timestamp': datetime.datetime.now()
                }
            }
        
        # Create test signal templates
        self.short_signal = create_signal_data('short', 'flat', -100)
        self.long_signal = create_signal_data('long', 'flat', 100)
        self.flat_signal = create_signal_data('flat', 'long', 0)
        self.flat_from_short_signal = create_signal_data('flat', 'short', 0)
        self.short_from_long_signal = create_signal_data('short', 'long', -100)
        self.long_from_short_signal = create_signal_data('long', 'short', 100)
        
        # Default test signal
        self.test_signal_data = self.short_signal
        
    def tearDown(self):
        """Tear down test fixtures"""
        # Restore the original app
        webapp_core.app = self.original_app
        
        # Stop all patches
        self.redis_patcher.stop()
        self.get_db_patcher.stop()

    def test_should_skip_flat_signal_with_nearby_directional(self):
        """Test that a flat signal is skipped when there's a directional signal within 15s"""
        # Setup mock cursor to return a recent directional signal
        self.mock_cursor.fetchone.return_value = ['123', 'test_bot', 'SOXL', 'short']
        
        # Create a flat signal with prev_position=long
        flat_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'test_bot',
                'market_position': 'flat',
                'prev_market_position': 'long',
                'timestamp': datetime.datetime.now()
            }
        }
        
        # Call the function
        should_skip, reason = webapp_core.should_skip_flat_signal(flat_signal)
        
        # Verify it should be skipped
        self.assertTrue(should_skip)
        self.assertTrue('transition signal' in reason)
        
    def test_should_not_skip_directional_signal(self):
        """Test that a directional signal is never skipped"""
        # Create a directional signal
        long_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'test_bot',
                'market_position': 'long',
                'prev_market_position': 'flat',
                'timestamp': datetime.datetime.now()
            }
        }
        
        # Call the function
        should_skip, reason = webapp_core.should_skip_flat_signal(long_signal)
        
        # Verify it should not be skipped
        self.assertFalse(should_skip)
        self.assertIsNone(reason)
    
    def test_process_signal_retries_skips_flat_with_nearby_directional(self):
        """Test that process_signal_retries skips a flat signal with a nearby directional signal"""
        # Mock the cursor's fetchall to return one flat signal retry
        retry_time = datetime.datetime.now()
        original_timestamp = retry_time - datetime.timedelta(seconds=15)
        
        flat_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'test_bot',
                'market_position': 'flat',
                'prev_market_position': 'short',
                'id': 123
            }
        }
        
        # First call returns the retry signals
        # second call returns the original timestamp
        # third call returns a nearby directional signal
        self.mock_cursor.fetchall.return_value = [
            [101, json.dumps(flat_signal), 1, 123, retry_time]
        ]
        
        # Setup sequential returns for fetchone calls
        self.mock_cursor.fetchone.side_effect = [
            [original_timestamp],  # First call - get original signal timestamp
            [original_timestamp],  # Duplicate for the retry lookup 
            ['999']  # Third call - found a nearby directional signal
        ]
        
        # Call the function under test
        webapp_core.process_signal_retries()
        
        # Verify that the signal was marked as completed (retries_remaining=0)
        self.mock_cursor.execute.assert_any_call(
            "UPDATE signal_retries SET retries_remaining = 0 WHERE id = ?", 
            (101,)
        )
        
        # Verify that the signal was NOT published to Redis
        self.mock_redis.publish.assert_not_called()
    
    def test_process_signal_retries_processes_flat_without_nearby_directional(self):
        """Test that process_signal_retries processes a flat signal without a nearby directional signal"""
        # Mock the cursor's fetchall to return one flat signal retry
        retry_time = datetime.datetime.now()
        original_timestamp = retry_time - datetime.timedelta(seconds=15)
        
        flat_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'test_bot',
                'market_position': 'flat',
                'prev_market_position': 'short',
                'id': 123
            }
        }
        
        # First call returns the retry signals
        # second call returns the original timestamp
        # third call returns None (no nearby directional signal)
        self.mock_cursor.fetchall.return_value = [
            [101, json.dumps(flat_signal), 1, 123, retry_time]
        ]
        
        # Setup sequential returns for fetchone calls
        self.mock_cursor.fetchone.side_effect = [
            [original_timestamp],  # First call - get original signal timestamp
            [original_timestamp],  # Duplicate for the retry lookup
            None  # Third call - no nearby directional signal
        ]
        
        # Call the function under test
        webapp_core.process_signal_retries()
        
        # Verify the signal was published to Redis
        expected_signal = flat_signal.copy()
        expected_signal['is_retry'] = True
        self.mock_redis.publish.assert_called_once_with(
            'tradingview', 
            json.dumps(expected_signal)
        )
    
    def test_process_signal_retries_with_sequential_orders(self):
        """Test the scenario that failed: short followed by flat within 2 seconds"""
        # Mock the cursor's fetchall to return one flat signal retry
        now = datetime.datetime.now()
        
        # Short signal received 17 seconds ago (processed immediately)
        short_time = now - datetime.timedelta(seconds=17)
        
        # Flat signal received 15 seconds ago (but delayed 15s, so processing now)
        flat_time = now - datetime.timedelta(seconds=15)
        
        flat_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'test_bot',
                'market_position': 'flat',
                'prev_market_position': 'short',
                'id': 456
            }
        }
        
        # First call returns the retry signals
        # second call returns the original timestamp
        # third call should find the nearby directional signal (the short)
        self.mock_cursor.fetchall.return_value = [
            [102, json.dumps(flat_signal), 1, 456, now]
        ]
        
        # Setup sequential returns for fetchone calls
        self.mock_cursor.fetchone.side_effect = [
            [flat_time],  # First call - get original signal timestamp
            [flat_time],  # Duplicate for retry lookup
            [789]  # Third call - found the short signal (since we're using 10s window)
        ]
        
        # Call the function under test
        webapp_core.process_signal_retries()
        
        # Verify that the signal was marked as completed (retries_remaining=0)
        self.mock_cursor.execute.assert_any_call(
            "UPDATE signal_retries SET retries_remaining = 0 WHERE id = ?", 
            (102,)
        )
        
        # Verify that the signal was NOT published to Redis
        self.mock_redis.publish.assert_not_called()
    
    def test_goflat_after_goshort_skipped(self):
        """Test the specific scenario that caused the issue: goshort then goflat 2 seconds later"""
        # Mock the cursor's fetchall to return one flat signal retry
        now = datetime.datetime.now()
        
        # Short signal received and processed 2 seconds ago
        short_time = now - datetime.timedelta(seconds=2)
        
        # Flat signal time (original received time)
        flat_time = now
        
        flat_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'live',
                'market_position': 'flat',
                'prev_market_position': 'short',
                'id': 456
            }
        }
        
        # First call returns the retry signals
        self.mock_cursor.fetchall.return_value = [
            [102, json.dumps(flat_signal), 1, 456, now]
        ]
        
        # Set up a short signal in the database within 10s of flat signal
        self.mock_cursor.fetchone.side_effect = [
            [flat_time],  # First call - get original signal timestamp
            [flat_time],  # Duplicate for retry lookup
            [789]  # Third call - found the short signal 2s ago
        ]
        
        # Call the function under test
        webapp_core.process_signal_retries()
        
        # Verify that the signal was marked as completed (retries_remaining=0)
        self.mock_cursor.execute.assert_any_call(
            "UPDATE signal_retries SET retries_remaining = 0 WHERE id = ?", 
            (102,)
        )
        
        # Verify that the signal was NOT published to Redis
        self.mock_redis.publish.assert_not_called()
    
    def test_goshort_after_goflat_processed(self):
        """Test the opposite of the failure case: first goflat, then goshort 2 seconds later"""
        # Mock the cursor's fetchall to return one short signal retry
        now = datetime.datetime.now()
        
        # Flat signal received and processed 2 seconds ago
        flat_time = now - datetime.timedelta(seconds=2)
        
        # Short signal time (original received time)
        short_time = now
        
        short_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'live',
                'market_position': 'short',
                'prev_market_position': 'flat',
                'id': 457
            }
        }
        
        # First call returns the retry signals
        self.mock_cursor.fetchall.return_value = [
            [103, json.dumps(short_signal), 1, 457, now]
        ]
        
        # Set up timestamps
        self.mock_cursor.fetchone.side_effect = [
            [short_time]  # First call - get original signal timestamp
        ]
        
        # Call the function under test
        webapp_core.process_signal_retries()
        
        # Verify the signal WAS published to Redis (because directional signals are processed even after flat)
        self.mock_redis.publish.assert_called_once()
        
    def test_goflat_then_direction_change(self):
        """Test going flat then changing direction (flat → long → short)"""
        # Mock the cursor's fetchall to return a series of signals
        now = datetime.datetime.now()
        
        # First signal: flat
        flat_time = now - datetime.timedelta(seconds=4)
        
        # Second signal: long
        long_time = now - datetime.timedelta(seconds=2)
        
        # Third signal: short
        short_time = now
        
        # Process short signal
        short_signal = {
            'ticker': 'SOXL',
            'strategy': {
                'bot': 'live',
                'market_position': 'short',
                'prev_market_position': 'long',
                'id': 459
            }
        }
        
        # First call returns the retry signals
        self.mock_cursor.fetchall.return_value = [
            [105, json.dumps(short_signal), 1, 459, now]
        ]
        
        # Set up timestamps
        self.mock_cursor.fetchone.side_effect = [
            [short_time]  # First call - get original signal timestamp
        ]
        
        # Call the function under test
        webapp_core.process_signal_retries()
        
        # Verify the signal WAS published to Redis (direction change should be processed)
        self.mock_redis.publish.assert_called_once()
    
    def test_save_signal_schedules_retry(self):
        """Test that save_signal schedules a retry for a signal"""
        # Mock cursor fetchone for the INSERT...RETURNING
        self.mock_cursor.fetchone.return_value = [999]  # Signal ID
        
        # Call the function under test with a directional signal
        webapp_core.save_signal(self.test_signal_data)
        
        # Verify that the signal was inserted
        self.mock_cursor.execute.assert_any_call(
            """
            INSERT INTO signals 
            (ticker, bot, order_action, order_contracts, market_position, 
             market_position_size, order_price, order_message, position_pct) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, 
            unittest.mock.ANY  # Don't validate the exact args since timestamps vary
        )
        
        # Verify that the initial execution and verification retries were scheduled
        self.assertEqual(self.mock_cursor.execute.call_count, 5)

if __name__ == '__main__':
    unittest.main()