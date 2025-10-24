# PassivMOS Management Guide

Easy commands to manage your PassivMOS webapp.

## Quick Start

```bash
# Start the app
./start.sh

# Stop the app
./stop.sh

# Check status
./passivmos status

# View live logs
./passivmos logs
```

## The `./passivmos` Command

A powerful management script with everything you need.

### Basic Commands

```bash
# Service Management
./passivmos start           # Start PassivMOS
./passivmos stop            # Stop PassivMOS
./passivmos restart         # Restart PassivMOS
./passivmos status          # Show service status

# Monitoring
./passivmos logs            # View live logs (Ctrl+C to exit)
./passivmos logs-tail       # View last 50 log lines
./passivmos health          # Check application health

# Information
./passivmos info            # Show all service information
./passivmos url             # Show access URLs
```

### Advanced Commands

```bash
./passivmos reload-nginx    # Reload nginx configuration
./passivmos install         # Install/update systemd service
./passivmos uninstall       # Remove systemd service
```

## Common Tasks

### 1. Starting the App

**Option A: Simple start (recommended)**
```bash
./start.sh
```

**Option B: Using management script**
```bash
./passivmos start
```

### 2. Checking if App is Running

```bash
./passivmos status
```

Or check health:
```bash
./passivmos health
```

### 3. Viewing Logs

**Live logs (follows new entries):**
```bash
./passivmos logs
# Press Ctrl+C to exit
```

**Last 50 lines:**
```bash
./passivmos logs-tail
```

### 4. Stopping the App

```bash
./stop.sh
```

Or:
```bash
./passivmos stop
```

### 5. Restarting After Changes

If you modified code or configuration:
```bash
./passivmos restart
```

### 6. Getting All Information

```bash
./passivmos info
```

This shows:
- Service status and uptime
- Access URLs (local, public IP, domain)
- File locations
- Health status
- Cached tokens count

### 7. Finding Access URLs

```bash
./passivmos url
```

Shows all ways to access your app:
- Local URLs
- Public IP URL
- Domain URL (once approved)

## How It Works

### Production Mode (Default)

When the systemd service is installed:
- ✅ Runs automatically on server boot
- ✅ Auto-restarts if it crashes
- ✅ Runs in background (daemon)
- ✅ Managed by systemd

### Development Mode (Fallback)

If systemd service is not installed:
- Runs in foreground
- You must keep terminal open
- Manual restart needed after crash

## Service Management

### Install/Enable Service

```bash
./passivmos install
```

This creates a systemd service that:
- Starts automatically on boot
- Restarts on failure
- Runs in background

### Check Service Status

```bash
systemctl status passivmos
# or
./passivmos status
```

### View Service Logs

```bash
# Live logs
journalctl -u passivmos -f

# Last 100 lines
journalctl -u passivmos -n 100

# Or use the shortcut
./passivmos logs
```

### Disable Service (stop auto-start)

```bash
sudo systemctl disable passivmos
```

### Uninstall Service

```bash
./passivmos uninstall
```

## Nginx Management

### Reload Nginx (after config changes)

```bash
./passivmos reload-nginx
```

### Check Nginx Status

```bash
systemctl status nginx
```

### Test Nginx Configuration

```bash
nginx -t
```

## Monitoring

### Real-time Health Check

```bash
watch -n 5 './passivmos health'
```

Updates every 5 seconds. Press Ctrl+C to exit.

### Check Specific Endpoint

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/stats
```

### Monitor Resource Usage

```bash
# CPU and Memory
systemctl status passivmos

# Detailed stats
top -p $(pgrep -f "python.*main.py")
```

## Troubleshooting

### App Won't Start

1. Check logs:
```bash
./passivmos logs-tail
```

2. Check if port 8000 is in use:
```bash
sudo lsof -i :8000
```

3. Restart the service:
```bash
./passivmos restart
```

### Can't Access from Browser

1. Check if app is running:
```bash
./passivmos health
```

2. Check firewall:
```bash
sudo ufw status
```

3. Test nginx:
```bash
curl http://localhost/api/health
```

### Service Keeps Restarting

1. View recent failures:
```bash
./passivmos logs-tail
```

2. Check for errors:
```bash
journalctl -u passivmos --since "5 minutes ago"
```

### Port 8000 Already in Use

Find what's using it:
```bash
sudo lsof -i :8000
```

Kill the process:
```bash
sudo kill -9 <PID>
```

### Nginx Returns 502 Bad Gateway

1. Check if PassivMOS is running:
```bash
./passivmos status
```

2. Test backend directly:
```bash
curl http://localhost:8000/api/health
```

3. Restart both:
```bash
./passivmos restart
sudo systemctl restart nginx
```

## File Locations

```
passivmos_web/
├── passivmos              # Main management script ⭐
├── start.sh               # Quick start script
├── stop.sh                # Quick stop script
├── backend/
│   ├── main.py           # Main application
│   └── .env              # API keys (NOT in git)
├── venv/                 # Python virtual environment
├── sessions/             # User session data (NOT in git)
├── data/cache/           # Price/APR cache (NOT in git)
└── requirements.txt      # Python dependencies

System files:
├── /etc/systemd/system/passivmos.service   # Systemd service
└── /etc/nginx/sites-available/passivmos    # Nginx config
```

## Environment Variables

The app reads from `backend/.env`:

```bash
# Numia API Configuration
NUMIA_API_KEY=your_key_here

# Optional settings
USE_CACHE_FALLBACK=true
PRICE_UPDATE_INTERVAL=300
```

## Useful Commands Cheat Sheet

```bash
# Service
./passivmos start         # Start
./passivmos stop          # Stop
./passivmos restart       # Restart
./passivmos status        # Status

# Monitoring
./passivmos logs          # Live logs
./passivmos health        # Health check
./passivmos info          # All info

# URLs
./passivmos url           # Show URLs

# Advanced
./passivmos install       # Install service
./passivmos reload-nginx  # Reload nginx

# Old scripts (still work)
./start.sh                # Start
./stop.sh                 # Stop
```

## Auto-start on Boot

The systemd service is enabled by default, so PassivMOS:
- ✅ Starts automatically when server boots
- ✅ Restarts automatically if it crashes
- ✅ Runs in background (no terminal needed)

To disable auto-start:
```bash
sudo systemctl disable passivmos
```

To re-enable:
```bash
sudo systemctl enable passivmos
```

## Updates and Maintenance

### After Code Changes

```bash
git pull                  # Get latest code
./passivmos restart       # Restart with new code
```

### After Config Changes

```bash
# If you changed backend/.env or config.json
./passivmos restart

# If you changed nginx config
./passivmos reload-nginx
```

### Update Dependencies

```bash
source venv/bin/activate
pip install -r requirements.txt --upgrade
./passivmos restart
```

## Security Notes

- ✅ `.env` file is protected by `.gitignore`
- ✅ Sessions are not committed to git
- ✅ Cache data is not committed to git
- ✅ Firewall configured (ports 22, 80, 443)
- ✅ Service runs as root (needed for port 80)

## Getting Help

```bash
./passivmos help          # Show help
./passivmos               # Same as help
```

## Support

- GitHub: https://github.com/tonyler/passivmos_web
- Domain PR: https://github.com/open-domains/register/pull/2851
- Contact: @tonyler on Telegram
