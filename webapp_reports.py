from flask import jsonify, render_template, request, redirect, url_for
from webapp_core import app, get_db, get_signals, is_logged_in
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.express as px

########################################################################################
# REPORTS
########################################################################################
@app.route('/reports')
def reports():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    timeframe = request.args.get('timeframe', 'mtd')
    selected_tickers = request.args.getlist('tickers')
    start_date = get_start_date(timeframe)
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT DISTINCT ticker 
        FROM signals 
        WHERE timestamp >= %s 
        ORDER BY ticker
    """, (start_date,))
    all_tickers = [row[0] for row in cursor.fetchall()]
    
    return render_template('reports.html', 
                           timeframe=timeframe, 
                           all_tickers=all_tickers, 
                           selected_tickers=selected_tickers,
                           date=datetime)

@app.route('/get_tickers')
def get_tickers():
    if not is_logged_in():
        return jsonify({'error': 'Not logged in'}), 401
    
    timeframe = request.args.get('timeframe', 'mtd')
    start_date = get_start_date(timeframe)
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT DISTINCT ticker 
        FROM signals 
        WHERE timestamp >= %s
        ORDER BY ticker
    """, (start_date,))
    tickers = [row[0] for row in cursor.fetchall()]
    
    return jsonify({'tickers': tickers})

@app.route('/get_chart_data')
def get_chart_data():
    if not is_logged_in():
        return jsonify({'error': 'Not logged in'}), 401
    
    timeframe = request.args.get('timeframe', 'mtd')
    selected_tickers = request.args.getlist('tickers')
    start_date = get_start_date(timeframe)
    app.logger.info(f"Timeframe={timeframe}, Start Date={start_date}, Selected Tickers={selected_tickers}")
    
    signals = get_signals() # last 500 signals

    # filter out anything before start_date
    signals = [signal for signal in signals if signal['timestamp'] >= start_date]

    # filter out any tickers not in selected_tickers
    if selected_tickers:
        signals = [signal for signal in signals if signal['ticker'] in selected_tickers]

    # for reporting, fix any bot=human record that's against NQ1! or TQQQ and is 4pm-8pm to be bot=live
    for signal in signals:
        if signal['bot'] == 'human' and (signal['ticker'] == 'NQ1!' or signal['ticker'] == 'TQQQ') and signal['timestamp'].hour >= 16 and signal['timestamp'].hour <= 20:
            signal['bot'] = 'live'

    df = pd.DataFrame(signals)
    df['date'] = pd.to_datetime(df['timestamp']).dt.date  # Use timestamp for date, not the normalized date

    # Group by date and bot only
    df_grouped = df.groupby(['date', 'bot']).size().reset_index(name='count')
    
    color_map = {'human': '#FF4136', 'live': '#0074D9', 'test': '#2ECC40'}
    
    if timeframe in ['ytd', '1year']:
        df_grouped['date'] = pd.to_datetime(df_grouped['date']).dt.to_period('W').apply(lambda r: r.start_time)
        df_grouped = df_grouped.groupby(['date', 'bot'])['count'].sum().reset_index()
        x_title = 'Week'
    else:
        x_title = 'Date'
    
    # Sort the dataframe by date to ensure correct ordering
    df_grouped = df_grouped.sort_values('date')
    app.logger.info(f"First Chart Date range: {df_grouped['date'].min()} to {df_grouped['date'].max()}")
    app.logger.info(f"First Chart Number of data points: {len(df_grouped)}")
    app.logger.info(df_grouped.head())
    
    fig_time = px.line(df_grouped, x='date', y='count', color='bot',
                       title=f'Number of Signals by {"Week" if timeframe in ["ytd", "1year"] else "Day"}',
                       labels={'date': x_title, 'count': 'Number of Signals'},
                       color_discrete_map=color_map)
    
    # Ensure proper date formatting for x-axis (dates only, no time)
    fig_time.update_xaxes(
        tickformat="%Y-%m-%d",
        type='date',
        tickmode='auto',
        nticks=20,  # Adjust this value to control the number of ticks
        autorange=True
    )

    # Update hover template to show only date and count
    fig_time.update_traces(
        hovertemplate='%{x|%Y-%m-%d}<br>Count: %{y}<extra></extra>'
    )
    
    # Set the x-axis range to the actual data range
    if not df_grouped.empty:
        min_date = df_grouped['date'].min()
        max_date = df_grouped['date'].max()
        fig_time.update_xaxes(range=[min_date, max_date])

    # Print debug information
    app.logger.info(f"Date range in data: {min_date} to {max_date}")
    app.logger.info(f"Grouped Number of data points: {len(df_grouped)}")
    app.logger.info(df_grouped.head())  # Print the first few rows of the data
    
    # For the weekly chart, we need to filter the original dataframe again
    df['day_of_week'] = pd.to_datetime(df['date']).dt.day_name()
    fig_weekly = px.bar(df.groupby(['day_of_week', 'bot'])['bot'].count().reset_index(name='count'),
                        x='day_of_week', y='count', color='bot', barmode='group',
                        title='Number of Signals by Day of Week',
                        labels={'count': 'Number of Signals', 'day_of_week': 'Day of Week'},
                        category_orders={'day_of_week': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']},
                        color_discrete_map=color_map)
    
    def convert_figure_to_dict(fig):
        fig_dict = fig.to_dict()
        for trace in fig_dict['data']:
            for key, value in trace.items():
                if isinstance(value, np.ndarray):
                    trace[key] = value.tolist()
        return fig_dict

    return jsonify({
        'time_chart': convert_figure_to_dict(fig_time),
        'weekly_chart': convert_figure_to_dict(fig_weekly)
    })

def get_start_date(timeframe):
    end_date = datetime.now()
    if timeframe == 'ytd':
        return datetime(end_date.year, 1, 1)
    elif timeframe == 'mtd':
        return datetime(end_date.year, end_date.month, 1)
    elif timeframe == 'qtd':
        quarter = (end_date.month - 1) // 3 + 1
        return datetime(end_date.year, 3 * quarter - 2, 1)
    elif timeframe == '1year':
        return end_date - timedelta(days=365)
    elif timeframe == '30days':
        return end_date - timedelta(days=30)
    elif timeframe == '1week':
        return end_date - timedelta(days=7)
    else:
        return datetime(end_date.year, end_date.month, 1)  # Default to MTD