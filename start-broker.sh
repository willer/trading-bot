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

# start broker connection point
# this is in a while loop because sometimes the broker script crashes
while true; do
    rotate_logs
    echo --------------------------------- |tee -a $logfile
    date |tee -a $logfile
    echo Starting up |tee -a $logfile
    py=`which python`
    if [ -z "$py" ]; then py=`which python3`; fi
    "$py" -u broker.py live 2>&1 |tee -a $logfile
    echo Restarting in 2s |tee -a $logfile
    sleep 2
done
