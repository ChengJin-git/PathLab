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
    echo "No PID file found. Trying to find SmartResearch processes..."

    # Find processes that belong to this project by checking command line
    # Look for uvicorn processes running smartresearch modules
    pids=$(ps aux | grep -E "uvicorn smartresearch\.(services\.(gateway|backend\.(wsi|ai))\.main|main):app" | grep -v grep | awk '{print $2}' || true)

    if [ -n "$pids" ]; then
        for pid in $pids; do
            echo "Stopping SmartResearch process (PID: $pid)"
            kill "$pid" 2>/dev/null || true
        done
    fi

    # Find frontend process (npm/vite running in smartresearch/services/frontend)
    frontend_pids=$(ps aux | grep -E "vite.*smartresearch/services/frontend|npm.*dev.*smartresearch" | grep -v grep | awk '{print $2}' || true)

    if [ -n "$frontend_pids" ]; then
        for pid in $frontend_pids; do
            echo "Stopping SmartResearch frontend (PID: $pid)"
            kill "$pid" 2>/dev/null || true
        done
    fi

    if [ -z "$pids" ] && [ -z "$frontend_pids" ]; then
        echo "No SmartResearch processes found."
    else
        echo "Done."
    fi
fi

# Clean up log files (optional)
# rm -f /tmp/smartresearch_*.log

