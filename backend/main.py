#!/usr/bin/env python3
"""
PassivMOS Webapp Backend
FastAPI server for portfolio tracking
"""
import asyncio
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
from pathlib import Path
import json
from datetime import datetime
import hashlib
import asyncio

# Import our modules
from wallet_analyzer import WalletAddressAnalyzer, WalletAnalysis
from price_scraper import PriceAPRScraper
from bech32_converter import Bech32Converter
from config_loader import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="PassivMOS Webapp",
    description="Portfolio tracking for Cosmos ecosystem wallets",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# Directories
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# Global scraper instance
price_scraper = PriceAPRScraper(cache_dir=str(Path(__file__).parent.parent / "data" / "cache"))

# === PYDANTIC MODELS ===

class UserSession(BaseModel):
    """User session model"""
    code: str
    addresses: List[str]
    created_at: str
    last_updated: str

class RegisterRequest(BaseModel):
    """User registration request"""
    code: str

class SaveAddressesRequest(BaseModel):
    """Save addresses request"""
    code: str
    addresses: List[str]

class CalculateRequest(BaseModel):
    """Calculate portfolio request"""
    code: str

class PortfolioResponse(BaseModel):
    """Portfolio calculation response"""
    code: str
    total_value_usd: float
    daily_earnings: float
    monthly_earnings: float
    yearly_earnings: float
    wallets: List[Dict]
    token_breakdown: Dict[str, Dict]
    last_updated: str

# === HELPER FUNCTIONS ===

def get_session_file(code: str) -> Path:
    """Get session file path for a user code"""
    # Hash the code for security
    code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
    return SESSIONS_DIR / f"{code_hash}.json"

def load_session(code: str) -> Optional[UserSession]:
    """Load user session from file"""
    session_file = get_session_file(code)
    if not session_file.exists():
        return None

    try:
        with open(session_file, 'r') as f:
            data = json.load(f)
        return UserSession(**data)
    except Exception as e:
        logger.error(f"Error loading session: {e}")
        return None

def save_session(session: UserSession):
    """Save user session to file"""
    session_file = get_session_file(session.code)
    try:
        with open(session_file, 'w') as f:
            json.dump(session.dict(), f, indent=2)
        logger.info(f"Session saved for code: {session.code}")
    except Exception as e:
        logger.error(f"Error saving session: {e}")
        raise HTTPException(status_code=500, detail="Failed to save session")

# === API ENDPOINTS ===

@app.get("/")
async def root():
    """Serve frontend"""
    return FileResponse(frontend_dir / "index.html")

@app.post("/api/register")
async def register(request: RegisterRequest):
    """Register or login with a user code"""
    if not request.code or len(request.code) < 3:
        raise HTTPException(status_code=400, detail="Code must be at least 3 characters")

    # Check if session exists
    existing_session = load_session(request.code)

    if existing_session:
        return {
            "message": "Welcome back!",
            "exists": True,
            "addresses": existing_session.addresses
        }
    else:
        # Create new session
        now = datetime.now().isoformat()
        new_session = UserSession(
            code=request.code,
            addresses=[],
            created_at=now,
            last_updated=now
        )
        save_session(new_session)

        return {
            "message": "Account created!",
            "exists": False,
            "addresses": []
        }

@app.post("/api/addresses/save")
async def save_addresses(request: SaveAddressesRequest):
    """Save wallet addresses for a user"""
    session = load_session(request.code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Please register first.")

    # Clean addresses (remove empty lines)
    cleaned_addresses = [addr.strip() for addr in request.addresses if addr.strip()]

    # Update session
    session.addresses = cleaned_addresses
    session.last_updated = datetime.now().isoformat()
    save_session(session)

    return {
        "message": "Addresses saved successfully",
        "count": len(cleaned_addresses)
    }

@app.get("/api/addresses/{code}")
async def get_addresses(code: str):
    """Get saved addresses for a user"""
    session = load_session(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "addresses": session.addresses,
        "last_updated": session.last_updated
    }

async def calculate_portfolio_generator(code: str):
    """Generator that yields progress updates during portfolio calculation"""

    def send_event(event_type: str, data: dict):
        """Send SSE event"""
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        # Load session
        session = load_session(code)
        if not session:
            yield send_event("error", {"message": "Session not found"})
            return

        if not session.addresses:
            yield send_event("error", {"message": "No addresses saved"})
            return

        yield send_event("progress", {"message": "💎 Loading token prices from Numia API cache...", "step": 1, "total": 10})

        # Get cached price/APR data from Numia
        cached_data = price_scraper.load_cache()
        if not cached_data:
            yield send_event("progress", {"message": "⚠️  Fetching fresh prices from Numia API...", "step": 2, "total": 10})
            cached_data = await price_scraper.scrape_all()
        else:
            yield send_event("progress", {"message": f"✅ Loaded prices for {len(cached_data)} tokens", "step": 2, "total": 10})

        # Analyze wallets
        yield send_event("progress", {"message": f"🔍 Analyzing {len(session.addresses)} wallet address(es)...", "step": 3, "total": 10})

        async with WalletAddressAnalyzer() as analyzer:
            wallet_analyses = []
            address_count = 0

            for address in session.addresses:
                address_count += 1
                try:
                    # Convert address to all chain variants using bech32
                    yield send_event("progress", {"message": f"🔄 Converting address {address_count}/{len(session.addresses)} to chain variants...", "step": 3 + address_count, "total": 10})

                    all_chain_addresses = Bech32Converter.get_all_chain_addresses(address)

                    if not all_chain_addresses:
                        yield send_event("warning", {"message": f"⚠️  Could not convert address: {address[:12]}..."})
                        continue

                    yield send_event("progress", {"message": f"✅ Checking {len(all_chain_addresses)} chains for address {address_count}...", "step": 4 + address_count, "total": 10})

                    # Check balance on each chain variant
                    for chain_name, chain_address in all_chain_addresses.items():
                        try:
                            # Get wallet balance
                            wallet_balance = await analyzer.get_wallet_balance(chain_address, chain_name)

                            # Skip if no balance found
                            if not wallet_balance or wallet_balance.total_balance == 0:
                                continue

                            # Found balance!
                            yield send_event("found", {"message": f"💰 Found {wallet_balance.total_balance:.2f} {wallet_balance.token_symbol} on {chain_name}", "chain": chain_name, "token": wallet_balance.token_symbol, "balance": wallet_balance.total_balance})

                            # Get token data
                            token_symbol = wallet_balance.token_symbol
                            token_data = cached_data.get(token_symbol)

                            if not token_data:
                                yield send_event("warning", {"message": f"⚠️  No price data for {token_symbol}"})
                                continue

                            # Check if APR is valid (not 0 or error status)
                            has_apr_issue = token_data.apr_status in ['error', 'fallback'] or token_data.apr == 0
                            apr_to_use = token_data.apr if not has_apr_issue else 0

                            # Calculate earnings (0 if APR failed)
                            total_value_usd = wallet_balance.total_balance * token_data.price
                            if apr_to_use > 0:
                                yearly_earnings = wallet_balance.delegated_balance * (apr_to_use / 100) * token_data.price
                                daily_earnings = yearly_earnings / 365
                                monthly_earnings = yearly_earnings / 12
                            else:
                                yearly_earnings = 0
                                daily_earnings = 0
                                monthly_earnings = 0

                            wallet_analyses.append({
                                'address': chain_address,
                                'original_address': address,
                                'chain': chain_name,
                                'token_symbol': token_symbol,
                                'available_balance': wallet_balance.available_balance,
                                'delegated_balance': wallet_balance.delegated_balance,
                                'total_balance': wallet_balance.total_balance,
                                'token_price': token_data.price,
                                'apr': apr_to_use,
                                'apr_status': token_data.apr_status,
                                'apr_source': token_data.apr_source,
                                'has_apr_issue': has_apr_issue,
                                'total_value_usd': total_value_usd,
                                'daily_earnings': daily_earnings,
                                'monthly_earnings': monthly_earnings,
                                'yearly_earnings': yearly_earnings
                            })

                        except Exception as e:
                            continue

                except Exception as e:
                    yield send_event("error", {"message": f"❌ Error analyzing address: {str(e)}"})
                    continue

        # Calculate totals
        yield send_event("progress", {"message": "📊 Calculating portfolio totals...", "step": 9, "total": 10})

        # Check for APR issues
        tokens_with_apr_issues = set()
        for wallet in wallet_analyses:
            if wallet.get('has_apr_issue'):
                tokens_with_apr_issues.add(wallet['token_symbol'])

        if tokens_with_apr_issues:
            issue_list = ", ".join(sorted(tokens_with_apr_issues))
            yield send_event("warning", {"message": f"⚠️  APR scraping failed for: {issue_list}. Earnings set to $0. Using fallback APRs where available."})

        total_portfolio_value = sum(w['total_value_usd'] for w in wallet_analyses)
        total_daily = sum(w['daily_earnings'] for w in wallet_analyses)
        total_monthly = sum(w['monthly_earnings'] for w in wallet_analyses)
        total_yearly = sum(w['yearly_earnings'] for w in wallet_analyses)

        # Group by token
        token_breakdown = {}
        for wallet in wallet_analyses:
            token = wallet['token_symbol']
            if token not in token_breakdown:
                token_breakdown[token] = {
                    'total_balance': 0.0,
                    'total_value_usd': 0.0,
                    'daily_earnings': 0.0,
                    'monthly_earnings': 0.0,
                    'yearly_earnings': 0.0,
                    'price': wallet['token_price'],
                    'apr': wallet['apr']
                }

            token_breakdown[token]['total_balance'] += wallet['total_balance']
            token_breakdown[token]['total_value_usd'] += wallet['total_value_usd']
            token_breakdown[token]['daily_earnings'] += wallet['daily_earnings']
            token_breakdown[token]['monthly_earnings'] += wallet['monthly_earnings']
            token_breakdown[token]['yearly_earnings'] += wallet['yearly_earnings']

        # Send completion with results
        yield send_event("progress", {"message": f"✅ Analysis complete! Found ${total_portfolio_value:.2f} across {len(wallet_analyses)} wallet(s)", "step": 10, "total": 10})

        result = {
            "code": code,
            "total_value_usd": total_portfolio_value,
            "daily_earnings": total_daily,
            "monthly_earnings": total_monthly,
            "yearly_earnings": total_yearly,
            "wallets": wallet_analyses,
            "token_breakdown": token_breakdown,
            "last_updated": datetime.now().isoformat()
        }

        yield send_event("complete", result)

    except Exception as e:
        logger.error(f"Error in portfolio calculation: {e}")
        yield send_event("error", {"message": f"❌ Error: {str(e)}"})


@app.get("/api/calculate/stream/{code}")
async def calculate_portfolio_stream(code: str):
    """Stream portfolio calculation progress via Server-Sent Events"""
    return StreamingResponse(
        calculate_portfolio_generator(code),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/calculate")
async def calculate_portfolio(request: CalculateRequest):
    """Calculate portfolio for a user's addresses (non-streaming version for compatibility)"""
    logger.info(f"Calculating portfolio for code: {request.code}")

    # Load session
    session = load_session(request.code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.addresses:
        raise HTTPException(status_code=400, detail="No addresses saved")

    # Get cached price/APR data from Numia
    logger.info("💎 Loading token prices from Numia API cache...")
    cached_data = price_scraper.load_cache()
    if not cached_data:
        logger.warning("⚠️  No cached data available, fetching from Numia API now...")
        cached_data = await price_scraper.scrape_all()
        logger.info(f"✅ Fetched fresh data for {len(cached_data)} tokens from Numia API")
    else:
        logger.info(f"✅ Using cached Numia prices for {len(cached_data)} tokens")

    # Analyze wallets (simplified without progress updates)
    async with WalletAddressAnalyzer() as analyzer:
        wallet_analyses = []

        for address in session.addresses:
            try:
                all_chain_addresses = Bech32Converter.get_all_chain_addresses(address)
                if not all_chain_addresses:
                    continue

                for chain_name, chain_address in all_chain_addresses.items():
                    try:
                        wallet_balance = await analyzer.get_wallet_balance(chain_address, chain_name)
                        if not wallet_balance or wallet_balance.total_balance == 0:
                            continue

                        token_symbol = wallet_balance.token_symbol
                        token_data = cached_data.get(token_symbol)
                        if not token_data:
                            continue

                        total_value_usd = wallet_balance.total_balance * token_data.price
                        yearly_earnings = wallet_balance.delegated_balance * (token_data.apr / 100) * token_data.price
                        daily_earnings = yearly_earnings / 365
                        monthly_earnings = yearly_earnings / 12

                        wallet_analyses.append({
                            'address': chain_address,
                            'original_address': address,
                            'chain': chain_name,
                            'token_symbol': token_symbol,
                            'available_balance': wallet_balance.available_balance,
                            'delegated_balance': wallet_balance.delegated_balance,
                            'total_balance': wallet_balance.total_balance,
                            'token_price': token_data.price,
                            'apr': token_data.apr,
                            'total_value_usd': total_value_usd,
                            'daily_earnings': daily_earnings,
                            'monthly_earnings': monthly_earnings,
                            'yearly_earnings': yearly_earnings
                        })
                    except Exception:
                        continue
            except Exception:
                continue

    # Aggregate totals
    total_portfolio_value = sum(w['total_value_usd'] for w in wallet_analyses)
    total_daily = sum(w['daily_earnings'] for w in wallet_analyses)
    total_monthly = sum(w['monthly_earnings'] for w in wallet_analyses)
    total_yearly = sum(w['yearly_earnings'] for w in wallet_analyses)

    # Group by token
    token_breakdown = {}
    for wallet in wallet_analyses:
        token = wallet['token_symbol']
        if token not in token_breakdown:
            token_breakdown[token] = {
                'total_balance': 0.0,
                'total_value_usd': 0.0,
                'daily_earnings': 0.0,
                'monthly_earnings': 0.0,
                'yearly_earnings': 0.0,
                'price': wallet['token_price'],
                'apr': wallet['apr']
            }

        token_breakdown[token]['total_balance'] += wallet['total_balance']
        token_breakdown[token]['total_value_usd'] += wallet['total_value_usd']
        token_breakdown[token]['daily_earnings'] += wallet['daily_earnings']
        token_breakdown[token]['monthly_earnings'] += wallet['monthly_earnings']
        token_breakdown[token]['yearly_earnings'] += wallet['yearly_earnings']

    return PortfolioResponse(
        code=request.code,
        total_value_usd=total_portfolio_value,
        daily_earnings=total_daily,
        monthly_earnings=total_monthly,
        yearly_earnings=total_yearly,
        wallets=wallet_analyses,
        token_breakdown=token_breakdown,
        last_updated=datetime.now().isoformat()
    )

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    cache = price_scraper.load_cache()
    return {
        "status": "healthy",
        "price_source": "Numia API (Osmosis DEX)",
        "cached_tokens": len(cache) if cache else 0,
        "cache_available": cache is not None
    }

@app.get("/api/config")
async def get_config():
    """Get frontend configuration (enabled tokens only)"""
    enabled_tokens = config.get_all_tokens(enabled_only=True)

    return {
        "tokens": {
            symbol: {
                "name": token_config.get("name"),
                "symbol": token_config.get("symbol"),
                "color": token_config.get("color"),
                "logo": token_config.get("logo"),
                "enabled": token_config.get("enabled")
            }
            for symbol, token_config in enabled_tokens.items()
        }
    }

@app.get("/api/stats")
async def get_stats():
    """Get current token prices and APRs for display"""
    cached_data = price_scraper.load_cache()

    if not cached_data:
        return {
            "available": False,
            "message": "No price data available. Please contact @tonyler on Telegram.",
            "tokens": []
        }

    # Only return enabled tokens
    enabled_symbols = config.get_enabled_tokens()

    tokens = []
    for symbol, data in cached_data.items():
        if symbol in enabled_symbols:
            tokens.append({
                "symbol": symbol,
                "price": data.price,
                "apr": data.apr,
                "apr_status": data.apr_status,
                "apr_source": data.apr_source,
                "has_apr_issue": data.apr_status in ['error', 'fallback'],
                "last_updated": data.last_updated.isoformat() if hasattr(data.last_updated, 'isoformat') else str(data.last_updated)
            })

    # Sort by symbol
    tokens.sort(key=lambda x: x['symbol'])

    return {
        "available": True,
        "message": "Data from Numia API (Osmosis DEX)",
        "tokens": tokens,
        "last_check": datetime.now().isoformat()
    }

# === BACKGROUND TASKS ===

async def background_price_collector():
    """Background task to collect prices and APRs every 5 minutes"""
    while True:
        try:
            logger.info("🔄 Running background price/APR collection...")
            await price_scraper.scrape_all()
            logger.info("✅ Background collection complete")
        except Exception as e:
            logger.error(f"❌ Background collection error: {e}")

        # Wait 5 minutes
        await asyncio.sleep(300)

# === STARTUP/SHUTDOWN ===

@app.on_event("startup")
async def startup_event():
    """Run on startup"""
    logger.info("🚀 Starting PassivMOS Webapp...")
    logger.info("💎 Using Numia API for price data (Osmosis DEX)")
    logger.info("🕷️  APR scraping from Keplr wallet")

    # Initial data fetch
    try:
        logger.info("📊 Fetching initial price/APR data...")
        await price_scraper.scrape_all()
        logger.info("✅ Initial data loaded")
    except Exception as e:
        logger.error(f"⚠️ Initial fetch failed, will retry: {e}")
        # Try to load from cache
        try:
            cached = price_scraper.load_cache()
            if cached:
                logger.info(f"📂 Loaded cached data for {len(cached)} tokens")
        except Exception:
            pass

    # Start background collection task
    logger.info("⏰ Starting background collector (every 5 minutes)")
    asyncio.create_task(background_price_collector())

    logger.info("✅ Webapp ready at http://localhost:8000")

@app.on_event("shutdown")
async def shutdown_event():
    """Run on shutdown"""
    logger.info("👋 Shutting down PassivMOS Webapp...")

if __name__ == "__main__":
    import uvicorn
    import os
    # Use PORT from environment or default to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
