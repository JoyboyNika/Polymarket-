"""Market classification: crypto/indices vs standard.

Determines the market category based on keyword matching against the
market title and slug, then returns the appropriate alert threshold.

Forensic Carmin analysis (13-14 Feb 2026) showed that 98% of crypto
alerts were noise from directional 5-minute markets (BTC/ETH/SOL/XRP
Up or Down). A $10,000 threshold for crypto/indices vs $4,000 for
standard markets eliminates 82% of false positives while preserving
65% of volume coverage.
"""

from typing import Any

from scorer.config import (
    ALERT_THRESHOLD_CRYPTO,
    ALERT_THRESHOLD_STANDARD,
    CRYPTO_KEYWORDS,
)

# Category constants
CATEGORY_CRYPTO = "crypto"
CATEGORY_STANDARD = "standard"


def classify_market(trade: dict[str, Any]) -> str:
    """Classify a market as crypto/indices or standard.

    Matches against market title and slug (case-insensitive).

    Args:
        trade: Enriched trade dict with 'title' and 'slug' fields.

    Returns:
        "crypto" or "standard".
    """
    title = (trade.get("title") or "").lower()
    slug = (trade.get("slug") or "").lower()
    text = f"{title} {slug}"

    for keyword in CRYPTO_KEYWORDS:
        if keyword in text:
            return CATEGORY_CRYPTO

    return CATEGORY_STANDARD


def get_alert_threshold(trade: dict[str, Any]) -> int:
    """Return the USDC alert threshold for this trade's market category.

    Args:
        trade: Enriched trade dict.

    Returns:
        Alert threshold in USDC (4000 for standard, 10000 for crypto).
    """
    category = classify_market(trade)
    if category == CATEGORY_CRYPTO:
        return ALERT_THRESHOLD_CRYPTO
    return ALERT_THRESHOLD_STANDARD
