#!/usr/bin/env python3
"""Bloc 1 — Polymarket Trade Ingestor.

Polls the Polymarket Data API for large trades, deduplicates them,
enriches each with market context, and passes them to Bloc 2 (Scoreur).

Usage:
    # Dry run: one cycle, print results, exit
    python -m ingestor.main --dry-run

    # Continuous mode: poll every POLL_INTERVAL_SECONDS
    python -m ingestor.main
"""

import argparse
import json
import logging
import sys
import time
from typing import Any

from ingestor.client import fetch_all_recent_trades, fetch_trades
from ingestor.config import FILTER_AMOUNT_USDC, POLL_INTERVAL_SECONDS
from ingestor.dedup import DedupTracker
from ingestor.enrichment import clear_market_cache, enrich_trade

logger = logging.getLogger("ingestor")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def seed_dedup(tracker: DedupTracker) -> None:
    """Reconstitute the dedup set from recent trades at startup."""
    logger.info("Seeding dedup tracker from recent trades...")
    try:
        trades = fetch_all_recent_trades()
        hashes = [t["transactionHash"] for t in trades if "transactionHash" in t]
        tracker.seed(hashes)
    except Exception as e:
        logger.error("Failed to seed dedup tracker: %s", e)
        logger.info("Starting with empty dedup set — some duplicates may occur")


def run_cycle(tracker: DedupTracker) -> list[dict[str, Any]]:
    """Execute one ingest cycle: poll, dedup, enrich.

    Args:
        tracker: The deduplication tracker.

    Returns:
        List of enriched trade dicts (new trades only).
    """
    # 1. Poll trades
    logger.info("Polling trades (filterAmount=%d USDC)...", FILTER_AMOUNT_USDC)
    try:
        raw_trades = fetch_trades()
    except Exception as e:
        logger.error("API call failed: %s — will retry next cycle", e)
        return []

    logger.info("Received %d trades from API", len(raw_trades))

    # 2. Deduplicate
    new_trades = []
    for trade in raw_trades:
        tx_hash = trade.get("transactionHash")
        if not tx_hash:
            logger.warning("Trade missing transactionHash, skipping: %s", trade)
            continue
        if tracker.is_seen(tx_hash):
            continue
        tracker.mark_seen(tx_hash)
        new_trades.append(trade)

    logger.info(
        "After dedup: %d new trades (%d already seen)",
        len(new_trades),
        len(raw_trades) - len(new_trades),
    )

    if not new_trades:
        return []

    # 3. Enrich with market context
    clear_market_cache()
    enriched = []
    for trade in new_trades:
        try:
            enriched_trade = enrich_trade(trade)
            enriched.append(enriched_trade)
        except Exception as e:
            logger.error("Failed to enrich trade %s: %s", trade.get("transactionHash"), e)

    logger.info("Enriched %d trades", len(enriched))

    # 4. Periodic cleanup
    tracker.purge_expired()

    return enriched


def process_trades(trades: list[dict[str, Any]]) -> None:
    """Pass enriched trades to Bloc 2 (Scoreur).

    Currently a placeholder — Bloc 2 will consume this list directly.

    Args:
        trades: List of enriched trade dicts.
    """
    # TODO: Replace with Bloc 2 scoring call when implemented
    logger.info("Passing %d trades to Bloc 2 (not yet implemented)", len(trades))


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket Trade Ingestor (Bloc 1)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a single cycle, print results as JSON, and exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    logger.info("Polymarket Ingestor starting")
    logger.info(
        "Config: poll=%ds, filter=%d USDC",
        POLL_INTERVAL_SECONDS,
        FILTER_AMOUNT_USDC,
    )

    tracker = DedupTracker()

    if args.dry_run:
        # Dry run: single cycle, no dedup seeding (shows all current trades)
        logger.info("DRY RUN — single cycle, no dedup seeding")
        enriched = run_cycle(tracker)
        print(json.dumps(enriched, indent=2, ensure_ascii=False))
        logger.info("Dry run complete: %d trades", len(enriched))
        return

    # Production mode: seed dedup then loop
    seed_dedup(tracker)

    while True:
        try:
            enriched = run_cycle(tracker)
            if enriched:
                process_trades(enriched)
        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down")
            sys.exit(0)
        except Exception as e:
            logger.error("Unexpected error in cycle: %s", e, exc_info=True)

        logger.info(
            "Sleeping %ds until next cycle (dedup set: %d hashes)",
            POLL_INTERVAL_SECONDS,
            tracker.size,
        )
        try:
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down")
            sys.exit(0)


if __name__ == "__main__":
    main()
