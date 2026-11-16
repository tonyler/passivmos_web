#!/usr/bin/env python3
"""
EVM wallet analyzer for PassivMOS.
Loads chain/token config from passivmos2/networks.json so it stays in sync.
Scans all configured EVM chains for native + ERC-20 balances via public RPCs.
"""
import asyncio
import aiohttp
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

# ── Load networks config ──────────────────────────────────────────────────────

_NETWORKS_PATH = Path(__file__).parent.parent / "passivmos2" / "networks.json"

def _load_networks() -> dict:
    try:
        return json.loads(_NETWORKS_PATH.read_text())
    except Exception as e:
        logger.error(f"Failed to load networks.json: {e}")
        return {"evm_chains": [], "erc20_tokens": {}}

_NETWORKS = _load_networks()

# {chain_id: {"name", "rpc", "native_symbol", "native_decimals", "coingecko_id"}}
EVM_CHAINS: Dict[int, Dict] = {
    c["id"]: c for c in _NETWORKS.get("evm_chains", [])
}

# {chain_id: [{"address", "symbol", "decimals", "coingecko_id"}, ...]}
ERC20_BY_CHAIN: Dict[int, List[Dict]] = {
    int(chain_id): tokens
    for chain_id, tokens in _NETWORKS.get("erc20_tokens", {}).items()
}

# Known staking APR sources {symbol: (fetch_fn_name, fallback_apr)}
# ponytail: static fallbacks for tokens without a free live APR API
STAKING_APRS: Dict[str, float] = {
    "stETH":  3.5,   # overridden by Lido API
    "wstETH": 3.5,   # overridden by Lido API
    "cbETH":  3.5,   # Coinbase ETH staking, roughly same as Lido
    "rETH":   3.5,   # overridden by Rocket Pool API
    "AAVE":   4.5,   # Safety Module staking
    "CAKE":  40.0,   # PancakeSwap auto-compound pool (rough average)
    "AERO":  10.0,   # Aerodrome BASE (varies widely)
}

DUST_THRESHOLD = 0.0001

# Additional fallback RPCs per chain (public, no API key)
_FALLBACK_RPCS: Dict[int, List[str]] = {
    1:     ["https://eth.llamarpc.com", "https://cloudflare-eth.com"],
    56:    ["https://bsc-rpc.publicnode.com", "https://bsc.drpc.org"],
    137:   ["https://polygon-rpc.com", "https://polygon.drpc.org"],
    42161: ["https://arb1.arbitrum.io/rpc", "https://arbitrum.drpc.org"],
    8453:  ["https://mainnet.base.org", "https://base.drpc.org"],
    130:   [],
}


@dataclass
class EVMTokenBalance:
    symbol: str
    balance: float
    chain_id: int
    chain_name: str
    contract: Optional[str] = None   # None = native token


# ── RPC helpers ───────────────────────────────────────────────────────────────

def _rpc_endpoints(chain_id: int) -> List[str]:
    primary = EVM_CHAINS.get(chain_id, {}).get("rpc", "")
    fallbacks = _FALLBACK_RPCS.get(chain_id, [])
    return [primary] + [f for f in fallbacks if f != primary]


async def _rpc(session: aiohttp.ClientSession, endpoint: str, method: str, params: list):
    try:
        async with session.post(
            endpoint,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as r:
            d = await r.json(content_type=None)
            return d.get("result")
    except Exception as e:
        logger.debug(f"RPC {method} @ {endpoint}: {e}")
        return None


async def _eth_balance(session: aiohttp.ClientSession, chain_id: int, address: str) -> float:
    for ep in _rpc_endpoints(chain_id):
        res = await _rpc(session, ep, "eth_getBalance", [address, "latest"])
        if res:
            try:
                decimals = EVM_CHAINS.get(chain_id, {}).get("native_decimals", 18)
                return int(res, 16) / (10 ** decimals)
            except (ValueError, TypeError):
                continue
    return 0.0


async def _erc20_balance(
    session: aiohttp.ClientSession,
    chain_id: int,
    address: str,
    contract: str,
    decimals: int,
) -> float:
    # balanceOf(address): selector 0x70a08231, address zero-padded to 32 bytes
    data = "0x70a08231" + address[2:].lower().zfill(64)
    for ep in _rpc_endpoints(chain_id):
        res = await _rpc(session, ep, "eth_call", [{"to": contract, "data": data}, "latest"])
        if res and res not in ("0x", "0x0", "0x" + "0" * 64):
            try:
                return int(res, 16) / (10 ** decimals)
            except (ValueError, TypeError):
                continue
    return 0.0


# ── Per-chain scan ────────────────────────────────────────────────────────────

async def _scan_chain(
    session: aiohttp.ClientSession,
    chain_id: int,
    address: str,
) -> List[EVMTokenBalance]:
    chain = EVM_CHAINS.get(chain_id)
    if not chain:
        return []

    chain_name = chain["name"]
    tokens = ERC20_BY_CHAIN.get(chain_id, [])

    # Native + all ERC-20s in parallel
    tasks = [_eth_balance(session, chain_id, address)] + [
        _erc20_balance(session, chain_id, address, t["address"], t["decimals"])
        for t in tokens
    ]
    symbols  = [chain["native_symbol"]] + [t["symbol"] for t in tokens]
    contracts = [None] + [t["address"] for t in tokens]

    balances = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for sym, bal, contract in zip(symbols, balances, contracts):
        if isinstance(bal, Exception):
            continue
        if bal > DUST_THRESHOLD:
            results.append(EVMTokenBalance(
                symbol=sym,
                balance=bal,
                chain_id=chain_id,
                chain_name=chain_name,
                contract=contract,
            ))
    return results


async def analyze_evm_address(address: str) -> List[EVMTokenBalance]:
    """
    Scan address across all configured EVM chains in parallel.
    Returns non-dust balances.
    """
    if not address.startswith("0x") or len(address) != 42:
        return []

    async with aiohttp.ClientSession() as session:
        chain_scans = await asyncio.gather(*[
            _scan_chain(session, chain_id, address)
            for chain_id in EVM_CHAINS
        ], return_exceptions=True)

    results = []
    for scan in chain_scans:
        if isinstance(scan, Exception):
            logger.warning(f"Chain scan error: {scan}")
            continue
        results.extend(scan)
    return results


# ── Prices ────────────────────────────────────────────────────────────────────

# DeFiLlama chain name mapping (free API, no key, contract-address based)
_LLAMA_CHAIN: Dict[int, str] = {
    1:     "ethereum",
    56:    "bsc",
    137:   "polygon",
    42161: "arbitrum",
    8453:  "base",
    130:   "unichain",
}


async def get_evm_prices() -> Dict[str, float]:
    """
    Fetch EVM token prices from DeFiLlama (free, no API key).
    Uses contract addresses directly — no coingecko_id mapping needed.
    Falls back to CoinGecko for native tokens (ETH, BNB, POL…) which have no contract.
    """
    # Build two maps:
    #   llama_id → symbol  (for ERC-20s, keyed by chain:contract)
    #   cg_id    → symbol  (for native tokens, keyed by coingecko_id)
    llama_to_sym: Dict[str, str] = {}
    cg_to_sym:    Dict[str, str] = {}

    for chain in EVM_CHAINS.values():
        cg_id = chain.get("coingecko_id", "")
        if cg_id:
            cg_to_sym[cg_id] = chain["native_symbol"]

    for chain_id, tokens in ERC20_BY_CHAIN.items():
        llama_chain = _LLAMA_CHAIN.get(chain_id)
        if not llama_chain:
            continue
        for t in tokens:
            llama_id = f"{llama_chain}:{t['address'].lower()}"
            llama_to_sym[llama_id] = t["symbol"]

    prices: Dict[str, float] = {}

    # 1. ERC-20 prices via DeFiLlama (contract address)
    if llama_to_sym:
        # DeFiLlama caps at ~100 coins per request; split if needed
        keys = list(llama_to_sym.keys())
        chunks = [keys[i:i+100] for i in range(0, len(keys), 100)]
        try:
            async with aiohttp.ClientSession() as session:
                for chunk in chunks:
                    url = "https://coins.llama.fi/prices/current/" + ",".join(chunk)
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                        data = await r.json(content_type=None)
                    for llama_id, sym in llama_to_sym.items():
                        if llama_id in chunk:
                            p = data.get("coins", {}).get(llama_id, {}).get("price", 0.0)
                            if p > 0:
                                prices[sym] = p  # last chain wins if same symbol on multiple chains
        except Exception as e:
            logger.error(f"DeFiLlama price fetch failed: {e}")

    # 2. Native token prices via CoinGecko (no contract address available)
    if cg_to_sym:
        ids_param = ",".join(cg_to_sym.keys())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_param}&vs_currencies=usd"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    data = await r.json(content_type=None)
            for cg_id, sym in cg_to_sym.items():
                p = data.get(cg_id, {}).get("usd", 0.0)
                if p > 0:
                    prices[sym] = p
        except Exception as e:
            logger.error(f"CoinGecko native price fetch failed: {e}")

    return prices


# ── APRs ──────────────────────────────────────────────────────────────────────

async def get_evm_aprs() -> Dict[str, float]:
    """Fetch live APRs where available; fall back to STAKING_APRS table."""
    aprs: Dict[str, float] = dict(STAKING_APRS)  # start with defaults

    async with aiohttp.ClientSession() as session:
        # Lido stETH + wstETH
        try:
            async with session.get(
                "https://eth-api.lido.fi/v1/protocol/steth/apr/sma",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                d = await r.json(content_type=None)
                lido_apr = float(d.get("data", {}).get("smaApr", 3.5))
                aprs["stETH"]  = lido_apr
                aprs["wstETH"] = lido_apr
                aprs["cbETH"]  = lido_apr  # close enough
        except Exception as e:
            logger.warning(f"Lido APR fetch failed: {e}")

        # Rocket Pool rETH
        try:
            async with session.get(
                "https://api.rocketpool.net/api/eth/apy",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                d = await r.json(content_type=None)
                aprs["rETH"] = float(d.get("yearlyAPR", d.get("apy", 3.5)))
        except Exception as e:
            logger.warning(f"Rocket Pool APR fetch failed: {e}")

    return aprs
