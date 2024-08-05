#!/bin/sh

logfile=$0.log

# start webapp/webhook-receiver (move to port 6001 to get away from Mac airplay issues)
py=`which python`
if [ -z "$py" ]; then py=`which python3`; fi
"$py" check-webapp.py 2>&1 |tee -a $logfile

