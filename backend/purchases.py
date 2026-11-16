#!/usr/bin/env python3
"""
Purchase tracker — stores user's token buy history and calculates cost basis.
Storage: /data/purchases/{code_hash}.json
"""
import json
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("passivmos.purchases")

PURCHASES_DIR = Path(__file__).parent.parent / "data" / "purchases"
PURCHASES_DIR.mkdir(parents=True, exist_ok=True)

PRESET_FLAGS = [
    "Bought on Osmosis",
    "Bought on Kraken",
    "Bought on Coinbase",
    "Bought on Binance",
    "Staking Rewards",
    "Airdrop",
    "LP Exit",
    "OTC Trade",
    "DCA Bot",
    "Gift / Transfer",
]

DUST_THRESHOLD = 0.001  # ignore diffs smaller than this


def _path(code_hash: str) -> Path:
    return PURCHASES_DIR / f"{code_hash}.json"


def _load(code_hash: str) -> Dict:
    p = _path(code_hash)
    if not p.exists():
        return {"purchases": [], "custom_flags": []}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {"purchases": [], "custom_flags": []}


def _save(code_hash: str, data: Dict):
    p = _path(code_hash)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.rename(p)


def get_purchases(code_hash: str) -> Dict:
    return _load(code_hash)


def add_purchase(code_hash: str, token: str, amount: float, price_usd: float,
                 date: str, flag: str) -> Dict:
    data = _load(code_hash)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "token": token.upper().strip(),
        "amount": amount,
        "price_usd": price_usd,
        "date": date,
        "flag": flag,
    }
    data["purchases"].append(entry)
    _save(code_hash, data)
    return entry


def delete_purchase(code_hash: str, purchase_id: str) -> bool:
    data = _load(code_hash)
    before = len(data["purchases"])
    data["purchases"] = [p for p in data["purchases"] if p["id"] != purchase_id]
    if len(data["purchases"]) == before:
        return False
    _save(code_hash, data)
    return True


def add_custom_flag(code_hash: str, flag: str) -> List[str]:
    data = _load(code_hash)
    flag = flag.strip()
    if flag and flag not in data["custom_flags"] and flag not in PRESET_FLAGS:
        data["custom_flags"].append(flag)
        _save(code_hash, data)
    return data["custom_flags"]


def summarize(purchases: List[Dict], on_chain_balances: Dict[str, float] = None) -> Dict:
    """
    Returns per-token summary: total_tokens, avg_price, total_cost.
    Also returns unrecorded diff if on_chain_balances provided.
    """
    by_token: Dict[str, Dict] = {}
    for p in purchases:
        tok = p["token"]
        if tok not in by_token:
            by_token[tok] = {"total_amount": 0.0, "total_cost": 0.0, "entries": 0}
        by_token[tok]["total_amount"] += p["amount"]
        by_token[tok]["total_cost"] += p["amount"] * p["price_usd"]
        by_token[tok]["entries"] += 1

    summary = {}
    for tok, s in by_token.items():
        avg = s["total_cost"] / s["total_amount"] if s["total_amount"] > 0 else 0.0
        unrecorded = 0.0
        if on_chain_balances and tok in on_chain_balances:
            diff = on_chain_balances[tok] - s["total_amount"]
            if diff > DUST_THRESHOLD:
                unrecorded = diff
        summary[tok] = {
            "total_amount": round(s["total_amount"], 6),
            "total_cost_usd": round(s["total_cost"], 4),
            "avg_price_usd": round(avg, 6),
            "entries": s["entries"],
            "unrecorded": round(unrecorded, 6),
        }

    # Surface tokens on-chain with zero purchases
    if on_chain_balances:
        for tok, bal in on_chain_balances.items():
            if tok not in summary and bal > DUST_THRESHOLD:
                summary[tok] = {
                    "total_amount": 0.0,
                    "total_cost_usd": 0.0,
                    "avg_price_usd": 0.0,
                    "entries": 0,
                    "unrecorded": round(bal, 6),
                }

    return summary
