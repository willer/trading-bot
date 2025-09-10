from flask import render_template, redirect, url_for
from webapp_core import app, is_logged_in, eastern_now
from datetime import datetime

@app.route('/stocks')
def stocks():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    return render_template('stocks.html', current_time=eastern_now())


