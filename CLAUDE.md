# CLAUDE.md - Guidelines for the tradingview-interactive-brokers project

## Build & Run Commands
- Run webapp: `python -m flask run --host=0.0.0.0 --port=6008`  
- Run broker: `python -u broker.py live`
- Test error handling: `python test-error.py`
- Run unit tests: 
  - All tests: `./run-unittests.sh` or `run-unittests.bat` on Windows
  - Webapp tests only: `./run-unittests-webapp.sh`
  - Broker tests only: `./run-unittests-broker.sh`

## Code Style
- **Formatting**: snake_case for functions/variables, PascalCase for classes
- **Imports**: Group imports (stdlib, third-party, local) with stdlib first
- **Error Handling**: Use centralized `handle_ex()` from core_error.py with context and service info
- **Architecture**: Use broker_root as base class with specific implementations (broker_ibkr, broker_alpaca)
- **Async Pattern**: Use async/await for trade execution and time-sensitive operations
- **Config**: Use configparser with config.ini (see config-template.ini for reference)
- **Logging**: Use Datadog for metrics and events, standard logging for console output
- **Structure**: Flask app (webapp.py) and broker system communicate through Redis pub/sub

## Tools
- Redis for component messaging
- Datadog for monitoring/logging
- Flask for web interface
- Interactive Brokers or Alpaca API for trading

## Testing
- Unit tests for webapp and broker components using unittest framework
- Test signal deduplication with test_webapp.py
- Test trade execution logic with test_broker.py
- Mocking for database, Redis, and external services
- Fixed issue with flat signals not being properly deduplicated when immediately following a directional signal

## File Overview
- **broker.py**: Main broker process that listens for trade signals via Redis and executes trades
- **broker_root.py**: Abstract base class defining broker interface 
- **broker_ibkr.py**: Interactive Brokers implementation for trade execution
- **broker_alpaca.py**: Alpaca Markets implementation for trade execution
- **webapp.py**: Flask web application that receives webhook signals and publishes to Redis
- **webapp_core.py**: Core functionality for webapp including signal processing
- **webapp_dashboard.py**: Dashboard view for the web interface
- **webapp_reports.py**: Reporting functionality for the web interface
- **webapp_stocks.py**: Stock information display functionality
- **core_error.py**: Centralized error handling including Datadog integration

## Recent Important Fixes
- March 25, 2025: Fixed position percentage scaling in broker.py to properly scale signal percentages by configured percentages for futures trading.
- March 5, 2025: Fixed signal deduplication in webapp_core.py to use original signal timestamp (not processing time) and expanded window from 3 to 10 seconds to properly skip flat signals after a directional change.
- March 5, 2025: Added comprehensive test coverage for webapp signal processing and broker trade execution.