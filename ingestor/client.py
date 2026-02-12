"""Polymarket API client for trades and market data."""

import json
import logging
from typing import Any

import requests

from ingestor.config import (
    API_BASE_URL,
    API_PAGE_LIMIT,
    FILTER_AMOUNT_USDC,
    GAMMA_API_URL,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


def fetch_trades(
    filter_amount: int = FILTER_AMOUNT_USDC,
    limit: int = API_PAGE_LIMIT,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch trades from the Polymarket Data API.

    Args:
        filter_amount: Minimum USDC size to filter on.
        limit: Max trades per request (max 500).
        offset: Pagination offset.

    Returns:
        List of raw trade dicts from the API.

    Raises:
        requests.RequestException: On network or HTTP errors.
    """
    url = f"{API_BASE_URL}/trades"
    params = {
        "filterType": "CASH",
        "filterAmount": filter_amount,
        "limit": min(limit, API_PAGE_LIMIT),
        "offset": offset,
    }

    logger.debug("GET %s params=%s", url, params)
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    trades = resp.json()
    logger.info("Fetched %d trades (offset=%d)", len(trades), offset)
    return trades


def fetch_all_recent_trades(filter_amount: int = FILTER_AMOUNT_USDC) -> list[dict[str, Any]]:
    """Fetch all available recent trades by paginating through the API.

    Used at startup to seed the deduplication set. Fetches up to
    offset=1000 (API hard limit).

    Args:
        filter_amount: Minimum USDC size to filter on.

    Returns:
        List of all fetched trade dicts.
    """
    all_trades = []
    offset = 0
    max_offset = 1000  # Polymarket API hard limit

    while offset <= max_offset:
        batch = fetch_trades(filter_amount=filter_amount, offset=offset)
        if not batch:
            break
        all_trades.extend(batch)
        if len(batch) < API_PAGE_LIMIT:
            break
        offset += API_PAGE_LIMIT

    logger.info("Fetched %d total trades for dedup seeding", len(all_trades))
    return all_trades


def fetch_market_data(condition_id: str) -> dict[str, Any] | None:
    """Fetch market metadata from the Gamma API by condition ID.

    Args:
        condition_id: The market's conditionId (0x hex string).

    Returns:
        Market dict with parsed fields, or None if not found / error.
    """
    url = f"{GAMMA_API_URL}/markets"
    params = {"condition_ids": condition_id}

    logger.debug("GET %s params=%s", url, params)
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch market data for %s: %s", condition_id, e)
        return None

    markets = resp.json()
    if not markets:
        logger.warning("No market found for condition_id=%s", condition_id)
        return None

    market = markets[0]

    # outcomePrices is a JSON-encoded string: '["0.55","0.45"]'
    probability = None
    try:
        outcome_prices = json.loads(market.get("outcomePrices", "[]"))
        if outcome_prices:
            probability = float(outcome_prices[0])
    except (json.JSONDecodeError, ValueError, IndexError) as e:
        logger.warning("Failed to parse outcomePrices for %s: %s", condition_id, e)

    return {
        "probability": probability,
        "volume_24h": market.get("volumeNum"),
        "end_date": market.get("endDate"),
    }
