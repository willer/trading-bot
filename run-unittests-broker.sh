#!/bin/bash

# Script to run broker unit tests

# Set up Python path
export PYTHONPATH=$(pwd):$PYTHONPATH

echo "Running broker unit tests..."
python -m unittest test_broker.py

# Check the exit code
if [ $? -eq 0 ]; then
    echo "✅ All broker tests passed successfully!"
    exit 0
else
    echo "❌ Some tests failed. Please check the output above."
    exit 1
fi