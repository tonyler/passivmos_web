# 🚀 Quick Start Guide - Get Your Free Domain!

This guide will help you set up PassivMOS with a free domain in just a few minutes.

## What You Get

- **Free Domain**: `tonyler.is-not-a.dev`
- **Server IP**: `2a01:4f9:c012:b061::1` (IPv6)
- **Public Access**: Your app accessible from anywhere!

## Prerequisites

1. **GitHub CLI** installed (we'll guide you)
2. **GitHub account** (username: tonyler)
3. **This server** running with public IP

---

## Step 1: Install GitHub CLI (if not installed)

### On Linux:
```bash
# Download and install
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null

sudo apt update && sudo apt install gh
```

### On Mac:
```bash
brew install gh
```

### Verify installation:
```bash
gh --version
```

---

## Step 2: Login to GitHub

```bash
gh auth login
```

Follow the prompts:
1. Choose: **GitHub.com**
2. Choose: **HTTPS**
3. Choose: **Login with a web browser**
4. Copy the code shown
5. Press Enter to open browser
6. Paste code and authorize

---

## Step 3: Setup GitHub Repository (Make It Public Safely)

This script will:
- Add `.gitignore` to protect your API keys
- Remove sensitive files from git history
- Create/update your GitHub repository
- Make it public (required for open-domains)

```bash
./setup_github.sh
```

**The script will ask**: "Make repository public?"
- Answer: **y** (yes)

---

## Step 4: Register Free Domain

This script will automatically:
- Fork the open-domains/register repository
- Create domain configuration for `tonyler.is-not-a.dev`
- Submit a pull request
- Give you a link to track approval

```bash
./setup_domain.sh
```

---

## Step 5: Wait for Approval ⏳

- **Time**: Usually 24-48 hours
- **Notifications**: Check your GitHub email/notifications
- **Track PR**: The script will give you a link

---

## Step 6: Start Your App

While waiting for domain approval, start your app:

```bash
./start.sh
```

App runs on: `http://localhost:8000`

---

## Step 7: Configure Public Access (After Domain Approval)

Once your domain is approved, set up nginx reverse proxy:

### Install nginx:
```bash
sudo apt update
sudo apt install nginx
```

### Create configuration:
```bash
sudo nano /etc/nginx/sites-available/passivmos
```

### Add this content:
```nginx
server {
    listen 80;
    listen [::]:80;
    server_name tonyler.is-not-a.dev;

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

### Enable and start:
```bash
sudo ln -s /etc/nginx/sites-available/passivmos /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Open firewall:
```bash
sudo ufw allow 80
sudo ufw allow 443
```

---

## Step 8: Run as System Service (Optional but Recommended)

Keep your app running 24/7:

### Create service file:
```bash
sudo nano /etc/systemd/system/passivmos.service
```

### Add this content (update paths):
```ini
[Unit]
Description=PassivMOS Webapp
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/flyfix
ExecStart=/usr/bin/python3 /root/flyfix/backend/main.py
Restart=always
RestartSec=10
Environment="PATH=/usr/bin:/usr/local/bin"

[Install]
WantedBy=multi-user.target
```

### Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable passivmos
sudo systemctl start passivmos

# Check status
sudo systemctl status passivmos

# View logs
sudo journalctl -u passivmos -f
```

---

## 🎉 Done!

Once domain is approved and nginx is configured, your app will be live at:
**http://tonyler.is-not-a.dev**

---

## Troubleshooting

### Check if app is running:
```bash
curl http://localhost:8000/api/health
```

### Check nginx:
```bash
sudo systemctl status nginx
sudo nginx -t
```

### Check domain resolution (after approval):
```bash
dig tonyler.is-not-a.dev
ping6 tonyler.is-not-a.dev
```

### View app logs:
```bash
# If using systemd
sudo journalctl -u passivmos -f

# If using start.sh
ps aux | grep python
```

---

## Commands Summary

```bash
# 1. Install GitHub CLI (if needed)
# See Step 1 above

# 2. Login to GitHub
gh auth login

# 3. Setup GitHub repo (make public safely)
./setup_github.sh

# 4. Register free domain
./setup_domain.sh

# 5. Start app
./start.sh

# 6. Stop app
./stop.sh

# 7. Check status
curl http://localhost:8000/api/health
```

---

## What's Protected?

Your `.gitignore` now protects:
- ✅ `.env` files with API keys
- ✅ `sessions/` with user wallet addresses
- ✅ `data/cache/` with token data
- ✅ Python cache files
- ✅ IDE settings

Safe to make public! 🔒

---

## Need Help?

Contact @tonyler on Telegram
