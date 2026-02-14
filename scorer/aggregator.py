"""Funder-level trade aggregation for split-detection.

Tracks trades per (funding_source, market) within a rolling 24-hour window.
When the aggregated volume for a funder on a single market exceeds the
category threshold, generates an aggregated alert containing all contributing
wallets and transactions.

This defeats intentional trade splitting (e.g. $12,000 split into 4 x $3,000
via different wallets funded by the same source).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from scorer.config import AGGREGATION_WINDOW_HOURS
from scorer.market_classifier import classify_market, get_alert_threshold

logger = logging.getLogger(__name__)


@dataclass
class AggregatedTrade:
    """A single trade record within an aggregation bucket."""
    wallet: str
    usdc_size: float
    transaction_hash: str
    timestamp: float  # time.time() when ingested


@dataclass
class AggregationBucket:
    """Accumulates trades for one (funder, market) pair."""
    funder: str
    condition_id: str
    market_title: str
    market_category: str
    alert_threshold: int
    trades: list[AggregatedTrade] = field(default_factory=list)
    alerted: bool = False  # True once an aggregated alert was emitted

    @property
    def total_volume(self) -> float:
        return sum(t.usdc_size for t in self.trades)

    @property
    def wallet_count(self) -> int:
        return len({t.wallet for t in self.trades})

    @property
    def wallets(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in self.trades:
            if t.wallet not in seen:
                seen.add(t.wallet)
                out.append(t.wallet)
        return out

    @property
    def trade_count(self) -> int:
        return len(self.trades)


class AggregationTracker:
    """Rolling-window aggregation by (funding_source, condition_id).

    Usage::

        tracker = AggregationTracker()

        # After each trade is enriched + wallet profiled:
        alert = tracker.add_trade(trade, wallet_profile)
        if alert is not None:
            # alert is a dict ready for webhook / further scoring
            send_aggregated_alert(alert)
    """

    def __init__(self, window_hours: int = AGGREGATION_WINDOW_HOURS) -> None:
        self._window_seconds = window_hours * 3600
        # Key: (funder, condition_id) → AggregationBucket
        self._buckets: dict[tuple[str, str], AggregationBucket] = {}

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)

    def add_trade(
        self,
        trade: dict[str, Any],
        wallet_profile: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Record a trade and return an aggregated alert if threshold crossed.

        The trade must already be enriched (Bloc 1 output format).
        The wallet_profile must contain 'funding_source'.

        Args:
            trade: Enriched trade dict.
            wallet_profile: Wallet profile with funding_source.

        Returns:
            Aggregated alert dict if the threshold was just crossed,
            None otherwise.
        """
        funder = (wallet_profile.get("funding_source") or "").strip()
        if not funder or funder in ("non_disponible", "N/A", "inconnu"):
            return None

        condition_id = trade.get("condition_id", "")
        if not condition_id:
            return None

        key = (funder, condition_id)
        now = time.time()

        # Get or create bucket
        if key not in self._buckets:
            self._buckets[key] = AggregationBucket(
                funder=funder,
                condition_id=condition_id,
                market_title=trade.get("title", ""),
                market_category=classify_market(trade),
                alert_threshold=get_alert_threshold(trade),
            )

        bucket = self._buckets[key]

        # Add trade
        bucket.trades.append(AggregatedTrade(
            wallet=trade.get("proxy_wallet", ""),
            usdc_size=trade.get("usdc_size", 0) or 0,
            transaction_hash=trade.get("transaction_hash", ""),
            timestamp=now,
        ))

        # Purge expired trades from this bucket
        cutoff = now - self._window_seconds
        bucket.trades = [t for t in bucket.trades if t.timestamp >= cutoff]

        # Check if threshold crossed (only alert once per bucket)
        if not bucket.alerted and bucket.total_volume >= bucket.alert_threshold:
            bucket.alerted = True
            logger.info(
                "AGGREGATED ALERT: funder=%s market=%s volume=%.0f >= %d (%d wallets, %d trades)",
                funder[:30],
                bucket.market_title[:40],
                bucket.total_volume,
                bucket.alert_threshold,
                bucket.wallet_count,
                bucket.trade_count,
            )
            return self._build_alert(bucket)

        return None

    def purge_expired(self) -> None:
        """Remove buckets with no trades within the window."""
        now = time.time()
        cutoff = now - self._window_seconds
        expired_keys = []
        for key, bucket in self._buckets.items():
            bucket.trades = [t for t in bucket.trades if t.timestamp >= cutoff]
            if not bucket.trades:
                expired_keys.append(key)
        for key in expired_keys:
            del self._buckets[key]

    @staticmethod
    def _build_alert(bucket: AggregationBucket) -> dict[str, Any]:
        """Build a flat alert dict from an aggregation bucket."""
        return {
            "alert_type": "ALERTE AGRÉGÉE",
            "funder": bucket.funder,
            "condition_id": bucket.condition_id,
            "market_title": bucket.market_title,
            "market_category": bucket.market_category,
            "total_volume": round(bucket.total_volume, 2),
            "alert_threshold": bucket.alert_threshold,
            "wallet_count": bucket.wallet_count,
            "trade_count": bucket.trade_count,
            "wallets": ", ".join(bucket.wallets),
            "transactions": ", ".join(t.transaction_hash for t in bucket.trades),
        }
