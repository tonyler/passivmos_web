# Deploy PassivMOS to Fly.io

## Prerequisites

1. Create a Fly.io account: https://fly.io/app/sign-up
2. Install the Fly CLI: https://fly.io/docs/hands-on/install-flyctl/

```bash
# On Linux/Mac:
curl -L https://fly.io/install.sh | sh

# On Windows (PowerShell):
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

3. Login to Fly.io:
```bash
flyctl auth login
```

## Deployment Steps

### 1. Push your code to GitHub

```bash
# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit for Fly.io deployment"

# Add your GitHub remote
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Push to GitHub
git push -u origin main
```

### 2. Deploy to Fly.io

From your project root directory:

```bash
# Launch the app (first time only)
flyctl launch

# When prompted:
# - Choose app name (or press Enter for auto-generated)
# - Choose region (pick closest to you)
# - Do NOT set up PostgreSQL (we use JSON files)
# - Do NOT deploy now (we need to create volume first)
```

### 3. Create persistent volume for sessions

```bash
# Create a volume for storing user sessions
flyctl volumes create passivmos_data --size 1

# The volume is already configured in fly.toml
```

### 4. Deploy the app

```bash
flyctl deploy
```

### 5. Check if it's running

```bash
# Open in browser
flyctl open

# View logs
flyctl logs

# Check status
flyctl status
```

## Important Notes

### Persistent Storage
- User sessions are stored in `/app/sessions` which is mounted to a persistent volume
- Data survives restarts and redeployments

### Background Scraping
- The app runs background tasks every 5 minutes to update prices/APRs
- This works on Fly.io (unlike serverless platforms)

### Free Tier Limits
- 3 shared-cpu VMs
- 3GB persistent storage (we use 1GB)
- 160GB outbound transfer/month
- This should be plenty for personal use

### Scaling
If you need more resources later:
```bash
flyctl scale memory 512  # Reduce to 512MB if 1GB is too much
flyctl scale vm shared-cpu-1x  # Smallest VM size
```

## Updating Your App

After making changes to your code:

```bash
# Commit changes
git add .
git commit -m "Your changes"
git push

# Deploy to Fly.io
flyctl deploy
```

## Troubleshooting

### Check logs
```bash
flyctl logs
```

### SSH into the machine
```bash
flyctl ssh console
```

### Restart the app
```bash
flyctl restart
```

### Check volume
```bash
flyctl volumes list
```

## Environment Variables

If you need to add API keys or secrets:

```bash
flyctl secrets set NUMIA_API_KEY=your_key_here
```

## Useful Commands

```bash
flyctl status          # App status
flyctl info            # App info
flyctl open            # Open in browser
flyctl logs            # View logs
flyctl ssh console     # SSH into machine
flyctl destroy         # Delete app (careful!)
```

## Costs

Fly.io free tier should cover this app, but monitor your usage at:
https://fly.io/dashboard
