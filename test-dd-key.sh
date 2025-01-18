#!/bin/sh

# Get the API key directly
API_KEY=$(grep "^datadog-api-key" config.ini | sed 's/.*= *//')
APP_KEY=$(grep "^datadog-app-key" config.ini | sed 's/.*= *//')
SITE="us5.datadoghq.com"

echo "Testing API key: ${API_KEY:0:5}..."
echo "Testing App key: ${APP_KEY:0:5}..."
echo "Using site: $SITE"

# Send a simple test event
echo "Sending test event..."
curl -v -X POST "https://api.$SITE/api/v1/events" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -H "DD-API-KEY: $API_KEY" \
    -H "DD-APPLICATION-KEY: $APP_KEY" \
    -d '{
        "title": "API Key Test",
        "text": "Testing API key functionality",
        "priority": "normal",
        "tags": ["test:api_key"]
    }'

echo -e "\n\nTrying to read events..."
curl -v -X GET "https://api.$SITE/api/v1/events?start=$(date +%s -d '5 minutes ago')&end=$(date +%s)" \
    -H "Accept: application/json" \
    -H "DD-API-KEY: $API_KEY" \
    -H "DD-APPLICATION-KEY: $APP_KEY" 