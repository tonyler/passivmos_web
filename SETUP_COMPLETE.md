# 🎉 PassivMOS Setup Complete!

Your PassivMOS webapp is now fully configured and running!

## ✅ What's Installed

### 1. Application
- ✅ PassivMOS webapp running on port 8000
- ✅ Python virtual environment with all dependencies
- ✅ Playwright/Chromium for APR scraping
- ✅ Background tasks (price/APR updates every 5 minutes)

### 2. System Services
- ✅ **systemd service** - Auto-starts on boot, auto-restarts on crash
- ✅ **nginx** - Reverse proxy on port 80
- ✅ **Firewall** - Ports 22, 80, 443 open

### 3. Domain Registration
- ✅ GitHub repository made public safely (API keys protected)
- ✅ Domain registration PR submitted
- ⏳ **Waiting for approval** (~24-48 hours)

## 🌐 Access Your App

### Right Now:
```
Local:      http://localhost:8000
            http://localhost

Public IP:  http://[2a01:4f9:c012:b061::1]
```

### Once Domain Approved:
```
Domain:     http://tonyler.is-not-a.dev
```

Track approval: https://github.com/open-domains/register/pull/2851

## 📋 Management Commands

### The `./passivmos` Script (Main Tool)

```bash
# Service Control
./passivmos start           # Start PassivMOS
./passivmos stop            # Stop PassivMOS
./passivmos restart         # Restart PassivMOS
./passivmos status          # Show status

# Monitoring
./passivmos logs            # Live logs (Ctrl+C to exit)
./passivmos logs-tail       # Last 50 lines
./passivmos health          # Health check
./passivmos info            # All information

# URLs
./passivmos url             # Show access URLs

# Help
./passivmos help            # Show all commands
```

### Legacy Scripts (Still Work)

```bash
./start.sh                  # Start the app
./stop.sh                   # Stop the app
```

## 🚀 Common Tasks

### Check if Running
```bash
./passivmos status
```

### View Live Logs
```bash
./passivmos logs
# Press Ctrl+C to exit
```

### Check Health
```bash
./passivmos health
```

### Get All Info
```bash
./passivmos info
```

### Restart After Changes
```bash
./passivmos restart
```

## 📊 What's Running in Background

Your app automatically:
1. **Fetches prices** from Numia API (Osmosis DEX) every 5 minutes
2. **Scrapes APRs** from Keplr wallet every 5 minutes
3. **Caches data** in `data/cache/`
4. **Stores sessions** in `sessions/`

All running seamlessly without manual intervention!

## 🔐 Security

✅ Protected:
- API keys (in `backend/.env`, excluded from git)
- User session data (excluded from git)
- Cache data (excluded from git)

✅ Firewall configured:
- Port 22 (SSH) - Open
- Port 80 (HTTP) - Open
- Port 443 (HTTPS) - Open

✅ Auto-restart on failure

## 📂 File Structure

```
passivmos_web/
├── passivmos              # ⭐ Main management script
├── start.sh               # Quick start
├── stop.sh                # Quick stop
├── MANAGEMENT.md          # Complete management guide
├── backend/
│   ├── main.py           # Application entry point
│   └── .env              # API keys (protected)
├── venv/                 # Virtual environment
├── sessions/             # User data (protected)
└── data/cache/           # Price/APR cache (protected)
```

## 📖 Documentation

- **[MANAGEMENT.md](MANAGEMENT.md)** - Complete management guide
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Deployment options
- **[QUICKSTART.md](QUICKSTART.md)** - Setup guide
- **[README.md](README.md)** - Project overview

## 🎯 Next Steps

### Now:
1. Test the app: `./passivmos health`
2. View logs: `./passivmos logs`
3. Access locally: http://localhost:8000

### In 24-48 Hours (Once Domain Approved):
1. Your domain will be active: http://tonyler.is-not-a.dev
2. Optionally add SSL (HTTPS):
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d tonyler.is-not-a.dev
   ```

## 🆘 Troubleshooting

### App won't start?
```bash
./passivmos logs-tail       # Check recent logs
./passivmos restart         # Try restart
```

### Can't access from browser?
```bash
./passivmos health          # Check if running
sudo ufw status             # Check firewall
curl http://localhost/api/health    # Test nginx
```

### Service keeps restarting?
```bash
./passivmos logs            # Watch live logs
journalctl -u passivmos -n 100      # Full logs
```

## 📱 Contact & Support

- **GitHub Repo**: https://github.com/tonyler/passivmos_web
- **Domain PR**: https://github.com/open-domains/register/pull/2851
- **Telegram**: @tonyler

## ⚡ Quick Reference

```bash
# Most Common Commands
./passivmos status          # Is it running?
./passivmos logs            # What's happening?
./passivmos health          # Is it healthy?
./passivmos restart         # Restart it
./passivmos info            # Tell me everything
```

---

## 🎊 You're All Set!

Your PassivMOS webapp is:
- ✅ Running 24/7
- ✅ Auto-starts on boot
- ✅ Auto-restarts on crash
- ✅ Publicly accessible
- ✅ Updating prices/APRs automatically

Just wait for domain approval and you'll have a beautiful domain name too! 🚀

---

*Generated on: 2025-10-24*
*Server IP: 2a01:4f9:c012:b061::1*
*Domain: tonyler.is-not-a.dev (pending)*
