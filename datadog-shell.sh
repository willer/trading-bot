#!/bin/sh

# Load Datadog API keys from config.ini
# Parse the [DEFAULT] section of config.ini to get the API keys
DATADOG_API_KEY=$(grep "^datadog-api-key" config.ini | sed 's/.*= *//')
DATADOG_APP_KEY=$(grep "^datadog-app-key" config.ini | sed 's/.*= *//')

if [ -z "$DATADOG_API_KEY" ]; then
    echo "Error: datadog-api-key not found in config.ini"
    exit 1
fi

echo "Using Datadog API Key: ${DATADOG_API_KEY:0:5}..."

# Function to send event to Datadog
dd_event() {
    title="$1"
    text="$2"
    alert_type="${3:-info}"  # Default to info if not specified
    tags="${4:-service:shell}"  # Default tags if not specified

    echo "Sending event to Datadog: $title"
    
    # Use curl to send event to Datadog API (show response for debugging)
    response=$(curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X POST "https://api.datadoghq.com/api/v1/events" \
        -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "DD-API-KEY: $DATADOG_API_KEY" \
        -d @- << EOF
{
    "title": "$title",
    "text": "$text",
    "alert_type": "$alert_type",
    "tags": ["$tags"]
}
EOF
    )
    
    http_status=$(echo "$response" | grep "HTTP_STATUS:" | cut -d' ' -f2)
    if [ "$http_status" != "202" ]; then
        echo "Failed to send event to Datadog. Response:"
        echo "$response"
    fi
}

# Function to send metric to Datadog
dd_metric() {
    metric="$1"
    value="$2"
    tags="${3:-service:shell}"  # Default tags if not specified

    # Use curl to send metric to Datadog API (silent unless error)
    curl -s -f -X POST "https://api.datadoghq.com/api/v1/series" \
        -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "DD-API-KEY: $DATADOG_API_KEY" \
        -d @- << EOF >/dev/null || echo "Failed to send metric to Datadog"
{
    "series": [{
        "metric": "$metric",
        "points": [[$(date +%s), $value]],
        "tags": ["$tags"]
    }]
}
EOF
}

# Function to wrap a command with Datadog monitoring
dd_monitor_cmd() {
    service="$1"
    shift
    # Store command in an array to preserve spaces
    cmd=("$@")
    
    start_time=$(date +%s)
    
    # Run the command using eval to handle spaces in paths
    eval "${cmd[@]}" 2>&1
    exit_status=$?
    
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    
    # Send metrics silently
    dd_metric "shell.command.duration" "$duration" "service:$service"
    dd_metric "shell.command.status" "$exit_status" "service:$service"
    
    # If command failed, send an event
    if [ $exit_status -ne 0 ]; then
        dd_event \
            "Command Failed: $service" \
            "Exit Status: $exit_status\nDuration: ${duration}s" \
            "error" \
            "service:$service"
    fi
    
    return $exit_status
} 