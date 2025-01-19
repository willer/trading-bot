#!/bin/sh

# Get the API key directly
API_KEY=$(grep "^datadog-api-key" config.ini | sed 's/.*= *//')
APP_KEY=$(grep "^datadog-app-key" config.ini | sed 's/.*= *//')
SITE="us5.datadoghq.com"

# Calculate timestamps
end_time=$(date +%s)
start_time=$((end_time - 3600))  # 1 hour ago

echo "Using API Key: ${API_KEY:0:5}..."
echo "Using App Key: ${APP_KEY:0:5}..."
echo "Using site: $SITE"
echo

# First send a test event
echo "Sending test event..."
echo "URL: https://api.$SITE/api/v1/events"
response=$(curl -s -w "\nHTTP_STATUS: %{http_code}\n" \
    -X POST "https://api.$SITE/api/v1/events" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -H "DD-API-KEY: $API_KEY" \
    -H "DD-APPLICATION-KEY: $APP_KEY" \
    -d '{
        "title": "Check Datadog Test",
        "text": "Testing event submission from check-datadog.sh",
        "priority": "normal",
        "tags": ["test:check_script"]
    }' 2>&1)

echo "Event submission response:"
echo "$response"
echo

# Wait a few seconds for the event to be processed
sleep 5

echo "Checking events from the last hour..."
echo "Start time: $(date -d @$start_time)"
echo "End time: $(date -d @$end_time)"
echo

# Get events with full output
echo "Fetching events..."
echo "URL: https://api.$SITE/api/v1/events?start=$start_time&end=$end_time"
response=$(curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X GET \
    "https://api.$SITE/api/v1/events?start=$start_time&end=$end_time" \
    -H "Accept: application/json" \
    -H "DD-API-KEY: $API_KEY" \
    -H "DD-APPLICATION-KEY: $APP_KEY" 2>&1)

echo "Full response:"
echo "$response"
echo

http_status=$(echo "$response" | grep "HTTP_STATUS:" | cut -d' ' -f2)
echo "Response status: $http_status"
echo "$response" | grep -v "HTTP_STATUS:" | python -m json.tool || echo "No events found or invalid JSON response"

echo
echo "Checking metrics from the last hour..."
echo "Fetching metrics..."
echo "URL: https://api.$SITE/api/v1/query?from=$start_time&to=$end_time&query=system.cpu.idle"
response=$(curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X GET \
    "https://api.$SITE/api/v1/query?from=$start_time&to=$end_time&query=system.cpu.idle" \
    -H "Accept: application/json" \
    -H "DD-API-KEY: $API_KEY" \
    -H "DD-APPLICATION-KEY: $APP_KEY" 2>&1)

echo "Full response:"
echo "$response"
echo

http_status=$(echo "$response" | grep "HTTP_STATUS:" | cut -d' ' -f2)
echo "Response status: $http_status"
echo "$response" | grep -v "HTTP_STATUS:" | python -m json.tool || echo "No metrics found or invalid JSON response" 
