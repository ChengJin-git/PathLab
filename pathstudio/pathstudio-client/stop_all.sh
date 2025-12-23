#!/bin/bash
# PathStudio Client Cleanup Script
# Usage: ./stop_all.sh

echo "=== Stopping PathStudio Client ==="

# Kill Python Sidecar
# We look for the specific script path to avoid killing other python processes
pids=$(ps aux | grep "server/main.py" | grep -v grep | awk '{print $2}')

if [ -n "$pids" ]; then
    echo "Found stray Python Sidecar processes: $pids"
    kill -9 $pids 2>/dev/null || true
    echo "Killed."
else
    echo "No stray Python Sidecar processes found."
fi

echo "Cleanup complete."
