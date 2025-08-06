# Trading View Interactive Brokers Integration

A trading bot that receives TradingView or other algorithmic trading signals via webhook, and places those trades on Interactive Brokers or Alpaca.

## Overview

This application consists of three main components:
1. **Webapp**: A Flask web server that receives webhook signals from TradingView
2. **Broker**: A service that processes trading signals and executes them on your broker(s)
3. **Ngrok**: A tunneling service to expose your local webhook endpoint to the internet

The system supports:
- Multiple accounts (IBKR and/or Alpaca)
- Error monitoring and alerts through Datadog
- Critical error SMS notifications via TextMagic
- Dashboard visualization of trading activity
- Configurable position sizing based on percentage of account

## Demo Video:

https://www.youtube.com/watch?v=zsYKfzCNPPU

## Support Part Time Larry's Work

__Visit Interactive Brokers__

https://www.interactivebrokers.com/mkt/?src=ptlg&url=%2Fen%2Findex.php%3Ff%3D1338

__Buy Him a Coffee__

https://buymeacoffee.com/parttimelarry

## Diagram 

![Diagram](diagram.png)

## Prerequisites / Installation

1. Install Python 3.7+ and pip3
2. Install required dependencies:
```
pip3 install -r requirements.txt
```
3. Download and install ngrok from https://ngrok.com/
4. For Interactive Brokers:
   - Install Trader Workstation (TWS) or IB Gateway from https://www.interactivebrokers.com/
   - Create and fund your IB account (paper or live)
5. For Alpaca:
   - Create an Alpaca account and generate API keys

## Configuration

1. Copy `config-template.ini` to `config.ini`
2. Configure your settings:
   - Set your `ngrok-subdomain` (requires paid ngrok account) and `signals-password`
   - Configure Datadog API keys for monitoring (optional)
   - Configure TextMagic credentials for SMS notifications (optional)
   - Add your broker accounts:
     - For IBKR: configure host and port
     - For Alpaca: configure API keys
   - Configure position sizing for each security and account

Example configuration for accounts:
```ini
[U8438939]
# Steve margin account
driver = ibkr
host = 127.0.0.1
port = 7496
use-futures = yes
SOXL-pct = 70  # use 70% of account size for SOXL
TQQQ-pct = 20  # use 20% of account size for TQQQ
default-pct = 0  # default for unspecified securities

[PA3I5VZDCGPF]
# Paper trading on Alpaca
driver = alpaca
key = YOUR_ALPACA_KEY
secret = YOUR_ALPACA_SECRET
paper = yes
use-futures = no
SOXL-pct = 50
default-pct = 0
```

## Starting the Services

Run each of these commands in separate terminal windows:

1. Start the web server:
   ```
   ./start-webapp.sh  # For Unix/Mac
   start-webapp.bat   # For Windows
   ```

2. Start the broker service:
   ```
   ./start-broker.sh  # For Unix/Mac
   ```

3. Start ngrok to expose your webhook:
   ```
   ./start-ngrok.sh  # For Unix/Mac
   ```

If using Interactive Brokers:
- Open TWS or IB Gateway and log in
- In settings, enable "ActiveX and Socket Clients" and disable "Read Only API"
- Accept any API connection warnings

## TradingView Alert Setup

1. Create a new alert in TradingView
2. Set the webhook URL to: `https://YOUR-SUBDOMAIN.ngrok.io/webhook`
3. Configure the alert message using this template:

```json
{
	"time": "{{timenow}}",
	"exchange": "{{exchange}}",
	"ticker": "{{ticker}}",
	"bar": {
		"time": "{{time}}",
		"open": {{open}},
		"high": {{high}},
		"low": {{low}},
		"close": {{close}},
		"volume": {{volume}}
	},
	"strategy": {
        "bot": "live",
		"position:size": {{strategy.position_size}},
		"order_action": "{{strategy.order.action}}",
		"order_contracts": {{strategy.order.contracts}},
		"order_price": {{strategy.order.price}},
        "order_id": "{{strategy.order.id}}",
		"market_position": "{{strategy.market_position}}",
		"market_position_size": {{strategy.market_position_size}},
		"prev_market_position": "{{strategy.prev_market_position}}",
		"prev_market_position_size": {{strategy.prev_market_position_size}}
	},
	"passphrase": "YOUR-SIGNALS-PASSWORD"
}
```

Replace `YOUR-SIGNALS-PASSWORD` with the value from your config.ini.

## Monitoring and Notifications

### Dashboard
Access the dashboard at: `http://localhost:6008/dashboard`

### Datadog Integration
If configured, the application will:
- Send error metrics and events to Datadog
- Monitor service health

### SMS Notifications
If TextMagic is configured, the system will send SMS alerts for:
- Critical trade execution errors
- Connection failures during trade operations

## Troubleshooting

Common issues:

- **Connection issues**: IBKR may disconnect if you log in elsewhere or during TWS's daily restart
- **Signal not received**: Ensure your ngrok tunnel is running and check the logs
- **Trade not executed**: Verify that:
  - The passphrase matches your config.ini
  - Your broker account has sufficient funds
  - IBKR API connections are enabled
  - Check the logs in the broker terminal

If a trade fails:
- Monitor the dashboard for error messages
- Check email alerts from TradingView (if configured)
- Use the logs to diagnose the issue

## Testing

Run unit tests with:
```
./run-unittests.sh
```

For specific test suites:
```
./run-unittests-broker.sh
./run-unittests-webapp.sh
```

## License

This software is freely available for use and modification.

## References, Tools, and Libraries Used:

* ngrok - https://ngrok.com - provides tunnel to localhost
* Flask - https://flask.palletsprojects.com/ - webapp
* Redis - https://pypi.org/project/redis/ - Redis client for Python
* ib_insync - https://ib-insync.readthedocs.io
* Redis pubsub - https://www.twilio.com/blog/sms-microservice-python-twilio-redis-pub-sub, https://redislabs.com/ebook/part-2-core-concepts/chapter-3-commands-in-redis/3-6-publishsubscribe/
* asyncio snippet - https://stackoverflow.com/questions/54153332/schedule-asyncio-task-to-execute-every-x-seconds
* ib_insyc examples - https://github.com/hackingthemarkets/interactive-brokers-demo/blob/main/order.py
