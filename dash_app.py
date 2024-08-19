import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.express as px
import pandas as pd
from sqlalchemy import func
from datetime import datetime, timedelta

def create_dash_app(flask_app, db):
    dash_app = dash.Dash(__name__, server=flask_app, url_base_pathname='/dashboard/')
    
    # Define your layout
    dash_app.layout = html.Div([
        html.H1("Manual Trades Dashboard"),
        
        dcc.DatePickerRange(
            id='date-range',
            start_date=datetime.now().date() - timedelta(days=30),
            end_date=datetime.now().date(),
            display_format='YYYY-MM-DD'
        ),
        
        dcc.Dropdown(
            id='date-preset',
            options=[
                {'label': 'Year to Date', 'value': 'ytd'},
                {'label': 'Month to Date', 'value': 'mtd'},
                {'label': 'Last 1 Year', 'value': 'last_year'}
            ],
            value='last_year'
        ),
        
        dcc.Graph(id='trades-per-day'),
        dcc.Graph(id='trades-per-weekday')
    ])

    @dash_app.callback(
        [Output('trades-per-day', 'figure'),
         Output('trades-per-weekday', 'figure'),
         Output('date-range', 'start_date'),
         Output('date-range', 'end_date')],
        [Input('date-range', 'start_date'),
         Input('date-range', 'end_date'),
         Input('date-preset', 'value')]
    )
    def update_graphs(start_date, end_date, date_preset):
        if date_preset:
            today = datetime.now().date()
            if date_preset == 'ytd':
                start_date = datetime(today.year, 1, 1).date()
                end_date = today
            elif date_preset == 'mtd':
                start_date = datetime(today.year, today.month, 1).date()
                end_date = today
            elif date_preset == 'last_year':
                start_date = today - timedelta(days=365)
                end_date = today

        # Query your database for manual trades
        trades = db.session.query(
            func.date(db.Table('signals').c.timestamp).label('date'),
            func.count().label('count')
        ).filter(
            db.Table('signals').c.bot == 'human',
            db.Table('signals').c.timestamp.between(start_date, end_date)
        ).group_by(func.date(db.Table('signals').c.timestamp)).all()

        df = pd.DataFrame(trades, columns=['date', 'count'])
        
        # Trades per day chart
        fig_per_day = px.bar(df, x='date', y='count', title='Manual Trades per Day')
        
        # Trades per weekday chart
        df['weekday'] = pd.to_datetime(df['date']).dt.day_name()
        fig_per_weekday = px.bar(df.groupby('weekday', sort=False)['count'].sum().reset_index(), 
                                 x='weekday', y='count', title='Manual Trades per Day of Week')

        return fig_per_day, fig_per_weekday, start_date, end_date

    return dash_app