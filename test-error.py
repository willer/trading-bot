#!/usr/bin/env python3
import configparser
from core_error import handle_ex
from broker_root import broker_root

def test_basic_error():
    """Test basic error handling with different services"""
    print("\n1. Testing basic error...")
    try:
        raise ValueError("This is a test error")
    except Exception as e:
        handle_ex(e, context="test_basic", service="test")

def test_with_tags():
    """Test error handling with extra tags"""
    print("\n2. Testing error with tags...")
    try:
        raise Exception("Test error with custom tags")
    except Exception as e:
        handle_ex(
            e, 
            context="test_tags", 
            service="test",
            extra_tags=['component:test', 'test_type:tags']
        )

def test_string_error():
    """Test handling of string errors vs exceptions"""
    print("\n3. Testing string error...")
    handle_ex(
        "This is a string error message",
        context="test_string",
        service="test",
        extra_tags=['error_type:string']
    )

def test_broker_error():
    """Test broker error handling with real account"""
    print("\n4. Testing broker error...")
    
    # Get a real account from config
    config = configparser.ConfigParser()
    config.read('config.ini')
    bot = config['DEFAULT'].get('test-bot', 'live')  # default to 'live' if no test bot specified
    accounts = config[f'bot-{bot}']['accounts'].split(',')
    test_account = accounts[0]  # use first account
    
    broker = broker_root(bot, test_account)
    try:
        raise Exception("Test broker error with real account")
    except Exception as e:
        broker.handle_ex(e, "test_broker")

def main():
    print("Testing error handling system...")
    
    test_basic_error()
    test_with_tags()
    test_string_error()
    test_broker_error()
    
    print("\nAll test errors have been sent to Datadog. Please check your Datadog events page.")

if __name__ == "__main__":
    main() 