"""Wallet profiler: fetch wallet data from Polymarket Data API + Alchemy.

Produces a standardized wallet_profile dict consumed by scorer.score_pass2().
Gracefully degrades when APIs are unavailable.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from scorer.config import (
    ALCHEMY_API_KEY,
    ALCHEMY_NETWORK,
    API_BASE_URL,
    KNOWN_MIXERS,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


def build_wallet_profile(proxy_wallet: str) -> dict[str, Any]:
    """Build a complete wallet profile by combining multiple data sources.

    Args:
        proxy_wallet: The wallet address (0x...) to profile.

    Returns:
        Standardized wallet profile dict:
        {
            "age_days": int | None,
            "tx_count": int | None,
            "markets_count": int | None,
            "win_loss": str | None,
            "funding_source": str | None,
            "first_polymarket_trade": str | None,
        }
    """
    profile: dict[str, Any] = {
        "age_days": None,
        "tx_count": None,
        "markets_count": None,
        "win_loss": None,
        "funding_source": None,
        "first_polymarket_trade": None,
    }

    # Source 1: Polymarket Data API (trade history)
    poly_data = _fetch_polymarket_activity(proxy_wallet)
    if poly_data is not None:
        profile["markets_count"] = poly_data.get("markets_count")
        profile["win_loss"] = poly_data.get("win_loss")
        profile["first_polymarket_trade"] = poly_data.get("first_trade_date")

    # Source 2: Alchemy (on-chain data)
    if ALCHEMY_API_KEY:
        onchain = _fetch_onchain_data(proxy_wallet)
        if onchain is not None:
            profile["age_days"] = onchain.get("age_days")
            profile["tx_count"] = onchain.get("tx_count")
            profile["funding_source"] = onchain.get("funding_source")
    else:
        logger.debug("ALCHEMY_API_KEY not set — skipping on-chain profiling")

    return profile


# ── Polymarket Data API ──────────────────────────────────────


def _fetch_polymarket_activity(wallet: str) -> dict[str, Any] | None:
    """Fetch trading history from the Polymarket Data API.

    Uses GET /activity?user={wallet} to get trade history.

    Returns:
        Dict with markets_count, win_loss, first_trade_date, or None on error.
    """
    url = f"{API_BASE_URL}/activity"
    params = {"user": wallet, "limit": 500}

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch Polymarket activity for %s: %s", wallet, e)
        return None

    activities = resp.json()
    if not activities:
        # No activity = first-time user
        return {
            "markets_count": 0,
            "win_loss": None,
            "first_trade_date": None,
        }

    # Count unique markets (by conditionId or slug)
    markets = set()
    wins = 0
    losses = 0
    first_trade_date = None

    for activity in activities:
        # Track unique markets
        slug = activity.get("slug") or activity.get("conditionId", "")
        if slug:
            markets.add(slug)

        # Try to determine W/L from resolved trades
        # The activity endpoint may contain "REDEEM" type events
        activity_type = (activity.get("type") or "").upper()
        if activity_type in ("REDEEM", "CLAIM"):
            # Redemption = win
            wins += 1
        elif activity_type == "LOSS":
            losses += 1

        # Track earliest trade timestamp
        ts = activity.get("timestamp")
        if ts is not None:
            try:
                ts_val = int(ts) if not isinstance(ts, int) else ts
                if first_trade_date is None or ts_val < first_trade_date:
                    first_trade_date = ts_val
            except (ValueError, TypeError):
                pass

    win_loss = None
    if wins > 0 or losses > 0:
        win_loss = f"{wins}W/{losses}L"

    first_date_str = None
    if first_trade_date is not None:
        try:
            first_date_str = datetime.fromtimestamp(
                first_trade_date, tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError):
            pass

    return {
        "markets_count": len(markets),
        "win_loss": win_loss,
        "first_trade_date": first_date_str,
    }


# ── Alchemy (on-chain) ──────────────────────────────────────


def _alchemy_rpc_url() -> str:
    return f"https://{ALCHEMY_NETWORK}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"


def _alchemy_json_rpc(method: str, params: list) -> Any:
    """Make a JSON-RPC call to Alchemy.

    Returns:
        The 'result' field from the response, or None on error.
    """
    url = _alchemy_rpc_url()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("Alchemy RPC error: %s", data["error"])
            return None
        return data.get("result")
    except requests.RequestException as e:
        logger.warning("Alchemy RPC failed (%s): %s", method, e)
        return None


def _fetch_onchain_data(wallet: str) -> dict[str, Any] | None:
    """Fetch on-chain wallet data via Alchemy.

    Gets:
    - Transaction count (eth_getTransactionCount)
    - Wallet age via asset transfers (alchemy_getAssetTransfers)
    - Funding source (most recent large inbound transfer)

    Returns:
        Dict with age_days, tx_count, funding_source, or None on total failure.
    """
    result: dict[str, Any] = {
        "age_days": None,
        "tx_count": None,
        "funding_source": None,
    }

    # 1. Transaction count
    tx_count_hex = _alchemy_json_rpc("eth_getTransactionCount", [wallet, "latest"])
    if tx_count_hex is not None:
        try:
            result["tx_count"] = int(tx_count_hex, 16)
        except (ValueError, TypeError):
            pass

    # 2. First inbound transfer (wallet age) + funding source
    transfers = _fetch_inbound_transfers(wallet)
    if transfers:
        # Earliest transfer = wallet creation proxy
        earliest = transfers[-1]  # Transfers are returned newest-first
        try:
            block_num_hex = earliest.get("blockNum", "0x0")
            block_ts = _get_block_timestamp(block_num_hex)
            if block_ts is not None:
                age_seconds = datetime.now(timezone.utc).timestamp() - block_ts
                result["age_days"] = max(0, int(age_seconds / 86400))
        except (ValueError, TypeError):
            pass

        # Most recent large transfer = funding source
        latest = transfers[0]
        from_addr = (latest.get("from") or "").lower()
        value = latest.get("value") or 0

        if from_addr in KNOWN_MIXERS:
            result["funding_source"] = f"mixer/tornado ({from_addr[:10]}...)"
        elif value:
            result["funding_source"] = f"transfer from {from_addr[:10]}... ({value})"
        else:
            result["funding_source"] = f"transfer from {from_addr[:10]}..."

    return result


def _fetch_inbound_transfers(wallet: str) -> list[dict[str, Any]]:
    """Fetch inbound asset transfers to the wallet via Alchemy.

    Returns:
        List of transfer objects (newest first), or empty list on error.
    """
    result = _alchemy_json_rpc(
        "alchemy_getAssetTransfers",
        [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "toAddress": wallet,
                "category": ["external", "erc20"],
                "order": "desc",
                "maxCount": "0x14",  # 20 transfers
                "withMetadata": True,
            }
        ],
    )
    if result and "transfers" in result:
        return result["transfers"]
    return []


def _get_block_timestamp(block_num_hex: str) -> float | None:
    """Get the timestamp of a block by its hex number.

    Returns:
        Unix timestamp as float, or None on error.
    """
    block = _alchemy_json_rpc("eth_getBlockByNumber", [block_num_hex, False])
    if block and "timestamp" in block:
        try:
            return float(int(block["timestamp"], 16))
        except (ValueError, TypeError):
            pass
    return None
