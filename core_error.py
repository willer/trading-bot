import configparser
import traceback
import logging
import urllib3

# For SMS notifications
try:
    from textmagic.rest import TextmagicRestClient
    TEXTMAGIC_AVAILABLE = True
except ImportError:
    TEXTMAGIC_AVAILABLE = False
    print("TextMagic library not found. SMS notifications will be disabled.")

# For Datadog monitoring
try:
    from datadog import initialize, statsd
    from datadog.api import Event
    DATADOG_AVAILABLE = True
except ImportError:
    DATADOG_AVAILABLE = False
    print("Datadog library not found. Monitoring will be disabled.")

# Suppress SSL connection noise
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Initialize Datadog on module import
config = configparser.ConfigParser()
config.read('config.ini')

# Debug config reading - safely get values with defaults
dd_api_key = config.get('DEFAULT', 'datadog-api-key', fallback='')
dd_app_key = config.get('DEFAULT', 'datadog-app-key', fallback='')
print(f"Initializing Datadog with API key: {dd_api_key[:8] if dd_api_key else 'None'}... App key: {dd_app_key[:8] if dd_app_key else 'None'}...")

# Check if Datadog is properly configured
datadog_enabled = (DATADOG_AVAILABLE and dd_api_key and dd_app_key)

if datadog_enabled:
    try:
        options = {
            'api_key': dd_api_key,
            'app_key': dd_app_key,
            'api_host': 'https://api.us5.datadoghq.com'
        }
        initialize(**options)
        print("Datadog monitoring enabled")
    except Exception as e:
        print(f"Failed to initialize Datadog: {e}")
        datadog_enabled = False
else:
    print("Datadog monitoring disabled (missing API keys or library)")

# TextMagic configuration
textmagic_username = config.get('DEFAULT', 'textmagic-username', fallback='')
textmagic_token = config.get('DEFAULT', 'textmagic-token', fallback='')
textmagic_phone = config.get('DEFAULT', 'textmagic-phone', fallback='')
textmagic_enabled = (TEXTMAGIC_AVAILABLE and textmagic_username and textmagic_token and textmagic_phone)

if textmagic_enabled:
    print(f"TextMagic SMS notifications enabled for {textmagic_phone}")
    textmagic_client = TextmagicRestClient(textmagic_username, textmagic_token)
else:
    print("TextMagic SMS notifications disabled (missing credentials or library)")

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
    
    # Track error metric if Datadog is enabled
    if datadog_enabled:
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
    
    # Send detailed event if Datadog is enabled
    if datadog_enabled:
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
    if textmagic_enabled and 'textmagic_client' in globals():
        # Only send SMS for critical trade execution failures or connection failures
        error_str = str(e).lower()
        
        # Filter criteria for SMS notifications
        is_critical_error = (
            # Connection failures only when related to trading
            (('failed to connect' in error_str or ('connection' in error_str and 'attempt' in error_str)) and
             service == 'broker' and context.startswith('trade_')) or
            
            # Price lookup failures
            (service == 'broker' and
             context.startswith('trade_') and
             'error trying to retrieve stock price' in error_str) or
            
            # Traditional trade errors
            (service == 'broker' and
             context.startswith('trade_') and 
             'ORDER FAILED' in str(e) and 
             ('order rejected' in error_str or 
              'insufficient buying power' in error_str or
              'position limit exceeded' in error_str or
              'margin requirement' in error_str))
        )
        
        if is_critical_error:
            try:
                sms_message = f"{title}: {context} - {str(e)[:100]}"
                textmagic_client.messages.create(phones=textmagic_phone, text=sms_message)
                print(f"SMS notification sent to {textmagic_phone}")
            except Exception as sms_e:
                print(f"Failed to send SMS: {sms_e}")
        else:
            print(f"SMS notification skipped - not a critical trade error")
    
    print(f"Error in {context}: {error_text}")  # Console logging
    return error_text  # Return for optional use by caller