#!/bin/sh

logfile=$0.log

# start broker connection point
# this is in a while loop because sometimes the broker script crashes
while true; do
	echo --------------------------------- |tee -a $logfile
	date |tee -a $logfile
	echo Starting up |tee -a $logfile
	py=`which python`
	if [ -z "$py" ]; then py=`which python3`; fi
	"$py" -u broker.py live 2>&1 |tee -a $logfile
	echo Restarting in 2s |tee -a $logfile
	sleep 2
done
