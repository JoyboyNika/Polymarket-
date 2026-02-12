"""Deduplication manager using a time-windowed in-memory set."""

import logging
import time

from ingestor.config import DEDUP_WINDOW_HOURS

logger = logging.getLogger(__name__)


class DedupTracker:
    """Tracks seen transaction hashes with automatic expiry.

    Each hash is stored with its insertion timestamp. Hashes older than
    the configured window are purged periodically.
    """

    def __init__(self, window_hours: int = DEDUP_WINDOW_HOURS):
        self._window_seconds = window_hours * 3600
        # {transaction_hash: timestamp_seen}
        self._seen: dict[str, float] = {}

    @property
    def size(self) -> int:
        return len(self._seen)

    def is_seen(self, tx_hash: str) -> bool:
        return tx_hash in self._seen

    def mark_seen(self, tx_hash: str) -> None:
        self._seen[tx_hash] = time.time()

    def seed(self, tx_hashes: list[str]) -> None:
        """Bulk-insert hashes (used at startup to reconstitute state).

        All seeded hashes get the current timestamp.
        """
        now = time.time()
        for h in tx_hashes:
            self._seen[h] = now
        logger.info("Seeded dedup tracker with %d hashes (total: %d)", len(tx_hashes), self.size)

    def purge_expired(self) -> int:
        """Remove hashes older than the dedup window.

        Returns:
            Number of hashes removed.
        """
        cutoff = time.time() - self._window_seconds
        expired = [h for h, ts in self._seen.items() if ts < cutoff]
        for h in expired:
            del self._seen[h]
        if expired:
            logger.info("Purged %d expired hashes (remaining: %d)", len(expired), self.size)
        return len(expired)
