#!/usr/bin/env python3
"""
PassivMOS Webapp Backend
FastAPI server for portfolio tracking
"""
import asyncio
import logging
import re
import time as _time
import os
import secrets
import hashlib
import math
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, validator, Field
from typing import List, Optional, Dict
from pathlib import Path
import json
from datetime import datetime
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ── Logging (must be first) ───────────────────────────────────────────────────
from logger import setup_logging, EMOJI
logger = setup_logging()

# Import our modules
from wallet_analyzer import WalletAddressAnalyzer, WalletAnalysis
from price_scraper import PriceAPRScraper
from bech32_converter import Bech32Converter
from config_loader import config
from coinfolio_scanner import (
    price_refresh_loop, portfolio_cycle_loop,
    scan_user, load_prices, load_portfolio, load_history,
    persist_portfolio, code_to_hash, load_prices_updated_ts,
    load_aprs, calculate_yearly_income, scan_cardano,
)
from evm_analyzer import analyze_evm_address, get_evm_prices, get_evm_aprs

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/hour"],  # Global default
    storage_uri="memory://"
)

# Initialize FastAPI
app = FastAPI(
    title="PassivMOS Webapp",
    description="Portfolio tracking for Cosmos ecosystem wallets",
    version="1.0.0"
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    # This application uses an HttpOnly session cookie.  Credentialed CORS must
    # be explicit; wildcard origins would let another site act as a user.
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_credentials=bool(os.getenv("CORS_ORIGINS")),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── HTTP request logger ───────────────────────────────────────────────────────
_SKIP_PATHS = {"/api/health", "/api/coinfolio/prices"}
_METHOD_EMOJI = {"GET": EMOJI["get"], "POST": EMOJI["post"], "DELETE": EMOJI["delete"]}

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = _time.monotonic()
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Request body is too large")
    response = await call_next(request)
    if request.url.path in _SKIP_PATHS:
        return response
    ms = (_time.monotonic() - start) * 1000
    m_emoji = _METHOD_EMOJI.get(request.method, "🔄")
    s_emoji = EMOJI["ok"] if response.status_code < 400 else EMOJI["fail"]
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    path = request.url.path
    # Account credentials must never land in access logs through legacy routes.
    for prefix in ("/api/calculate/stream/", "/api/addresses/", "/api/purchases/"):
        if path.startswith(prefix):
            path = prefix + "[redacted]"
            break
    logger.info(f"{m_emoji} {request.method} {path} {s_emoji} {response.status_code} · {ms:.0f}ms · {ip}")
    return response

# Mount frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# Directories
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# Global scraper instance
price_scraper = PriceAPRScraper(cache_dir=str(Path(__file__).parent.parent / "data" / "cache"))

# Constants
MAX_ADDRESSES_PER_USER = 50
MAX_HOLDINGS_PER_SNAPSHOT = 500
MAX_REQUEST_BYTES = 1_000_000
SESSION_COOKIE = "passivmos_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
VALID_ADDRESS_PREFIXES = ['cosmos', 'osmo', 'celestia', 'juno', 'chihuahua', 'dym', 'saga', 'nolus', 'addr1', 'stake1']

# Tokens deliberately live only in memory: a server restart invalidates them.
_auth_sessions: Dict[str, tuple[str, float]] = {}

# Input Validation Helpers
def validate_user_code(code: str) -> bool:
    """Validate user code format"""
    # Existing accounts may still use a legacy short code while they sign in to
    # migrate. New accounts are required to use a real passphrase below.
    if not code or len(code) < 3 or len(code) > 100:
        return False
    # Allow any printable characters (passwords can contain spaces, symbols, etc.)
    if not code.isprintable():
        return False
    # Codes are still accepted by a few legacy path-based endpoints; a slash
    # cannot be represented reliably by all ASGI proxies, even when encoded.
    if "/" in code:
        return False
    return True

def validate_wallet_address(address: str) -> bool:
    """Validate wallet address format (EVM, Cosmos bech32, or Cardano bech32)."""
    if not address:
        return False
    # EVM
    if address.startswith("0x"):
        return bool(re.match(r'^0x[0-9a-fA-F]{40}$', address))
    # Bech32 (Cosmos + Cardano) — Cardano payment addresses can be ~103 chars
    if len(address) < 39 or len(address) > 110:
        return False
    if not re.match(r'^[a-z0-9]+$', address):
        return False
    return any(address.startswith(prefix) for prefix in VALID_ADDRESS_PREFIXES)

def sanitize_addresses(addresses: List[str]) -> tuple[List[str], List[str]]:
    """
    Sanitize and validate addresses
    Returns: (valid_addresses, invalid_addresses)
    """
    valid = []
    invalid = []

    for addr in addresses:
        cleaned = addr.strip()
        if not cleaned:
            continue

        if validate_wallet_address(cleaned):
            valid.append(cleaned)
        else:
            invalid.append(cleaned)

    return valid, invalid

class UserSession(BaseModel):
    """User session model"""
    addresses: List[str]
    created_at: str
    last_updated: str
    password_hash: Optional[str] = None

class RegisterRequest(BaseModel):
    """User registration request"""
    code: str

    @validator('code')
    def validate_code(cls, v):
        if not validate_user_code(v):
            raise ValueError('Invalid code format.')
        return v

class SaveAddressesRequest(BaseModel):
    """Save addresses request"""
    code: str
    addresses: List[str]

    @validator('code')
    def validate_code(cls, v):
        if not validate_user_code(v):
            raise ValueError('Invalid code format.')
        return v

    @validator('addresses')
    def validate_addresses_count(cls, v):
        if len(v) > MAX_ADDRESSES_PER_USER:
            raise ValueError(f'Maximum {MAX_ADDRESSES_PER_USER} addresses allowed.')
        return v

class CalculateRequest(BaseModel):
    """Calculate portfolio request"""
    code: str

    @validator('code')
    def validate_code(cls, v):
        if not validate_user_code(v):
            raise ValueError('Invalid code format.')
        return v

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

def get_session_file(code: str) -> Path:
    """Get session file path for a user code"""
    code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
    return SESSIONS_DIR / f"{code_hash}.json"

def _password_hash(code: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(code.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"

def _verify_password(code: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$", 2)
        actual = _password_hash(code, bytes.fromhex(salt_hex)).split("$", 2)[2]
        return secrets.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False

def load_session(code: str) -> Optional[UserSession]:
    """Load user session from file"""
    session_file = get_session_file(code)
    if not session_file.exists():
        return None

    try:
        with open(session_file, 'r') as f:
            data = json.load(f)
        # Migrate old local files after their code has been verified.  New files
        # never retain the plaintext credential.
        stored_hash = data.get("password_hash")
        if stored_hash:
            if not _verify_password(code, stored_hash):
                return None
        elif not secrets.compare_digest(str(data.get("code", "")), code):
            return None
        session = UserSession(**data)
        if not stored_hash:
            session.password_hash = _password_hash(code)
            save_session(session, code)
        return session
    except Exception as e:
        logger.error(f"Error loading session: {e}")
        return None

def save_session(session: UserSession, code: str):
    """Save user session to file (atomic write)"""
    session_file = get_session_file(code)
    temp_file = session_file.with_name(f".{session_file.name}.{secrets.token_hex(8)}.tmp")
    try:
        with open(temp_file, 'w') as f:
            json.dump(session.dict(), f, indent=2)
        temp_file.rename(session_file)
        os.chmod(session_file, 0o600)
        logger.info("Session saved")
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink()
        logger.error(f"Error saving session: {e}")
        raise HTTPException(status_code=500, detail="Failed to save session")

def _create_auth_session(code: str) -> str:
    token = secrets.token_urlsafe(32)
    _auth_sessions[token] = (hashlib.sha256(code.encode()).hexdigest()[:16], _time.time() + SESSION_TTL_SECONDS)
    return token

def _set_auth_cookie(response: Response, token: str):
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS,
                        httponly=True, secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
                        samesite="lax", path="/")

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _auth_sessions.pop(token, None)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}

def require_session(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    record = _auth_sessions.get(token or "")
    if not record or record[1] <= _time.time():
        if token:
            _auth_sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="Please sign in again")
    return record[0]

def require_owner(code: str, owner_hash: str):
    if not secrets.compare_digest(hashlib.sha256(code.encode()).hexdigest()[:16], owner_hash):
        raise HTTPException(status_code=403, detail="Not authorized for this account")

@app.get("/")
async def root():
    """Serve frontend"""
    return FileResponse(frontend_dir / "index.html")

@app.post("/api/register")
@limiter.limit("10/minute")
async def register(req: RegisterRequest, request: Request, response: Response):
    """Register or login with a user code"""
    request_data = req  # Rename for clarity

    # Check if session exists — scrypt is CPU-bound; run in thread to avoid blocking the event loop
    existing_session = await asyncio.to_thread(load_session, request_data.code)

    if existing_session:
        token = _create_auth_session(request_data.code)
        _set_auth_cookie(response, token)
        return {
            "message": "Welcome back!",
            "exists": True,
            "addresses": existing_session.addresses
        }
    else:
        if len(request_data.code) < 12:
            raise HTTPException(status_code=400, detail="New passphrases must be at least 12 characters")
        # Create new session
        now = datetime.now().isoformat()
        pw_hash = await asyncio.to_thread(_password_hash, request_data.code)
        new_session = UserSession(
            addresses=[],
            created_at=now,
            last_updated=now,
            password_hash=pw_hash,
        )
        save_session(new_session, request_data.code)
        _set_auth_cookie(response, _create_auth_session(request_data.code))

        return {
            "message": "Account created!",
            "exists": False,
            "addresses": []
        }

@app.post("/api/addresses/save")
@limiter.limit("15/minute")
async def save_addresses(req: SaveAddressesRequest, request: Request, owner_hash: str = Depends(require_session)):
    """Save wallet addresses for a user"""
    request_data = req
    require_owner(request_data.code, owner_hash)
    session = await asyncio.to_thread(load_session, request_data.code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Please register first.")

    # Validate and sanitize addresses
    valid_addresses, invalid_addresses = sanitize_addresses(request_data.addresses)

    # Update session with only valid addresses
    session.addresses = valid_addresses
    session.last_updated = datetime.now().isoformat()
    save_session(session, request_data.code)

    response = {
        "message": "Addresses saved successfully",
        "count": len(valid_addresses)
    }

    # Add warning if some addresses were invalid
    if invalid_addresses:
        response["warning"] = f"{len(invalid_addresses)} invalid address(es) skipped"
        response["invalid_addresses"] = invalid_addresses[:5]  # Show first 5

    return response

@app.get("/api/addresses/{code}")
async def get_addresses(code: str, owner_hash: str = Depends(require_session)):
    """Get saved addresses for a user"""
    require_owner(code, owner_hash)
    session = await asyncio.to_thread(load_session, code)
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
        session = await asyncio.to_thread(load_session, code)
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

        # Build symbol→price fallback from CoinGecko cache (covers tokens Numia doesn't price, e.g. NLS)
        _cg_prices = load_prices()
        _nets = json.loads((Path(__file__).parent.parent / "passivmos2" / "networks.json").read_text())
        _cg_fallback: Dict[str, float] = {
            c["native_symbol"]: _cg_prices.get(c["coingecko_id"], 0.0)
            for c in _nets.get("cosmos_chains", [])
            if c.get("coingecko_id")
        }

        # Pre-fetch EVM prices/APRs if any 0x addresses present
        evm_addresses = [a for a in session.addresses if a.startswith("0x")]
        evm_prices: dict = {}
        evm_aprs: dict = {}
        if evm_addresses:
            yield send_event("progress", {"message": f"🔗 Fetching EVM prices & APRs for {len(evm_addresses)} Ethereum address(es)...", "step": 2, "total": 10})
            evm_prices, evm_aprs = await asyncio.gather(get_evm_prices(), get_evm_aprs())

        # Analyze all addresses in parallel
        yield send_event("progress", {"message": f"🔍 Scanning {len(session.addresses)} address(es) in parallel...", "step": 3, "total": 10})

        async with WalletAddressAnalyzer() as analyzer:

            async def process_address(address: str):
                """Returns (analyses, events) for one address. Never raises."""
                analyses, events = [], []
                try:
                    if address.startswith("0x"):
                        # ── EVM ──────────────────────────────────────────────
                        evm_balances = await analyze_evm_address(address)
                        if not evm_balances:
                            events.append(("warning", {"message": f"⚠️  No EVM balances found for {address[:12]}..."}))
                            return analyses, events

                        for token_bal in evm_balances:
                            symbol = token_bal.symbol
                            price  = evm_prices.get(symbol, 0.0)
                            apr    = evm_aprs.get(symbol, 0.0)
                            total_value_usd  = token_bal.balance * price
                            yearly_earnings  = token_bal.balance * price * (apr / 100) if apr > 0 else 0.0
                            events.append(("found", {
                                "message": f"💰 Found {token_bal.balance:.4f} {symbol} on {token_bal.chain_name} (${total_value_usd:.2f})",
                                "chain": token_bal.chain_name, "token": symbol, "balance": token_bal.balance,
                            }))
                            analyses.append({
                                'address': address, 'original_address': address,
                                'chain': token_bal.chain_name, 'token_symbol': symbol,
                                'available_balance': token_bal.balance, 'delegated_balance': 0.0,
                                'total_balance': token_bal.balance, 'token_price': price,
                                'apr': apr, 'apr_status': 'ok' if apr > 0 else 'none',
                                'apr_source': 'live' if apr > 0 else 'none',
                                'has_apr_issue': apr == 0,
                                'total_value_usd': total_value_usd,
                                'daily_earnings': yearly_earnings / 365,
                                'monthly_earnings': yearly_earnings / 12,
                                'yearly_earnings': yearly_earnings,
                            })

                    elif address.startswith("addr1") or address.startswith("stake1"):
                        # ── Cardano ───────────────────────────────────────────
                        import aiohttp as _aiohttp
                        connector = _aiohttp.TCPConnector(limit=5)
                        async with _aiohttp.ClientSession(
                            connector=connector,
                            headers={"User-Agent": "CoinFolio/1.0"},
                        ) as ada_session:
                            ada_holdings = await scan_cardano(ada_session, address)

                        if not ada_holdings:
                            events.append(("warning", {"message": f"⚠️  No Cardano balances found for {address[:12]}..."}))
                            return analyses, events

                        ada_price = load_prices().get("cardano", 0.0)
                        for h in ada_holdings:
                            bal = h["balance"]
                            usd = bal * ada_price
                            sym = h["symbol"]
                            staking_apr = h.get("staking_apr") or 0.0
                            yearly = usd * (staking_apr / 100) if staking_apr > 0 and "(Staked)" in sym else 0.0
                            events.append(("found", {
                                "message": f"₳ Found {bal:.2f} {sym} on Cardano (${usd:.2f})",
                                "chain": "Cardano", "token": sym, "balance": bal,
                            }))
                            analyses.append({
                                'address': address, 'original_address': address,
                                'chain': 'Cardano', 'token_symbol': sym,
                                'available_balance': bal,
                                'delegated_balance': bal if "(Staked)" in sym else 0.0,
                                'total_balance': bal, 'token_price': ada_price,
                                'apr': staking_apr,
                                'apr_status': 'fallback' if h.get('staking_apr_fallback') else ('ok' if staking_apr > 0 else 'none'),
                                'apr_source': 'koios',
                                'has_apr_issue': staking_apr == 0,
                                'total_value_usd': usd,
                                'daily_earnings': yearly / 365,
                                'monthly_earnings': yearly / 12,
                                'yearly_earnings': yearly,
                            })

                    else:
                        # ── Cosmos ────────────────────────────────────────────
                        all_chain_addresses = Bech32Converter.get_all_chain_addresses(address)
                        if not all_chain_addresses:
                            events.append(("warning", {"message": f"⚠️  Could not convert address: {address[:12]}..."}))
                            return analyses, events

                        async def check_chain(chain_name, chain_address):
                            try:
                                wb = await analyzer.get_wallet_balance(chain_address, chain_name)
                                return (chain_name, chain_address, wb) if wb and wb.total_balance > 0 else None
                            except Exception:
                                return None

                        chain_results = await asyncio.gather(*[
                            check_chain(cn, ca) for cn, ca in all_chain_addresses.items()
                        ])

                        for result in chain_results:
                            if result is None:
                                continue
                            chain_name, chain_address, wb = result
                            token_data = cached_data.get(wb.token_symbol)
                            if not token_data:
                                events.append(("warning", {"message": f"⚠️  No price data for {wb.token_symbol}"}))
                                continue
                            has_apr_issue = token_data.apr_status in ('error', 'fallback') or token_data.apr == 0
                            apr_to_use    = token_data.apr if not has_apr_issue else 0
                            # Numia doesn't price every token (e.g. NLS) — fall back to CoinGecko cache
                            price = token_data.price or _cg_fallback.get(wb.token_symbol, 0.0)
                            total_value_usd = wb.total_balance * price
                            yearly_earnings = wb.delegated_balance * (apr_to_use / 100) * price if apr_to_use > 0 else 0.0
                            events.append(("found", {
                                "message": f"💰 Found {wb.total_balance:.2f} {wb.token_symbol} on {chain_name}",
                                "chain": chain_name, "token": wb.token_symbol, "balance": wb.total_balance,
                            }))
                            analyses.append({
                                'address': chain_address, 'original_address': address,
                                'chain': chain_name, 'token_symbol': wb.token_symbol,
                                'available_balance': wb.available_balance, 'delegated_balance': wb.delegated_balance,
                                'total_balance': wb.total_balance, 'token_price': price,
                                'apr': apr_to_use, 'apr_status': token_data.apr_status,
                                'apr_source': token_data.apr_source, 'has_apr_issue': has_apr_issue,
                                'total_value_usd': total_value_usd,
                                'daily_earnings': yearly_earnings / 365,
                                'monthly_earnings': yearly_earnings / 12,
                                'yearly_earnings': yearly_earnings,
                            })

                except Exception as e:
                    events.append(("warning", {"message": f"⚠️  Error analyzing {address[:12]}...: {str(e)}"}))

                return analyses, events

            # Fire all addresses at once
            all_results = await asyncio.gather(*[
                process_address(addr) for addr in session.addresses
            ])

            wallet_analyses = []
            for analyses, events in all_results:
                for event_type, data in events:
                    yield send_event(event_type, data)
                wallet_analyses.extend(analyses)

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
@limiter.limit("5/minute")
async def calculate_portfolio_stream(code: str, request: Request, owner_hash: str = Depends(require_session)):
    """Stream portfolio calculation progress via Server-Sent Events"""
    # Validate code
    if not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code format")
    require_owner(code, owner_hash)

    return StreamingResponse(
        calculate_portfolio_generator(code),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/calculate")
@limiter.limit("5/minute")
async def calculate_portfolio(req: CalculateRequest, request: Request, owner_hash: str = Depends(require_session)):
    """Calculate portfolio for a user's addresses (non-streaming version for compatibility)"""
    request_data = req
    require_owner(request_data.code, owner_hash)
    logger.info("Calculating portfolio")

    # Apply timeout protection
    try:
        return await asyncio.wait_for(
            _calculate_portfolio_internal(request_data.code),
            timeout=60.0  # 60 second timeout
        )
    except asyncio.TimeoutError:
        logger.error("Calculation timeout")
        raise HTTPException(status_code=504, detail="Calculation timeout. Please try with fewer addresses.")

async def _calculate_portfolio_internal(code: str):
    """Internal calculation logic with timeout"""

    # Load session
    session = await asyncio.to_thread(load_session, code)
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

        # Helper function to check a single chain
        async def check_chain_balance(address, chain_name, chain_address):
            try:
                wallet_balance = await analyzer.get_wallet_balance(chain_address, chain_name)
                if not wallet_balance or wallet_balance.total_balance == 0:
                    return None

                token_symbol = wallet_balance.token_symbol
                token_data = cached_data.get(token_symbol)
                if not token_data:
                    return None

                total_value_usd = wallet_balance.total_balance * token_data.price
                yearly_earnings = wallet_balance.delegated_balance * (token_data.apr / 100) * token_data.price
                daily_earnings = yearly_earnings / 365
                monthly_earnings = yearly_earnings / 12

                return {
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
                }
            except Exception:
                return None

        # Create all tasks for all addresses and chains
        all_tasks = []
        for address in session.addresses:
            try:
                all_chain_addresses = Bech32Converter.get_all_chain_addresses(address)
                if not all_chain_addresses:
                    continue

                for chain_name, chain_address in all_chain_addresses.items():
                    all_tasks.append(check_chain_balance(address, chain_name, chain_address))
            except Exception:
                continue

        # Bound fan-out: 50 wallets can otherwise produce hundreds of stalled
        # HTTP coroutines before the per-chain timeout gets a chance to run.
        semaphore = asyncio.Semaphore(20)
        async def bounded(task):
            async with semaphore:
                return await task
        results = await asyncio.gather(*(bounded(task) for task in all_tasks))

        # Collect valid results
        wallet_analyses = [r for r in results if r is not None]

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
        code=code,
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

async def background_price_collector():
    """Background task to collect prices and APRs every 10 minutes"""
    while True:
        try:
            logger.info("🔄 Running background price/APR collection...")
            await price_scraper.scrape_all()
            logger.info("✅ Background collection complete")
        except Exception as e:
            logger.error(f"❌ Background collection error: {e}")

        # Wait 10 minutes before next run
        await asyncio.sleep(600)

# ── Frontend Event Logger ──────────────────────────────────────────────────────

_UI_EMOJI = {
    "sign_in":      EMOJI["signin"],
    "sign_out":     EMOJI["signout"],
    "wallet_add":   EMOJI["wallet_add"],
    "wallet_remove":EMOJI["wallet_rm"],
    "scan_start":   EMOJI["ui_scan"],
    "scan_done":    EMOJI["ui_done"],
    "period_change":EMOJI["period"],
    "page_load":    EMOJI["load"],
}

class FrontendLogRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    data: dict = {}

@app.post("/api/log")
@limiter.limit("30/minute")
async def frontend_log(req: FrontendLogRequest, request: Request):
    """Receive UI events from the frontend and write them to the log."""
    emoji = _UI_EMOJI.get(req.action, "📌")
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    # Keep client-controlled values to a single log line.
    extra = "  ".join(f"{str(k)[:40]}={str(v).replace(chr(10), ' ').replace(chr(13), ' ')[:200]}"
                      for k, v in list(req.data.items())[:20]) if req.data else ""
    logger.info(f"{emoji} [UI] {req.action}  {extra}  · {ip}")
    return {"ok": True}


# ── CoinFolio API Endpoints ────────────────────────────────────────────────────

class HoldingInput(BaseModel):
    chain: str = Field(min_length=1, max_length=64)
    chain_type: str = Field(default="", max_length=32)
    symbol: str = Field(min_length=1, max_length=100)
    balance: float = Field(ge=0)
    coingecko_id: Optional[str] = Field(default=None, max_length=128)
    lpp_apr: Optional[float] = Field(default=None, ge=0, le=1000)
    staking_apr: Optional[float] = Field(default=None, ge=0, le=1000)

    @validator("balance", "lpp_apr", "staking_apr")
    def finite_number(cls, value):
        if value is not None and not math.isfinite(value):
            raise ValueError("Must be a finite number")
        return value

class CoinfolioSnapshotRequest(BaseModel):
    code: str
    holdings: List[HoldingInput] = Field(max_length=MAX_HOLDINGS_PER_SNAPSHOT)

@app.get("/api/coinfolio/portfolio")
async def coinfolio_get_portfolio(code: str, request: Request, owner_hash: str = Depends(require_session)):
    """Return the last stored portfolio for this user, with prices injected."""
    if not code or not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)
    session = await asyncio.to_thread(load_session, code)
    if not session:
        raise HTTPException(status_code=404, detail="User not found")

    h = code_to_hash(code)
    portfolio = load_portfolio(h)
    prices = load_prices()

    return {
        "portfolio": portfolio,  # None if never scanned
        "prices": prices,
        "prices_updated_ts": load_prices_updated_ts(),
    }

@app.get("/api/portfolio/cached")
async def portfolio_cached(code: str, request: Request, owner_hash: str = Depends(require_session)):
    """
    Return last background-scanned portfolio translated to the format displayPortfolioResults() expects.
    Returns {available: false} when no cached data exists yet.
    """
    if not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)

    h = code_to_hash(code)
    portfolio = load_portfolio(h)
    if not portfolio:
        return {"available": False}

    aprs = load_aprs()
    holdings = portfolio.get("holdings", [])
    total_usd = portfolio.get("total_usd", 0)
    yearly_income_usd = portfolio.get("yearly_income_usd", 0)

    wallets = []
    for item in holdings:
        sym = item.get("symbol", "")
        bal = item.get("balance", 0)
        usd = item.get("usd_value", 0)
        base_sym = sym.replace(" (Staked)", "").replace(" (Rewards)", "").strip()
        apr = aprs.get(base_sym, 0)

        if "(LPP)" in sym or sym == "USDC Deposited":
            yearly = usd * (item.get("lpp_apr", 0) / 100)
        elif "(Staked)" in sym:
            yearly = usd * (apr / 100)
        else:
            yearly = 0.0

        wallets.append({
            "address": "",
            "chain": item.get("chain", ""),
            "token_symbol": sym,
            "total_balance": bal,
            "delegated_balance": bal if "(Staked)" in sym else 0,
            "total_value_usd": usd,
            "apr": apr,
            "apr_status": "cached",
            "has_apr_issue": apr == 0 and ("(Staked)" in sym or "(LPP)" in sym),
            "yearly_earnings": round(yearly, 6),
            "monthly_earnings": round(yearly / 12, 6),
            "daily_earnings": round(yearly / 365, 6),
            "original_address": None,
        })

    token_breakdown: Dict[str, Dict] = {}
    for w in wallets:
        token = w["token_symbol"]
        if token not in token_breakdown:
            token_breakdown[token] = {
                "total_balance": 0.0, "total_value_usd": 0.0,
                "yearly_earnings": 0.0, "monthly_earnings": 0.0, "daily_earnings": 0.0,
                "apr": w["apr"],
            }
        token_breakdown[token]["total_balance"]    += w["total_balance"]
        token_breakdown[token]["total_value_usd"]  += w["total_value_usd"]
        token_breakdown[token]["yearly_earnings"]  += w["yearly_earnings"]
        token_breakdown[token]["monthly_earnings"] += w["monthly_earnings"]
        token_breakdown[token]["daily_earnings"]   += w["daily_earnings"]

    return {
        "available": True,
        "total_value_usd": round(total_usd, 2),
        "daily_earnings": round(yearly_income_usd / 365, 4),
        "monthly_earnings": round(yearly_income_usd / 12, 4),
        "yearly_earnings": round(yearly_income_usd, 2),
        "last_updated": portfolio.get("scanned_at", datetime.now().isoformat()),
        "wallets": wallets,
        "token_breakdown": token_breakdown,
    }

@app.post("/api/coinfolio/snapshot")
@limiter.limit("10/minute")
async def coinfolio_save_snapshot(req: CoinfolioSnapshotRequest, request: Request, owner_hash: str = Depends(require_session)):
    """
    Frontend sends raw on-chain holdings (no prices).
    Backend injects cached prices, saves portfolio + history.
    """
    if not validate_user_code(req.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(req.code, owner_hash)
    session = await asyncio.to_thread(load_session, req.code)
    if not session:
        raise HTTPException(status_code=404, detail="User not found")

    prices = load_prices()
    # Inject prices into holdings
    holdings = []
    for item in req.holdings:
        h = item.dict(exclude_none=True)
        if h.get("symbol") == "USDC Deposited" or (h.get("price") == 1.0 and h.get("lpp_apr") is not None):
            h["price"] = 1.0
            h["usd_value"] = h.get("balance", 0)
        else:
            price = prices.get(h.get("coingecko_id", ""), 0)
            h["price"] = price
            h["usd_value"] = h.get("balance", 0) * price
        holdings.append(h)

    total_usd = sum(h["usd_value"] for h in holdings)
    aprs = load_aprs()
    yearly_income_usd = calculate_yearly_income(holdings, aprs)
    code_hash = code_to_hash(req.code)
    await persist_portfolio(code_hash, holdings, total_usd, yearly_income_usd)

    logger.info(f"{EMOJI['portfolio']} Snapshot saved  user={code_hash[:8]}  total=${total_usd:.2f}  yearly=${yearly_income_usd:.2f}  holdings={len(holdings)}")
    return {"total_usd": round(total_usd, 2), "yearly_income_usd": round(yearly_income_usd, 2), "holdings": len(holdings)}

@app.get("/api/coinfolio/history")
async def coinfolio_get_history(code: str, request: Request, owner_hash: str = Depends(require_session)):
    """Return portfolio history for chart."""
    if not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)
    session = await asyncio.to_thread(load_session, code)
    if not session:
        raise HTTPException(status_code=404, detail="User not found")
    return load_history(code_to_hash(code))

@app.get("/api/coinfolio/prices")
async def coinfolio_get_prices(request: Request):
    """Return current cached prices."""
    return load_prices()

@app.get("/api/coinfolio/aprs")
async def coinfolio_get_aprs():
    """Return staking APRs per token from the local scraper cache, plus Cardano."""
    result = {}
    try:
        cache_file = Path(__file__).parent.parent / "data" / "cache" / "token_data.json"
        with open(cache_file) as f:
            data = json.load(f)
        result = {
            sym: {
                "apr": round(float(v.get("apr", 0)), 2),
                "apr_status": v.get("apr_status", "unknown"),
                "apr_source": v.get("apr_source", ""),
            }
            for sym, v in data.items()
        }
    except Exception:
        pass
    return result

@app.get("/api/coinfolio/cardano")
@limiter.limit("10/minute")
async def coinfolio_scan_cardano(address: str, request: Request, owner_hash: str = Depends(require_session)):
    """
    Proxy Cardano scan through backend (Koios POST responses lack CORS headers).
    Returns raw holdings list for the given addr1/stake1 address.
    """
    if not address or not (address.startswith("addr1") or address.startswith("stake1")):
        raise HTTPException(status_code=400, detail="Invalid Cardano address")
    if not re.match(r'^[a-z0-9]+$', address) or len(address) > 110:
        raise HTTPException(status_code=400, detail="Invalid Cardano address")

    import aiohttp as _aiohttp
    from coinfolio_scanner import scan_cardano, KOIOS_URL

    connector = _aiohttp.TCPConnector(limit=10)
    async with _aiohttp.ClientSession(connector=connector, headers={"User-Agent": "CoinFolio/1.0"}) as session:
        holdings = await scan_cardano(session, address)

    prices = load_prices()
    for h in holdings:
        if h.get("coingecko_id"):
            price = prices.get(h["coingecko_id"], 0)
            h["price"] = price
            h["usd_value"] = h["balance"] * price

    return holdings


# ── Purchase Tracker ──────────────────────────────────────────────────────────
import purchases as _pur

class AddPurchaseRequest(BaseModel):
    code: str
    token: str = Field(min_length=1, max_length=32)
    amount: float
    price_usd: float
    date: str = Field(min_length=10, max_length=10)
    flag: str = Field(min_length=1, max_length=80)

    @validator('code')
    def validate_code(cls, v):
        if not validate_user_code(v):
            raise ValueError('Invalid code format.')
        return v

    @validator('amount', 'price_usd')
    def positive(cls, v):
        if not math.isfinite(v) or v <= 0:
            raise ValueError('Must be positive')
        return v

    @validator('date')
    def valid_date(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be YYYY-MM-DD")
        return v

class AddFlagRequest(BaseModel):
    code: str
    flag: str

    @validator('code')
    def validate_code(cls, v):
        if not validate_user_code(v):
            raise ValueError('Invalid code format.')
        return v

    @validator('flag')
    def validate_flag(cls, v):
        v = v.strip()
        if not v or len(v) > 80:
            raise ValueError('Flag must be 1-80 chars')
        return v


@app.get("/api/purchases/{code}")
async def get_purchases(code: str, request: Request, owner_hash: str = Depends(require_session)):
    if not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)
    code_hash = code_to_hash(code)
    data = _pur.get_purchases(code_hash)

    # Pull on-chain balances from last cached portfolio for unrecorded diff
    portfolio = load_portfolio(code_hash)
    on_chain: Dict[str, float] = {}
    if portfolio and "holdings" in portfolio:
        for h in portfolio["holdings"]:
            sym = (h.get("symbol") or h.get("token") or "").upper()
            if sym:
                on_chain[sym] = on_chain.get(sym, 0) + h.get("balance", 0)

    summary = _pur.summarize(data["purchases"], on_chain)
    return {
        "purchases": data["purchases"],
        "custom_flags": data["custom_flags"],
        "preset_flags": _pur.PRESET_FLAGS,
        "summary": summary,
    }


@app.post("/api/purchases/{code}")
@limiter.limit("20/minute")
async def add_purchase(code: str, req: AddPurchaseRequest, request: Request, owner_hash: str = Depends(require_session)):
    if code != req.code or not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)
    code_hash = code_to_hash(code)
    entry = _pur.add_purchase(code_hash, req.token, req.amount, req.price_usd, req.date, req.flag)
    return entry


@app.delete("/api/purchases/{code}/{purchase_id}")
@limiter.limit("20/minute")
async def delete_purchase(code: str, purchase_id: str, request: Request, owner_hash: str = Depends(require_session)):
    if not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)
    if not re.match(r'^[a-f0-9]{12}$', purchase_id):
        raise HTTPException(status_code=400, detail="Invalid purchase ID")
    code_hash = code_to_hash(code)
    ok = _pur.delete_purchase(code_hash, purchase_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return {"deleted": purchase_id}


@app.post("/api/purchases/{code}/flags")
@limiter.limit("20/minute")
async def add_flag(code: str, req: AddFlagRequest, request: Request, owner_hash: str = Depends(require_session)):
    if code != req.code or not validate_user_code(code):
        raise HTTPException(status_code=400, detail="Invalid code")
    require_owner(code, owner_hash)
    code_hash = code_to_hash(code)
    flags = _pur.add_custom_flag(code_hash, req.flag)
    return {"custom_flags": flags}


@app.on_event("startup")
async def startup_event():
    logger.info(f"{EMOJI['start']} PassivMOS starting on port 8000")

    try:
        cached = price_scraper.load_cache()
        if cached:
            logger.info(f"{EMOJI['load']} Loaded cached prices for {len(cached)} tokens")
        else:
            logger.info(f"{EMOJI['warn']} No price cache — will fetch on first background run")
    except Exception as e:
        logger.warning(f"{EMOJI['warn']} Cache load failed: {e}")

    logger.info(f"{EMOJI['clock']} Background: Numia prices every 10 min")
    asyncio.create_task(background_price_collector())

    logger.info(f"{EMOJI['clock']} Background: CoinGecko prices every 2 min · portfolio cycle 30 min")
    asyncio.create_task(price_refresh_loop())
    asyncio.create_task(portfolio_cycle_loop())

    logger.info(f"{EMOJI['ready']} PassivMOS ready")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"{EMOJI['stop']} PassivMOS shutting down")

if __name__ == "__main__":
    import uvicorn
    import os
    # Use PORT from environment or default to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
