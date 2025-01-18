#!/bin/sh

# Source Datadog functions
. ./datadog-shell.sh

# Send a test event using dd_event
dd_event \
    "Test DD Event Function" \
    "Testing the dd_event function from datadog-shell.sh" \
    "info" \
    "service:test" 