"""Enrichment: convert raw API trades into the standard output format."""

import logging
from datetime import datetime, timezone
from typing import Any

from ingestor.client import fetch_market_data

logger = logging.getLogger(__name__)

# Cache market data to avoid redundant API calls within a cycle.
# Key: conditionId, Value: market data dict or None.
_market_cache: dict[str, dict[str, Any] | None] = {}


def clear_market_cache() -> None:
    """Clear the market data cache (call between cycles)."""
    _market_cache.clear()


def _get_market_data(condition_id: str) -> dict[str, Any] | None:
    """Fetch market data with per-cycle caching."""
    if condition_id not in _market_cache:
        _market_cache[condition_id] = fetch_market_data(condition_id)
    return _market_cache[condition_id]


def _compute_usdc_size(trade: dict[str, Any]) -> float:
    """Extract or compute the USDC size of a trade."""
    # The API may return usdcSize directly
    if "usdcSize" in trade and trade["usdcSize"] is not None:
        try:
            return float(trade["usdcSize"])
        except (ValueError, TypeError):
            pass
    # Fallback: size (tokens) * price
    try:
        return float(trade.get("size", 0)) * float(trade.get("price", 0))
    except (ValueError, TypeError):
        return 0.0


def enrich_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw API trade dict into the standardized enriched format.

    Args:
        trade: Raw trade dict from the Data API.

    Returns:
        Enriched trade dict matching the Bloc 2 input contract.
    """
    condition_id = trade.get("conditionId", "")

    # Fetch market context (cached per condition_id within cycle)
    market = _get_market_data(condition_id)

    market_probability = None
    market_volume_24h = None
    market_end_date = None

    if market:
        market_probability = market.get("probability")
        market_volume_24h = market.get("volume_24h")
        market_end_date = market.get("end_date")

    return {
        "proxy_wallet": trade.get("proxyWallet", ""),
        "condition_id": condition_id,
        "transaction_hash": trade.get("transactionHash", ""),
        "usdc_size": _compute_usdc_size(trade),
        "price": _safe_float(trade.get("price")),
        "side": trade.get("side", ""),
        "slug": trade.get("slug", ""),
        "title": trade.get("title", ""),
        "market_probability": market_probability,
        "market_volume_24h": market_volume_24h,
        "market_end_date": market_end_date,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def _safe_float(value: Any) -> float:
    """Convert a value to float, returning 0.0 on failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
