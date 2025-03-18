#!/bin/bash

# Script to run all unit tests

# Set up Python path
export PYTHONPATH=$(pwd):$PYTHONPATH

echo "=== Running all unit tests ==="
echo ""

echo "🧪 Running webapp tests..."
./run-unittests-webapp.sh

# Store the exit code
WEBAPP_EXIT=$?

echo ""

echo "🧪 Running broker tests..."
./run-unittests-broker.sh

# Store the exit code
BROKER_EXIT=$?

echo ""
echo "=== Test run complete ==="

# Check if all tests passed
if [ $WEBAPP_EXIT -eq 0 ] && [ $BROKER_EXIT -eq 0 ]; then
    echo "✅ All tests passed successfully!"
    exit 0
else
    echo "❌ Some tests failed. See logs above for details."
    exit 1
fi