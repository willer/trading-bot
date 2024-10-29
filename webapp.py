import hashlib
import traceback
from flask import redirect, render_template, request, session, url_for
from webapp_core import app, get_db, is_logged_in, USER_CREDENTIALS, publish_signal, r, p
import webapp_reports
import webapp_dashboard
import webapp_stocks  # Add this line
import threading
import time

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
    data = request.data

    if data:
        data_dict = request.json
        try:
            publish_signal(data_dict)
        except Exception as e:
            app.logger.error(f"Error publishing signal: {e}; data: {data_dict}; traceback: {traceback.format_exc()}")
            return {"code": "failure", "message": str(e)}, 500
    else:
        app.logger.error(f"No data received")
        return {"code": "failure", "message": "No data received"}, 400

    return {"code": "success"}

# GET /health
@app.get("/health")
def health():

    # send a message to the redis channel to test connectivity
    r.publish('tradingview', 'health check')
    # check if we got a response 
    message = p.get_message(timeout=15)
    if message and message['type'] == 'message':
        return {"code": "success"}

    if message != None:
        return {"code": "failure", "message-type": message['type'], "message": message['data']}, 500
    else:
        return {"code": "failure", "message-type": "timeout", "message": "no message received"}, 500

def retry_checker():
    while True:
        try:
            process_signal_retries()
        except Exception as e:
            app.logger.error(f"Error processing retries: {e}")
        time.sleep(5)  # Check every 5 seconds

# Start the retry checker thread when the app starts
if __name__ == '__main__':
    retry_thread = threading.Thread(target=retry_checker, daemon=True)
    retry_thread.start()
    
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(debug=True)
