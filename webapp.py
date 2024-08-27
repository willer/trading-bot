import hashlib
from flask import redirect, render_template, request, session, url_for
from webapp_core import app, get_db, is_logged_in, USER_CREDENTIALS, r, p
import webapp_reports
import webapp_dashboard

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
        r.publish('tradingview', data)

        data_dict = request.json

        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO signals (ticker, bot, order_action, order_contracts, market_position, market_position_size, order_price, order_message) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (data_dict['ticker'], 
                data_dict['strategy']['bot'],
                data_dict['strategy']['order_action'], 
                data_dict['strategy']['order_contracts'],
                data_dict['strategy']['market_position'],
                data_dict['strategy']['market_position_size'],
                data_dict['strategy']['order_price'],
                request.get_data()))
        db.commit()

        return data

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

########################################################################################
# MAIN
########################################################################################
if __name__ == '__main__':
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(debug=True)