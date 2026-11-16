#!/usr/bin/env python3
"""
CoinFolio Background Scanner
- Fetches CoinGecko prices every 2 min (batched to avoid rate limiting)
- Scans user portfolios (EVM + Cosmos + Nolus) on a 30-min rolling cycle
- Stores everything in plain JSON files under data/
"""

import asyncio
import aiohttp
import json
import hashlib
import logging
import base64
import time
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

from bech32 import bech32_decode, bech32_encode

logger = logging.getLogger("passivmos.scanner")

# ── Paths ──────────────────────────────────────────────────────────────────────
DATA_DIR       = Path(__file__).parent.parent / "data"
PRICES_FILE    = DATA_DIR / "prices.json"
PORTFOLIOS_DIR = DATA_DIR / "portfolios"
HISTORY_DIR    = DATA_DIR / "history"
SESSIONS_DIR   = Path(__file__).parent.parent / "sessions"
NETWORKS_FILE  = Path(__file__).parent.parent / "passivmos2" / "networks.json"

PORTFOLIOS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ──────────────────────────────────────────────────────────────────
COINGECKO_URL    = "https://api.coingecko.com/api/v3/simple/price"
PRICE_BATCH_SIZE = 20          # IDs per CoinGecko request
PRICE_BATCH_DELAY = 7          # seconds between batches (free tier: ~10 req/min)
PRICE_INTERVAL   = 120         # seconds between full price refresh cycles
PORTFOLIO_CYCLE  = 1800        # 30 minutes total cycle for all users
HISTORY_MAX_DAYS = 30
TIMEOUT          = 12          # seconds per HTTP request
SCAN_CONCURRENCY  = 20
_portfolio_locks: Dict[str, asyncio.Lock] = {}

KOIOS_URL      = "https://api.koios.rest/api/v1"
NOLUS_LCD      = "https://rest.cosmos.directory/nolus"
NOLUS_CONTRACT = "nolus1gurgpv8savnfw66lckwzn4zk7fp394lpe667dhu7aw48u40lj6jsqxf8nd"
NOLUS_DECIMALS = {
    "NLS":6,"OSMO":6,"ATOM":6,"TIA":6,"AKT":6,"NTRN":6,
    "ST_ATOM":6,"STKATOM":6,"STATOM":6,"ALL_BTC":8,"ALL_SOL":9,
    "USDC":6,"USDC_NOBLE":6,"USDC_AXL":6,"USDT":6,
}
NOLUS_CG = {
    "ST_ATOM":"stride-staked-atom","STKATOM":"stride-staked-atom",
    "STATOM":"stride-staked-atom","ALL_BTC":"bitcoin","ALL_SOL":"solana",
    "USDC":"usd-coin","USDC_NOBLE":"usd-coin","USDC_AXL":"usd-coin",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def code_to_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:16]

def reencode_address(address: str, new_prefix: str) -> Optional[str]:
    try:
        hrp, data = bech32_decode(address)
        if hrp is None or data is None:
            return None
        return bech32_encode(new_prefix, data)
    except Exception:
        return None

def load_networks() -> Dict:
    try:
        with open(NETWORKS_FILE) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load networks.json: {e}")
        return {"evm_chains": [], "cosmos_chains": [], "erc20_tokens": {}}

def load_prices() -> Dict[str, float]:
    try:
        with open(PRICES_FILE) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}

def load_prices_updated_ts() -> Optional[int]:
    try:
        with open(PRICES_FILE) as f:
            return json.load(f).get("_updated_ts")
    except Exception:
        return None

def save_prices(prices: Dict[str, float]):
    out = {"_updated": datetime.now(timezone.utc).isoformat(), "_updated_ts": int(time.time())}
    out.update(prices)
    tmp = PRICES_FILE.with_name(f".{PRICES_FILE.name}.{secrets.token_hex(8)}.tmp")
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2)
    tmp.rename(PRICES_FILE)
    logger.info(f"💰 Prices saved — {len(prices)} tokens")

def load_aprs() -> Dict[str, float]:
    """Load staking APRs from PassivMOS token_data.json cache. Returns symbol → apr%."""
    try:
        cache_file = DATA_DIR / "cache" / "token_data.json"
        with open(cache_file) as f:
            data = json.load(f)
        return {sym: float(v.get("apr", 0)) for sym, v in data.items()}
    except Exception:
        return {}

def calculate_yearly_income(holdings: List[Dict], aprs: Dict[str, float]) -> float:
    """Sum yearly income across all holdings."""
    total = 0.0
    for h in holdings:
        sym = h.get("symbol", "")
        usd = h.get("usd_value", 0)
        if sym == "USDC Deposited" or "(LPP)" in sym:
            total += usd * (h.get("lpp_apr", 0) / 100)
        elif h.get("staking_apr") is not None and sym == "ADA (Staked)":
            # Cardano: only delegated ADA earns staking rewards
            total += usd * (h["staking_apr"] / 100)
        elif "(Staked)" in sym:
            base = sym.replace(" (Staked)", "").strip()
            apr = aprs.get(base, 0)
            total += usd * (apr / 100)
    return round(total, 4)

def save_portfolio(code_hash: str, holdings: List[Dict], total_usd: float, yearly_income_usd: float = 0.0):
    path = PORTFOLIOS_DIR / f"{code_hash}.json"
    out = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "scanned_at_ts": int(time.time()),
        "total_usd": round(total_usd, 4),
        "yearly_income_usd": round(yearly_income_usd, 4),
        "holdings": holdings,
    }
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2)
    tmp.rename(path)

def load_portfolio(code_hash: str) -> Optional[Dict]:
    path = PORTFOLIOS_DIR / f"{code_hash}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def append_history(code_hash: str, total_usd: float, yearly_income_usd: float = 0.0):
    path = HISTORY_DIR / f"{code_hash}.json"
    try:
        with open(path) as f:
            history = json.load(f)
    except Exception:
        history = []

    now = int(time.time())
    cutoff = now - HISTORY_MAX_DAYS * 86400
    history = [e for e in history if e.get("ts", 0) >= cutoff]
    history.append({"ts": now, "total_usd": round(total_usd, 2), "yearly_income_usd": round(yearly_income_usd, 2)})

    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    with open(tmp, "w") as f:
        json.dump(history, f)
    tmp.rename(path)

async def persist_portfolio(code_hash: str, holdings: List[Dict], total_usd: float,
                            yearly_income_usd: float = 0.0):
    """Serialize a user's portfolio/history update so no snapshot is lost."""
    lock = _portfolio_locks.setdefault(code_hash, asyncio.Lock())
    async with lock:
        save_portfolio(code_hash, holdings, total_usd, yearly_income_usd)
        append_history(code_hash, total_usd, yearly_income_usd)

def load_history(code_hash: str) -> List[Dict]:
    path = HISTORY_DIR / f"{code_hash}.json"
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []

def list_all_users() -> List[Dict]:
    """Return list of {hash, addresses} for all session files."""
    users = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            with open(f) as fh:
                data = json.load(fh)
            if data.get("addresses"):
                users.append({
                    "hash": f.stem,
                    "addresses": data["addresses"],
                })
        except Exception:
            pass
    return users


# ── Price Fetcher ──────────────────────────────────────────────────────────────

async def fetch_prices_batch(session: aiohttp.ClientSession, ids: List[str]) -> Dict[str, float]:
    params = {"ids": ",".join(ids), "vs_currencies": "usd"}
    try:
        async with session.get(COINGECKO_URL, params=params, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
            if r.status == 429:
                logger.warning("🚦 CoinGecko rate limit hit — skipping batch")
                return {}
            data = await r.json()
            return {k: v.get("usd", 0) for k, v in data.items() if isinstance(v, dict)}
    except Exception as e:
        logger.warning(f"⚠️  Price batch error: {e}")
        return {}

async def refresh_prices():
    """Collect all coingecko_ids from networks.json and fetch in batches."""
    nets = load_networks()
    ids = set()

    for chain in nets.get("evm_chains", []):
        if chain.get("coingecko_id"):
            ids.add(chain["coingecko_id"])
    for tokens in nets.get("erc20_tokens", {}).values():
        for t in tokens:
            if t.get("coingecko_id"):
                ids.add(t["coingecko_id"])
    for chain in nets.get("cosmos_chains", []):
        if chain.get("coingecko_id"):
            ids.add(chain["coingecko_id"])
    # Add Nolus-specific ids
    for cg_id in NOLUS_CG.values():
        ids.add(cg_id)
    # Cardano
    ids.add("cardano")

    ids = [i for i in ids if i]  # remove empty
    batches = [list(ids)[i:i+PRICE_BATCH_SIZE] for i in range(0, len(ids), PRICE_BATCH_SIZE)]

    prices = load_prices()  # start from existing so partial failures don't wipe data

    async with aiohttp.ClientSession(headers={"User-Agent": "CoinFolio/1.0"}) as session:
        for i, batch in enumerate(batches):
            result = await fetch_prices_batch(session, batch)
            prices.update(result)
            if i < len(batches) - 1:
                await asyncio.sleep(PRICE_BATCH_DELAY)

    save_prices(prices)
    return prices


# ── On-Chain Scanners ──────────────────────────────────────────────────────────

async def rpc_call(session: aiohttp.ClientSession, rpc: str, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(rpc, json=payload, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
        data = await r.json()
        return data.get("result")

async def scan_evm_chain(session: aiohttp.ClientSession, address: str, chain: Dict, tokens: List[Dict]) -> List[Dict]:
    """Scan one EVM chain — native balance + all ERC20 tokens, all concurrent."""
    results = []

    async def native():
        try:
            hex_bal = await rpc_call(session, chain["rpc"], "eth_getBalance", [address, "latest"])
            bal = int(hex_bal, 16) / 10 ** chain["native_decimals"]
            if bal > 0:
                return {"chain": chain["name"], "chain_type": "evm",
                        "symbol": chain["native_symbol"], "balance": bal,
                        "coingecko_id": chain["coingecko_id"], "price": 0, "usd_value": 0}
        except Exception:
            pass
        return None

    async def erc20(token):
        try:
            data_hex = "0x70a08231" + "000000000000000000000000" + address[2:]
            hex_bal = await rpc_call(session, chain["rpc"], "eth_call",
                                     [{"to": token["address"], "data": data_hex}, "latest"])
            tb = int(hex_bal, 16) / 10 ** token["decimals"]
            if tb > 0:
                return {"chain": chain["name"], "chain_type": "evm",
                        "symbol": token["symbol"], "balance": tb,
                        "coingecko_id": token["coingecko_id"], "price": 0, "usd_value": 0}
        except Exception:
            pass
        return None

    tasks = [native()] + [erc20(t) for t in tokens]
    items = await asyncio.gather(*tasks, return_exceptions=False)
    return [h for h in items if h]

async def scan_evm(session: aiohttp.ClientSession, address: str, nets: Dict) -> List[Dict]:
    erc20_map = nets.get("erc20_tokens", {})
    tasks = [
        scan_evm_chain(session, address, chain, erc20_map.get(str(chain["id"]), []))
        for chain in nets.get("evm_chains", [])
    ]
    nested = await asyncio.gather(*tasks, return_exceptions=False)
    return [h for sublist in nested for h in sublist]

async def scan_cosmos_chain(session: aiohttp.ClientSession, address: str, chain: Dict) -> List[Dict]:
    """Scan one Cosmos chain — bank + staking + rewards, all concurrent."""
    chain_addr = reencode_address(address, chain["prefix"])
    if not chain_addr:
        return []
    sym, dec, lcd = chain["native_symbol"], chain["native_decimals"], chain["lcd"]
    results = []

    async def bank():
        try:
            async with session.get(f"{lcd}/cosmos/bank/v1beta1/balances/{chain_addr}",
                                   timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                bals = await r.json()
            for b in bals.get("balances", []):
                if b["denom"] == chain["native_denom"]:
                    bal = float(b["amount"]) / 10 ** dec
                    if bal > 0:
                        return {"chain": chain["name"], "chain_type": "cosmos",
                                "symbol": sym, "balance": bal,
                                "coingecko_id": chain["coingecko_id"], "price": 0, "usd_value": 0}
        except Exception:
            pass
        return None

    async def staking():
        try:
            async with session.get(f"{lcd}/cosmos/staking/v1beta1/delegations/{chain_addr}",
                                   timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                stk = await r.json()
            amt = sum(float(d["balance"]["amount"]) for d in stk.get("delegation_responses", []))
            if amt > 0:
                return {"chain": chain["name"], "chain_type": "cosmos",
                        "symbol": f"{sym} (Staked)", "balance": amt / 10 ** dec,
                        "coingecko_id": chain["coingecko_id"], "price": 0, "usd_value": 0}
        except Exception:
            pass
        return None

    async def rewards():
        try:
            async with session.get(f"{lcd}/cosmos/distribution/v1beta1/delegators/{chain_addr}/rewards",
                                   timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                rwd = await r.json()
            for r_entry in rwd.get("total", []):
                if r_entry["denom"] == chain["native_denom"]:
                    bal = float(r_entry["amount"]) / 10 ** dec
                    if bal >= 0.001:
                        return {"chain": chain["name"], "chain_type": "cosmos",
                                "symbol": f"{sym} (Rewards)", "balance": bal,
                                "coingecko_id": chain["coingecko_id"], "price": 0, "usd_value": 0}
        except Exception:
            pass
        return None

    items = await asyncio.gather(bank(), staking(), rewards())
    return [h for h in items if h]

async def scan_cosmos(session: aiohttp.ClientSession, address: str, nets: Dict) -> List[Dict]:
    tasks = [scan_cosmos_chain(session, address, chain) for chain in nets.get("cosmos_chains", [])]
    nested = await asyncio.gather(*tasks, return_exceptions=False)
    return [h for sublist in nested for h in sublist]

async def cosmwasm_query(session: aiohttp.ClientSession, lcd: str, contract: str, query: Dict) -> Optional[Dict]:
    encoded = base64.b64encode(json.dumps(query).encode()).decode()
    url = f"{lcd}/cosmwasm/wasm/v1/contract/{contract}/smart/{encoded}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
        data = await r.json()
        return data.get("data")

async def scan_nolus(session: aiohttp.ClientSession, address: str) -> List[Dict]:
    results = []
    try:
        pd = await cosmwasm_query(session, NOLUS_LCD, NOLUS_CONTRACT, {"protocols": {}})
        # protocols query returns a list directly, not {"protocols": [...]}
        protocols = pd if isinstance(pd, list) else ((pd or {}).get("protocols", []))
        for proto_id in protocols:
            try:
                p = await cosmwasm_query(session, NOLUS_LCD, NOLUS_CONTRACT, {"protocol": proto_id})
                if not p:
                    continue

                # Leases
                if p.get("contracts", {}).get("leaser"):
                    try:
                        ld = await cosmwasm_query(session, NOLUS_LCD, p["contracts"]["leaser"],
                                                  {"leases": {"owner": address}})
                        for lease in (ld or {}).get("leases", []):
                            if lease.get("opened", {}).get("amount", {}).get("ticker"):
                                tk = lease["opened"]["amount"]["ticker"]
                                dec = NOLUS_DECIMALS.get(tk, 6)
                                bal = int(lease["opened"]["amount"]["amount"]) / 10 ** dec
                                cg = NOLUS_CG.get(tk, tk.lower())
                                results.append({
                                    "chain": "Nolus", "chain_type": "cosmos",
                                    "symbol": f"Nolus Position ({tk})", "balance": bal,
                                    "coingecko_id": cg, "price": 0, "usd_value": 0,
                                })
                    except Exception:
                        pass

                # LPP deposits
                if p.get("contracts", {}).get("lpp"):
                    lpp = p["contracts"]["lpp"]
                    try:
                        bd = await cosmwasm_query(session, NOLUS_LCD, lpp, {"balance": {"address": address}})
                        # balance query returns {"amount":"..."} directly (nLPN tokens)
                        if bd and bd.get("amount") and int(bd["amount"]) > 0:
                            pr, lpp_bal, cfg = await asyncio.gather(
                                cosmwasm_query(session, NOLUS_LCD, lpp, {"price": []}),
                                cosmwasm_query(session, NOLUS_LCD, lpp, {"lpp_balance": []}),
                                cosmwasm_query(session, NOLUS_LCD, lpp, {"config": []}),
                            )
                            # Determine underlying asset ticker from lpp_balance
                            ticker = (lpp_bal or {}).get("balance", {}).get("ticker", "USDC")
                            is_stable = ticker.startswith("USDC") or ticker == "USDT"
                            LPP_CG = {
                                "ATOM": "cosmos", "OSMO": "osmosis", "TIA": "celestia",
                                "NLS": "nolus", "NTRN": "neutron-3", "AKT": "akash-network",
                                "USDC": "usd-coin", "USDC_NOBLE": "usd-coin", "USDC_AXL": "usd-coin",
                            }
                            cg = LPP_CG.get(ticker, "usd-coin")
                            sym = "USDC Deposited" if is_stable else f"{ticker} (LPP)"
                            # Convert nLPN → underlying asset amount
                            bal = int(bd["amount"]) / 1e6
                            if pr and pr.get("amount_quote", {}).get("amount") and pr.get("amount", {}).get("amount"):
                                bal *= float(pr["amount_quote"]["amount"]) / float(pr["amount"]["amount"])
                            # Live lender APR
                            lpp_apr = 0.0
                            if lpp_bal and cfg:
                                available   = int((lpp_bal.get("balance") or {}).get("amount", 0))
                                principal   = int((lpp_bal.get("total_principal_due") or {}).get("amount", 0))
                                interest    = int((lpp_bal.get("total_interest_due") or {}).get("amount", 0))
                                pool_total  = available + principal + interest
                                borrowed    = principal + interest
                                utilization = borrowed / pool_total if pool_total > 0 else 0
                                br          = cfg.get("borrow_rate", {})
                                base        = br.get("base_interest_rate", 0)
                                addon       = br.get("addon_optimal_interest_rate", 0)
                                util_opt    = br.get("utilization_optimal", 1000) / 1000
                                if utilization <= util_opt:
                                    borrow_rate_pct = (base + addon * (utilization / util_opt)) / 10
                                else:
                                    borrow_rate_pct = (base + addon + addon * ((utilization - util_opt) / (1 - util_opt))) / 10
                                lpp_apr = borrow_rate_pct * utilization
                            # Stable → price=1, usd_value=bal; volatile → price=0 (injected later)
                            price     = 1.0 if is_stable else 0.0
                            usd_value = bal if is_stable else 0.0
                            results.append({
                                "chain": "Nolus", "chain_type": "cosmos",
                                "symbol": sym, "balance": bal,
                                "coingecko_id": cg, "price": price, "usd_value": usd_value,
                                "lpp_apr": lpp_apr,
                            })
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"⚠️  Nolus scan error: {e}")

    return results


async def get_cardano_pool_apr(session: aiohttp.ClientSession, pool_id: str) -> float:
    """Fetch the average epoch_ros from the last 5 epochs as annualised APR (%)."""
    try:
        url = f"{KOIOS_URL}/pool_history?_pool_bech32={pool_id}&limit=5&order=epoch_no.desc"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
            data = await r.json()
        if isinstance(data, list) and data:
            ros_values = [float(e["epoch_ros"]) for e in data if e.get("epoch_ros") is not None]
            if ros_values:
                return round(sum(ros_values) / len(ros_values), 2)
    except Exception:
        pass
    return 3.5  # Cardano network average fallback

async def scan_cardano(session: aiohttp.ClientSession, address: str) -> List[Dict]:
    """Scan one Cardano address (addr1... or stake1...) via Koios API."""
    results = []
    try:
        if address.startswith("stake1"):
            # Stake address: account_info gives total balance + rewards
            url = f"{KOIOS_URL}/account_info"
            async with session.post(url,
                                    json={"_stake_addresses": [address]},
                                    headers={"accept": "application/json", "content-type": "application/json"},
                                    timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                data = await r.json()
            if not isinstance(data, list) or not data:
                return []
            info = data[0]
            total_lovelace    = int(info.get("total_balance") or 0)
            rewards_lovelace  = int(info.get("rewards_available") or 0)
            wallet_lovelace   = total_lovelace - rewards_lovelace
            delegated_pool    = info.get("delegated_pool")

            # Fetch pool APR (only when delegated)
            staking_apr = None
            staking_apr_fallback = False
            if delegated_pool:
                staking_apr = await get_cardano_pool_apr(session, delegated_pool)
                staking_apr_fallback = (staking_apr == 3.5)
            else:
                staking_apr = 3.5
                staking_apr_fallback = True

            if wallet_lovelace > 0:
                bal = wallet_lovelace / 1_000_000
                sym = "ADA (Staked)" if delegated_pool else "ADA"
                results.append({
                    "chain": "Cardano", "chain_type": "cardano",
                    "symbol": sym, "balance": bal,
                    "coingecko_id": "cardano", "price": 0, "usd_value": 0,
                    "staking_apr": staking_apr,
                    "staking_apr_fallback": staking_apr_fallback,
                })
            if rewards_lovelace > 0:
                bal = rewards_lovelace / 1_000_000
                results.append({
                    "chain": "Cardano", "chain_type": "cardano",
                    "symbol": "ADA (Rewards)", "balance": bal,
                    "coingecko_id": "cardano", "price": 0, "usd_value": 0,
                })
        elif address.startswith("addr1"):
            # Payment address: get address_info first to find the stake key
            url = f"{KOIOS_URL}/address_info"
            async with session.post(url,
                                    json={"_addresses": [address]},
                                    headers={"accept": "application/json", "content-type": "application/json"},
                                    timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                data = await r.json()
            if not isinstance(data, list) or not data:
                return []
            info = data[0]
            stake_addr = info.get("stake_address")
            if stake_addr:
                # Recurse with the stake address to get the full wallet balance
                # (HD wallet has many payment addresses; account_info aggregates all of them)
                return await scan_cardano(session, stake_addr)
            else:
                # Script or Byron address — just return the UTxO balance of this address
                lovelace = int(info.get("balance") or 0)
                if lovelace > 0:
                    results.append({
                        "chain": "Cardano", "chain_type": "cardano",
                        "symbol": "ADA", "balance": lovelace / 1_000_000,
                        "coingecko_id": "cardano", "price": 0, "usd_value": 0,
                    })
    except Exception as e:
        logger.warning(f"⚠️  Cardano scan error ({address[:12]}…): {e}")
    return results


# ── Portfolio Scanner ──────────────────────────────────────────────────────────

def inject_prices(holdings: List[Dict], prices: Dict[str, float]) -> List[Dict]:
    result = []
    for h in holdings:
        h = dict(h)
        if h["symbol"] == "USDC Deposited":
            h["price"] = 1.0
            h["usd_value"] = h["balance"]
        elif h.get("price", 0) == 1.0 and h.get("lpp_apr") is not None:
            # Already priced stable LPP (USDC variants)
            h["usd_value"] = h["balance"]
        else:
            price = prices.get(h.get("coingecko_id", ""), 0)
            h["price"] = price
            h["usd_value"] = h["balance"] * price
        result.append(h)
    return result

def merge_holdings(raw: List[Dict]) -> List[Dict]:
    """Sum duplicate chain+symbol entries, weighted-average lpp_apr."""
    merged = {}
    for h in raw:
        key = f"{h['chain']}::{h['symbol']}"
        if key in merged:
            prev = merged[key]
            new_bal = prev["balance"] + h["balance"]
            # Weighted average APR when merging Nolus LPP pools
            if h.get("lpp_apr") is not None and prev.get("lpp_apr") is not None and new_bal > 0:
                prev["lpp_apr"] = (prev["lpp_apr"] * prev["balance"] + h["lpp_apr"] * h["balance"]) / new_bal
            # Cardano staking APR — keep from first entry (same pool)
            if h.get("staking_apr") is not None and prev.get("staking_apr") is None:
                prev["staking_apr"] = h["staking_apr"]
            prev["balance"] = new_bal
            prev["usd_value"] = prev.get("usd_value", 0) + h.get("usd_value", 0)
        else:
            merged[key] = dict(h)
    return [h for h in merged.values() if h["balance"] > 0]

async def scan_user(addresses: List[str], prices: Optional[Dict[str, float]] = None) -> List[Dict]:
    """Scan all addresses concurrently and return holdings with prices injected."""
    if prices is None:
        prices = load_prices()

    nets = load_networks()
    evm_addrs     = [a for a in addresses if a.startswith("0x")]
    cardano_addrs = [a for a in addresses if a.startswith("addr1") or a.startswith("stake1")]
    cosmos_addrs  = [a for a in addresses if not a.startswith("0x") and not a.startswith("addr1") and not a.startswith("stake1")]
    # Re-encode every cosmos address to nolus prefix for Nolus scan
    _nolus_set = set()
    for a in cosmos_addrs:
        nolus_a = a if a.startswith("nolus1") else reencode_address(a, "nolus")
        if nolus_a:
            _nolus_set.add(nolus_a)
    nolus_addrs = list(_nolus_set)

    connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
    async with aiohttp.ClientSession(connector=connector, headers={"User-Agent": "CoinFolio/1.0"}) as session:
        tasks = (
            [scan_evm(session, a, nets) for a in evm_addrs] +
            [scan_cosmos(session, a, nets) for a in cosmos_addrs] +
            [scan_nolus(session, a) for a in nolus_addrs] +
            [scan_cardano(session, a) for a in cardano_addrs]
        )
        # Do not turn a large address list into an unbounded outbound request
        # burst.  The connector limit alone still leaves thousands of queued
        # coroutines and slow client requests.
        semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
        async def bounded(task):
            async with semaphore:
                return await task
        nested = await asyncio.gather(*(bounded(task) for task in tasks), return_exceptions=False)

    all_holdings = [h for sublist in nested for h in sublist]
    holdings = merge_holdings(all_holdings)
    holdings = inject_prices(holdings, prices)
    return holdings


# ── Background Loop: Prices ────────────────────────────────────────────────────

async def price_refresh_loop():
    """Refresh CoinGecko prices every PRICE_INTERVAL seconds."""
    logger.info("🦎 CoinGecko price refresh loop started")
    while True:
        t0 = time.monotonic()
        try:
            prices = await refresh_prices()
            elapsed = time.monotonic() - t0
            logger.info(f"💰 CoinGecko refresh done — {len(prices)} tokens in {elapsed:.1f}s · next in {PRICE_INTERVAL}s")
        except Exception as e:
            logger.error(f"❌ Price refresh error: {e}")
        await asyncio.sleep(PRICE_INTERVAL)


# ── Background Loop: Portfolio Cycle ──────────────────────────────────────────

async def portfolio_cycle_loop():
    """
    Scan all users within a PORTFOLIO_CYCLE window, evenly distributed.
    e.g. 6 users, 30-min cycle → one user every 5 minutes.
    """
    logger.info("📊 Portfolio cycle loop started")

    # Wait for prices to be available first
    await asyncio.sleep(15)

    while True:
        users = list_all_users()
        if not users:
            await asyncio.sleep(60)
            continue

        prices = load_prices()
        interval = PORTFOLIO_CYCLE / len(users)
        logger.info(f"🔭 Portfolio cycle start — {len(users)} users · 1 scan every {interval:.0f}s")

        for user in users:
            t0 = time.monotonic()
            try:
                aprs = load_aprs()
                holdings = await scan_user(user["addresses"], prices)
                total_usd = sum(h["usd_value"] for h in holdings)
                yearly_income_usd = calculate_yearly_income(holdings, aprs)
                await persist_portfolio(user["hash"], holdings, total_usd, yearly_income_usd)
                elapsed = time.monotonic() - t0
                logger.info(f"👤 {user['hash'][:8]} — ${total_usd:,.2f} · yearly ${yearly_income_usd:,.2f} · {len(holdings)} holdings · {elapsed:.1f}s")
            except Exception as e:
                logger.error(f"❌ Scan failed {user['hash'][:8]}: {e}")

            await asyncio.sleep(interval)
