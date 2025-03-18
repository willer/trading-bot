import configparser
import traceback
from datadog import initialize, statsd
from datadog.api import Event
import logging
import urllib3

# For SMS notifications
try:
    from textmagic.rest import TextmagicRestClient
    TEXTMAGIC_AVAILABLE = True
except ImportError:
    TEXTMAGIC_AVAILABLE = False
    print("TextMagic library not found. SMS notifications will be disabled.")

# Suppress SSL connection noise
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Initialize Datadog on module import
config = configparser.ConfigParser()
config.read('config.ini')

# Debug config reading
dd_api_key = config['DEFAULT'].get('datadog-api-key', '')
dd_app_key = config['DEFAULT'].get('datadog-app-key', '')
print(f"Initializing Datadog with API key: {dd_api_key[:8]}... App key: {dd_app_key[:8]}...")

# TextMagic configuration
textmagic_username = config['DEFAULT'].get('textmagic-username', '')
textmagic_token = config['DEFAULT'].get('textmagic-token', '')
textmagic_phone = config['DEFAULT'].get('textmagic-phone', '')
textmagic_enabled = (TEXTMAGIC_AVAILABLE and textmagic_username and textmagic_token and textmagic_phone)

if textmagic_enabled:
    print(f"TextMagic SMS notifications enabled for {textmagic_phone}")
    textmagic_client = TextmagicRestClient(textmagic_username, textmagic_token)
else:
    print("TextMagic SMS notifications disabled (missing credentials or library)")

options = {
    'api_key': dd_api_key,
    'app_key': dd_app_key,
    'api_host': 'https://api.us5.datadoghq.com'
}

initialize(**options)

def handle_ex(e, context="unknown", service="unknown", extra_tags=None):
    """
    Centralized exception handler that sends events and metrics to Datadog
    
    Args:
        e: The exception or error message
        context: String describing where/how the error occurred
        service: The service name (e.g., 'webapp', 'broker')
        extra_tags: Additional tags to include with the event
    """
    # Build tags list
    tags = [
        f'service:{service}',
        f'error_context:{context}'
    ]
    
    # Add any extra tags
    if extra_tags:
        tags.extend(extra_tags)
    
    # Track error metric
    try:
        print(f"Sending metric to Datadog: {service}.errors with tags {tags}")
        statsd.increment(f'{service}.errors', tags=tags)
    except Exception as metric_e:
        print(f"Failed to send metric: {metric_e}")
    
    # Get error details
    error_text = str(e) if isinstance(e, str) else f"{e}\n{traceback.format_exc()}"
    
    # Create event title based on service
    title = f'{service.title()} Error'
    if service == 'broker' and 'bot' in dict(tag.split(':') for tag in tags):
        bot = dict(tag.split(':') for tag in tags).get('bot')
        account = dict(tag.split(':') for tag in tags).get('account')
        title = f'Broker Error: {bot}/{account}'
    
    # Send detailed event
    try:
        print(f"Sending event to Datadog: {title}")
        event_response = Event.create(
            title=title,
            text=f'Context: {context}\n\nError:\n{error_text}',
            alert_type='error',
            tags=tags
        )
        print(f"Event response: {event_response}")
    except Exception as event_e:
        print(f"Failed to send event: {event_e}")
    
    # Send SMS notification if TextMagic is enabled
    if 'textmagic_enabled' in globals():
        # Only send SMS for trade-related failures or critical errors
        is_trade_error = (
            'ORDER FAILED' in str(e) or 
            context.startswith('trade_') or 
            (service == 'broker' and ('timeout' in str(e).lower() or 'failed' in str(e).lower()))
        )
        
        if is_trade_error:
            try:
                sms_message = f"{title}: {context} - {str(e)[:100]}"
                textmagic_client.messages.create(phones=textmagic_phone, text=sms_message)
                print(f"SMS notification sent to {textmagic_phone}")
            except Exception as sms_e:
                print(f"Failed to send SMS: {sms_e}")
        else:
            print(f"SMS notification skipped - not a trade-related error")
    
    print(f"Error in {context}: {error_text}")  # Console logging
    return error_text  # Return for optional use by caller