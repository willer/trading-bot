#!/bin/sh

# Source Datadog functions
. ./datadog-shell.sh

logfile=logs/ngrok.log
mkdir -p logs

# start ngrok proxy -- requires paid account if you want a fixed subdomain
subd=`grep ngrok-subdomain config.ini |sed 's/\r//'|awk '{print $3}'`
echo "Running while config.ini says 'ngrok-run = yes'"

while grep -s "ngrok-run = yes" config.ini >/dev/null ; do
	echo "Starting ngrok..." | tee -a "$logfile"
	echo "--------------------------------" | tee -a "$logfile"
	date | tee -a "$logfile"

	# Send startup event
	dd_event \
		"Ngrok Started" \
		"Ngrok process has been started" \
		"info" \
		"service:ngrok"
	
	# Start ngrok with monitoring
	if [ "$subd" = "" ] ; then
		dd_monitor_cmd "ngrok" "ngrok http 6008" 2>&1 | tee -a "$logfile"
	else
		dd_monitor_cmd "ngrok" "ngrok http --subdomain=$subd 6008" 2>&1 | tee -a "$logfile"
	fi
	
	exit_code=$?
	if [ $exit_code -ne 0 ]; then
		echo "Ngrok crashed with exit code $exit_code" | tee -a "$logfile"
		dd_event \
			"Ngrok Crashed" \
			"Ngrok process exited with code $exit_code, restarting in 5s" \
			"warning" \
			"service:ngrok"
	else
		dd_event \
			"Ngrok Stopped" \
			"Ngrok process stopped normally, restarting in 5s" \
			"info" \
			"service:ngrok"
	fi

	echo "Restarting in 5s..." | tee -a "$logfile"
	sleep 5
done

# Send shutdown event when ngrok-run is set to no
dd_event \
	"Ngrok Shutdown" \
	"Ngrok process has been stopped (ngrok-run = no)" \
	"warning" \
	"service:ngrok"

