#!/bin/bash
# PassivMOS Webapp Startup Script
# Now uses systemd service for production deployment

echo "🚀 Starting PassivMOS Webapp..."

# Check if systemd service exists
if systemctl list-unit-files | grep -q "passivmos.service"; then
    echo "📋 Using systemd service (production mode)"
    sudo systemctl start passivmos

    # Wait for service to start
    sleep 2

    if sudo systemctl is-active --quiet passivmos; then
        echo "✅ PassivMOS started successfully!"
        echo ""
        echo "🌐 Access URLs:"
        echo "   Local:  http://localhost:8000"
        PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null)
        if [[ -n "$PUBLIC_IP" ]]; then
            if [[ $PUBLIC_IP =~ : ]]; then
                echo "   Public: http://[$PUBLIC_IP]"
                echo "   IP:     $PUBLIC_IP"
            else
                echo "   Public: http://$PUBLIC_IP"
                echo "   IP:     $PUBLIC_IP"
            fi
        else
            echo "   Public: (unable to detect IP)"
        fi
        echo "   Domain: http://tonyler.is-not-a.dev (once approved)"
        echo ""
        echo "📊 Monitoring:"
        echo "   Status: ./passivmos status"
        echo "   Logs:   ./passivmos logs"
        echo "   Health: ./passivmos health"
        echo ""
        echo "🛑 Stop with: ./stop.sh or ./passivmos stop"
    else
        echo "❌ Failed to start PassivMOS"
        echo "Check logs with: ./passivmos logs"
        exit 1
    fi
else
    echo "⚠️  Systemd service not found, using development mode"
    echo ""

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
    echo "📊 Background tasks: Price collection + APR scraping (every 10 min)"
    echo "Press Ctrl+C to stop"
    echo ""
    cd backend
    python main.py
fi
