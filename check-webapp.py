import nest_asyncio
import configparser
import traceback
from datadog import initialize, statsd
from datadog.api import Event

nest_asyncio.apply()

import requests

config = configparser.ConfigParser()
config.read('config.ini')

# Initialize the Datadog client
initialize(
    api_key=config['DEFAULT'].get('datadog-api-key', ''),
    app_key=config['DEFAULT'].get('datadog-app-key', '')
)

def handle_ex(e):
    # Send an event to Datadog
    error_text = str(e) if isinstance(e, str) else traceback.format_exc()
    
    # Increment error counter
    statsd.increment('webapp.health_check.errors', tags=['service:webapp'])
    
    # Send detailed event
    Event.create(
        title='Webapp Health Check Failed',
        text=error_text,
        alert_type='error',
        tags=['service:webapp', 'monitor:health_check']
    )

try:
    # try to load the url
    url = f"http://{config['DEFAULT']['ngrok-subdomain']}.ngrok.io/health"

    response = requests.get(url)
    if response.status_code == 200:
        # Track successful health checks
        statsd.increment('webapp.health_check.success', tags=['service:webapp'])
        exit(0)
    else:
        raise Exception(f"Error! The server returned a {response.status_code} status code.")

except Exception as e:
    handle_ex(e)
    raise

