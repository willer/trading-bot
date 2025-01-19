import hashlib
import logging
from logging.handlers import RotatingFileHandler
from flask import redirect, render_template, request, session, url_for
from webapp_core import app, get_db, is_logged_in, USER_CREDENTIALS, save_signal, r, p, process_signal_retries
from flask_apscheduler import APScheduler
import webapp_reports
import webapp_dashboard
import webapp_stocks
from datadog import statsd
from core_error import handle_ex
import os

# Set up logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

file_handler = RotatingFileHandler(
    os.path.join(log_dir, 'webapp.log'),
    maxBytes=1024 * 1024,  # 1MB
    backupCount=10
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Webapp startup')

# Initialize scheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# Add scheduler job
@scheduler.task('interval', id='process_retries', seconds=5, misfire_grace_time=None)
def scheduled_retry_check():
    with app.app_context():
        try:
            process_signal_retries()
        except Exception as e:
            error_text = handle_ex(e, context="process_retries", service="webapp")
            app.logger.error(error_text)

# New login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

# New logout route
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# Modify existing routes to require login
@app.route('/')
def index():
    if not is_logged_in():
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

# POST /webhook
@app.post("/webhook")
def webhook():
    try:
        # Get the JSON data from the request
        data = request.get_json()
        if not data:
            raise ValueError("No JSON data received")

        # Save the signal and process it
        save_signal(data)
        return "ok"
    except Exception as e:
        error_text = handle_ex(e, context="webhook", service="webapp")
        app.logger.error(error_text)
        return str(e), 500

# GET /health
@app.get("/health")
def health():
    try:
        # send a message to the redis channel to test connectivity
        r.publish('tradingview', 'health check')
        
        # wait for response
        for i in range(10):
            message = p.get_message()
            if message and message['type'] == 'message' and message['data'] == b'ok':
                return "ok"
        
        raise Exception("Health check failed - no response from broker")
    except Exception as e:
        error_text = handle_ex(e, context="health_check", service="webapp")
        app.logger.error(error_text)
        return str(e), 500

if __name__ == '__main__':
    app.run(debug=False)
