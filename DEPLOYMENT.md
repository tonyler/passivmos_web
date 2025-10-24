# Deploy PassivMOS Webapp Globally

This guide shows how to run PassivMOS locally and make it accessible globally using a free domain from [open-domains](https://github.com/open-domains/register).

## Prerequisites

1. Linux/Mac server or VPS with a public IP address
2. Node.js installed (for local tunnel) OR port forwarding setup
3. Python 3.12+ installed
4. Git installed

## Setup Steps

### 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers for APR scraping
playwright install chromium
playwright install-deps chromium
```

### 2. Configure the Application

The app is configured via `config.json`. You can enable/disable tokens and set APR fallbacks:

```json
{
  "tokens": {
    "ATOM": {
      "enabled": true,
      ...
    },
    "SAGA": {
      "skip_apr_scraping": true,
      "fallback_apr": 3.0,
      ...
    }
  }
}
```

### 3. Run the Application

**Option A: Using the start script (recommended)**
```bash
./start.sh
```

**Option B: Manual start**
```bash
cd backend
python main.py
```

The app will be available at `http://localhost:8000`

To stop:
```bash
./stop.sh
```

## Make It Globally Accessible

### Option 1: Using Cloudflare Tunnel (Free, Recommended)

1. Install cloudflared:
```bash
# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Mac
brew install cloudflare/cloudflare/cloudflared
```

2. Run the tunnel:
```bash
cloudflared tunnel --url http://localhost:8000
```

This will give you a free `*.trycloudflare.com` URL that's globally accessible.

### Option 2: Using ngrok (Free tier available)

1. Install ngrok:
```bash
# Download from https://ngrok.com/download
```

2. Run ngrok:
```bash
ngrok http 8000
```

This provides a public URL like `https://abc123.ngrok.io`

### Option 3: VPS with Direct Access + Free Domain

If you have a VPS with a public IP:

1. **Get your server's public IP**:
```bash
curl ifconfig.me
```

2. **Configure firewall to allow port 8000**:
```bash
# Ubuntu/Debian
sudo ufw allow 8000

# Or run on port 80 (requires sudo)
sudo PORT=80 python backend/main.py
```

3. **Get a free domain from open-domains**:

   a. Fork the repository: https://github.com/open-domains/register

   b. Create a file in `domains/` directory (e.g., `domains/passivmos.is-an.app.json`):
   ```json
   {
     "description": "PassivMOS Webapp - Cosmos Passive Income Calculator",
     "repo": "https://github.com/YOUR_USERNAME/passivmos_web",
     "owner": {
       "username": "YOUR_GITHUB_USERNAME",
       "email": "your@email.com"
     },
     "record": {
       "A": ["YOUR_SERVER_IP"]
     }
   }
   ```

   c. Create a pull request to the open-domains repository

   d. Wait for approval (usually 24-48 hours)

   e. Once approved, your app will be accessible at `http://passivmos.is-an.app:8000`

4. **Optional: Set up reverse proxy with nginx** (to use port 80):

```bash
# Install nginx
sudo apt install nginx

# Create config file
sudo nano /etc/nginx/sites-available/passivmos
```

Add this configuration:
```nginx
server {
    listen 80;
    server_name passivmos.is-an.app;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Enable and restart nginx:
```bash
sudo ln -s /etc/nginx/sites-available/passivmos /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Option 4: Run as a System Service

To keep the app running 24/7 on your server:

1. Create a systemd service file:
```bash
sudo nano /etc/systemd/system/passivmos.service
```

2. Add this content:
```ini
[Unit]
Description=PassivMOS Webapp
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/passivmos_web
ExecStart=/usr/bin/python3 /path/to/passivmos_web/backend/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable passivmos
sudo systemctl start passivmos

# Check status
sudo systemctl status passivmos

# View logs
sudo journalctl -u passivmos -f
```

## Available Free Domain Providers

Through open-domains, you can choose from many free domains:
- `*.is-an.app`
- `*.is-a.dev`
- `*.js.org`
- `*.runs.gg`
- `*.publicvm.com`
- And many more...

See the full list at: https://github.com/open-domains/register#available-domains

## Environment Variables

You can customize the port:
```bash
PORT=3000 python backend/main.py
```

## Monitoring

Check if the app is running:
```bash
curl http://localhost:8000/api/health
```

View logs:
```bash
# If using systemd
sudo journalctl -u passivmos -f

# If using start.sh script, check the process
ps aux | grep python
```

## Troubleshooting

### Port already in use
```bash
# Find what's using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 PID
```

### Background tasks not running
The app automatically runs background tasks every 5 minutes to update prices/APRs. Check logs to verify.

### Playwright issues
```bash
# Reinstall Playwright
playwright install chromium
playwright install-deps chromium
```

## Security Considerations

1. **Use HTTPS**: Consider adding SSL with Let's Encrypt if using a custom domain
2. **Firewall**: Only open necessary ports
3. **Rate Limiting**: Consider adding rate limiting for production use
4. **Updates**: Keep dependencies updated regularly

## Costs

- **Cloudflare Tunnel**: Free
- **ngrok**: Free tier available (limited features)
- **VPS**: Starting from $3-5/month (DigitalOcean, Linode, Vultr, etc.)
- **Domain**: Free via open-domains
- **SSL Certificate**: Free via Let's Encrypt

## Support

Contact @tonyler on Telegram for assistance.
