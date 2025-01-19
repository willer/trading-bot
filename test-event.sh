#!/bin/sh

# Source Datadog functions to get API key
. ./datadog-shell.sh

echo "Using Datadog API Key: ${DATADOG_API_KEY:0:5}..."
echo "Using Datadog site: $DATADOG_SITE"
echo

# Send a test event
echo "Sending test event to Datadog..."
echo "URL: https://api.$DATADOG_SITE/api/v1/events"
response=$(curl -s -w "\nHTTP_STATUS: %{http_code}\n" \
  -X POST "https://api.$DATADOG_SITE/api/v1/events" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "DD-API-KEY: $DATADOG_API_KEY" \
  -d @- << EOF 2>&1
{
  "title": "Test Event",
  "text": "This is a test event from the command line",
  "priority": "normal",
  "tags": ["test:true", "source:cli"]
}
EOF
)

echo "Full response:"
echo "$response"
echo

http_status=$(echo "$response" | grep "HTTP_STATUS:" | cut -d' ' -f2)
echo "Response status: $http_status" 
