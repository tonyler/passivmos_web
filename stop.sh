#!/bin/bash
# PassivMOS Webapp Stop Script

echo "🛑 Stopping PassivMOS Webapp..."

# Find and kill Python processes running main.py
PIDS=$(ps aux | grep "python.*main.py" | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo "❌ No running webapp found"
    exit 0
fi

# Kill each process
for PID in $PIDS; do
    echo "🔪 Killing process $PID..."
    kill $PID 2>/dev/null

    # Wait a moment and force kill if still running
    sleep 1
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚡ Force killing process $PID..."
        kill -9 $PID 2>/dev/null
    fi
done

echo "✅ Webapp stopped successfully"
