#!/bin/bash
# PassivMOS Webapp Startup Script

echo "🚀 Starting PassivMOS Webapp..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install requirements
echo "📥 Installing dependencies..."
pip install -r requirements.txt --quiet

# Install Playwright browsers (only if not already installed)
if [ ! -d "$HOME/.cache/ms-playwright" ]; then
    echo "🌐 Installing Playwright browsers..."
    playwright install chromium --quiet
fi

# Start the server
echo "🌐 Starting server on http://localhost:8000"
echo "📊 Background tasks: Price collection + APR scraping (every 5 min)"
echo "Press Ctrl+C to stop"
echo ""
cd backend
python main.py
