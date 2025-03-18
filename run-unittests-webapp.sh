#!/bin/bash

# Script to run webapp unit tests

# Set up Python path
export PYTHONPATH=$(pwd):$PYTHONPATH

echo "Running webapp unit tests..."
python -m unittest test_webapp.py

# Check the exit code
if [ $? -eq 0 ]; then
    echo "✅ All webapp tests passed successfully!"
    exit 0
else
    echo "❌ Some tests failed. Please check the output above."
    exit 1
fi