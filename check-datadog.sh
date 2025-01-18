#!/bin/sh

# Source Datadog functions to get API key
. ./datadog-shell.sh

# Get events from the last hour
echo "Checking events from the last hour..."
curl -s -X GET "https://api.datadoghq.com/api/v1/events?start=$(date -d '1 hour ago' +%s)&end=$(date +%s)" \
    -H "Accept: application/json" \
    -H "DD-API-KEY: $DATADOG_API_KEY" | \
    python -m json.tool | \
    grep -A 5 "title\|text\|tags" 