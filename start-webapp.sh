#!/bin/sh

# Source Datadog functions
. ./datadog-shell.sh

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

# Rotate logs if needed
rotate_logs

# Set up Python environment
export PYTHONPATH=.

# Activate virtual environment if it exists
if [ -f .venv/bin/activate ]; then
    . .venv/bin/activate
fi

# Find Python executable
py=`which python`
if [ -z "$py" ]; then py=`which python3`; fi

# Start the webapp with monitoring
while true; do
    # Send startup event
    dd_event \
        "Webapp Started" \
        "Webapp process has been started" \
        "info" \
        "service:webapp"

    echo "Starting webapp..." | tee -a "$logfile"
    
    # Start Gunicorn with monitoring (with proper quoting)
    dd_monitor_cmd "webapp" '"'"$py"'" -m gunicorn --bind 0.0.0.0:6008 --workers 1 --threads 2 --timeout 120 --access-logfile - webapp:app' 2>&1 | tee -a "$logfile"
    
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "Webapp crashed with exit code $exit_code" | tee -a "$logfile"
        dd_event \
            "Webapp Crashed" \
            "Webapp process exited with code $exit_code, restarting in 2s" \
            "warning" \
            "service:webapp"
        sleep 2
    fi
done

