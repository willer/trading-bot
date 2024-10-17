#!/bin/sh

logfile=logs/$0.log
max_log_size=10M
num_logs_to_keep=5

# Function to rotate logs
rotate_logs() {
    if [ -f "$logfile" ] && [ $(stat -c %s "$logfile") -ge $(numfmt --from=iec $max_log_size) ]; then
        for i in $(seq $((num_logs_to_keep-1)) -1 1); do
            if [ -f "${logfile}.$i" ]; then
                mv "${logfile}.$i" "${logfile}.$((i+1))"
            fi
        done
        mv "$logfile" "${logfile}.1"
        touch "$logfile"
    fi
}

# Ensure logs directory exists
mkdir -p logs

# start webapp/webhook-receiver (move to port 6001 to get away from Mac airplay issues)
export FLASK_APP=webapp
export FLASK_ENV=development
export FLASK_DEBUG=1
export PYTHONPATH=.

py=`which python`
if [ -z "$py" ]; then py=`which python3`; fi

while true; do
    rotate_logs
    echo --------------------------------- |tee -a $logfile
    date |tee -a $logfile
    echo Starting up |tee -a $logfile
    "$py" -m flask run -p 6008 2>&1 |tee -a $logfile
    echo Restarting in 2s |tee -a $logfile
    sleep 2
done

