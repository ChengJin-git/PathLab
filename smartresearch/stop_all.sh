#!/usr/bin/env bash
# SmartResearch - Stop all services
# Usage: bash smartresearch/stop_all.sh

set -e

echo "=== Stopping SmartResearch services ==="

if [ -f /tmp/smartresearch_pids.txt ]; then
    source /tmp/smartresearch_pids.txt
    
    for pid in $GATEWAY_PID $WSI_PID $AI_PID $FRONTEND_PID; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "Stopping PID $pid"
            kill "$pid" 2>/dev/null || true
        fi
    done
    
    rm -f /tmp/smartresearch_pids.txt
    echo "All services stopped."
else
    echo "No PID file found. Trying to find processes by port..."
    
    # Kill by port
    for port in 6100 6101 6102 5173; do
        pid=$(lsof -ti:$port 2>/dev/null || true)
        if [ -n "$pid" ]; then
            echo "Stopping process on port $port (PID: $pid)"
            kill "$pid" 2>/dev/null || true
        fi
    done
    
    echo "Done."
fi

# Clean up log files (optional)
# rm -f /tmp/smartresearch_*.log

