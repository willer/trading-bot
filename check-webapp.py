import nest_asyncio
import configparser
import traceback
from textmagic.rest import TextmagicRestClient

nest_asyncio.apply()

import requests

config = configparser.ConfigParser()
config.read('config.ini')

def handle_ex(e):
    tmu = config['DEFAULT']['textmagic-username']
    tmk = config['DEFAULT']['textmagic-key']
    tmp = config['DEFAULT']['textmagic-phone']
    if tmu != '':
        tmc = TextmagicRestClient(tmu, tmk)
        # if e is a string send it, otherwise send the first 300 chars of the traceback
        if isinstance(e, str):
            tmc.messages.create(phones=tmp, text="webapp FAIL " + e)
        else:
            tmc.messages.create(phones=tmp, text="webapp FAIL " + traceback.format_exc()[0:300])

try:
    # try to load the url
    url = f"http://{config['DEFAULT']['ngrok-subdomain']}.ngrok.io/health"

    #print(f"Checking {url}")
    response = requests.get(url)
    if response.status_code == 200:
        exit(0)
    else:
        raise Exception(f"Error! The server returned a {response.status_code} status code.")

except Exception as e:
    handle_ex(e)
    raise

