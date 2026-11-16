# PassivMOS Webapp

Passive income calculator for Cosmos ecosystem wallets.

## Quick Start

**Start:**
```bash
./start.sh
```

**Stop:**
```bash
./stop.sh
```

**Manage (recommended):**
```bash
./passivmos start       # Start the app
./passivmos stop        # Stop the app
./passivmos status      # Check status
./passivmos logs        # View live logs
./passivmos health      # Health check
./passivmos info        # Show everything
./passivmos help        # See all commands
```

**Includes automatic background tasks:**
- 💰 Price collection (every 10 minutes)
- 📊 APR scraping from Keplr (every 10 minutes)

No separate scripts needed!


## Configuration

## Security and deployment

New accounts require a passphrase of at least 12 characters. After sign-in, the
app uses an HttpOnly session cookie; keep the app behind HTTPS in production and
set `SESSION_COOKIE_SECURE=true`. If the frontend is hosted on another origin,
set `CORS_ORIGINS` to its exact HTTPS origin (or a comma-separated allowlist).

Existing local sessions are migrated to password hashes on their next successful
sign-in. Existing short codes should be replaced with a new account/passphrase.

**Everything** is configured in `config.json`:

```json
{
  "tokens": {
    "ATOM": {
      "enabled": true,  // Set false to disable
      ...
    },
    "SAGA": {
      "skip_apr_scraping": true,  // Use hardcoded APR
      "fallback_apr": 3.0,
      ...
    }
  }
}
```

### Enable/Disable Tokens

Change `"enabled": false` in `config.json`, restart server.

### Skip APR Scraping for Specific Tokens

Set `"skip_apr_scraping": true` and provide `"fallback_apr"` to use hardcoded APR instead of scraping.

## Project Structure

```
passivmos_webapp/
├── config.json          # ALL configuration here
├── backend/
│   ├── main.py          # FastAPI server
│   ├── config_loader.py # Config manager
│   ├── wallet_analyzer.py
│   ├── price_scraper.py
│   ├── apr_scraper.py
│   └── numia_client.py
└── frontend/
    ├── index.html
    └── app.js
```

## Dependencies

- Python 3.12+
- FastAPI
- Playwright (for APR scraping)
- aiohttp

Install: `pip install -r requirements.txt`

## Features

- Wallet analysis (cosmos1..., osmo1..., etc)
- Real-time prices from Osmosis
- APR scraping from Keplr wallet
- Passive income calculations

## API Endpoints

- `GET /` - Frontend
- `POST /api/calculate` - Analyze addresses
- `GET /api/config` - Get enabled tokens
- `GET /api/stats` - Get prices/APRs

## Support

Contact @tonyler on Telegram
