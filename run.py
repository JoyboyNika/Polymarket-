#!/usr/bin/env python3
"""Carmin — Polymarket Insider Detection Bot.

Unified entry point that runs the full pipeline:
    Bloc 1 (Ingesteur) → Bloc 2 (Scoreur) → Bloc 3 (webhook Make)

Usage:
    python run.py                 # Production: infinite polling loop
    python run.py --dry-run       # One cycle, print scoring results, no webhook
    python run.py --test-webhook  # Send hardcoded Maduro payload to Make webhook
    python run.py -v              # Verbose (debug) logging
"""

import argparse
import json
import logging
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from ingestor.client import fetch_all_recent_trades, fetch_trades
from ingestor.config import FILTER_AMOUNT_USDC, POLL_INTERVAL_SECONDS
from ingestor.dedup import DedupTracker
from ingestor.enrichment import clear_market_cache, enrich_trade
from scorer.aggregator import AggregationTracker
from scorer.side_resolver import clear_clob_cache
from scorer.config import (
    ALERT_THRESHOLD_CRYPTO,
    ALERT_THRESHOLD_STANDARD,
    MAKE_WEBHOOK_URL,
    PASS1_THRESHOLD,
    PASS2_THRESHOLD,
)
from scorer.main import process_enriched_trades
from scorer.market_classifier import classify_market, get_alert_threshold
from scorer.scoring import score_pass1, score_trade
from scorer.webhook import build_flat_payload, send_webhook

logger = logging.getLogger("carmin")


# ── Maduro test payload (shared between tests) ──────────────

MADURO_TRADE = {
    "proxy_wallet": "0xTEST_MADURO_WALLET",
    "condition_id": "test-maduro-condition-id",
    "transaction_hash": "test-tx-hash-0x1234",
    "usdc_size": 32000.0,
    "price": 0.07,
    "side": "BUY",
    "slug": "will-maduro-leave-office-before-jan-31",
    "title": "Will Maduro leave office before Jan 31?",
    "market_probability": 0.055,
    "market_volume_24h": 85000.0,
    "market_end_date": "2025-01-31T00:00:00Z",
    "ingested_at": "2025-01-15T12:00:00Z",
}

MADURO_WALLET_PROFILE = {
    "age_days": 3,
    "tx_count": 4,
    "markets_count": 1,
    "win_loss": None,
    "funding_source": "transfer from 0xCoinbase... (35000 USDC)",
    "first_polymarket_trade": None,
}


# ── Modes ────────────────────────────────────────────────────


def mode_test_webhook() -> None:
    """Send the Maduro test payload to the Make webhook."""
    print("=" * 60)
    print("TEST WEBHOOK — Sending Maduro payload to Make")
    print("=" * 60)
    print()

    if not MAKE_WEBHOOK_URL:
        print("ERROR: MAKE_WEBHOOK_URL is not set in .env")
        print("Set it before running --test-webhook")
        sys.exit(1)

    # Build full scored payload (flat, null-safe format for Make.com)
    result = score_trade(MADURO_TRADE, MADURO_WALLET_PROFILE)
    payload = build_flat_payload(MADURO_TRADE, result, MADURO_WALLET_PROFILE)

    print(f"Payload score: {result.score_total} pts (P1: {result.score_pass1}, P2: {result.score_pass2})")
    print(f"Flags: {result.flags_triggered}")
    print(f"Webhook URL: {MAKE_WEBHOOK_URL[:50]}...")
    print()
    print("Payload (flat format):")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print()
    print("Sending...")

    success = send_webhook(payload)

    if success:
        print()
        print("Webhook sent successfully!")
        print("Check your Notion DB for the new Maduro entry.")
        print("Expected: title, score=19, montant=32000, fiche Haiku, verdict=Non traite")
    else:
        print()
        print("Webhook FAILED — check logs above for details.")
        print("Payload saved to local fallback (data/failed_webhooks/).")
        sys.exit(1)


def mode_dry_run() -> None:
    """Run one ingest cycle with scoring, print results, no webhook."""
    print("=" * 60)
    print("DRY RUN — One cycle, live data, no side effects")
    print("=" * 60)
    print()

    # 1. Fetch trades
    logger.info("Polling trades (filterAmount=%d USDC)...", FILTER_AMOUNT_USDC)
    try:
        raw_trades = fetch_trades()
    except Exception as e:
        print(f"ERROR: API call failed: {e}")
        sys.exit(1)

    print(f"Fetched {len(raw_trades)} trades from Polymarket API")
    print()

    if not raw_trades:
        print("No trades found. Try lowering FILTER_AMOUNT_USDC.")
        return

    # 2. Enrich
    clear_market_cache()
    clear_clob_cache()
    enriched = []
    for trade in raw_trades:
        try:
            enriched.append(enrich_trade(trade))
        except Exception as e:
            logger.warning("Failed to enrich trade: %s", e)

    print(f"Enriched {len(enriched)} trades with market context")
    print()

    # 3. Classify and filter by category threshold
    crypto_count = 0
    standard_count = 0
    filtered_by_threshold = 0
    above_threshold = []
    for trade in enriched:
        category = classify_market(trade)
        threshold = get_alert_threshold(trade)
        trade["_market_category"] = category
        trade["_alert_threshold"] = threshold
        usdc_size = trade.get("usdc_size") or 0
        if category == "crypto":
            crypto_count += 1
        else:
            standard_count += 1
        if usdc_size >= threshold:
            above_threshold.append(trade)
        else:
            filtered_by_threshold += 1

    print(f"Category breakdown: {crypto_count} crypto/indices, {standard_count} standard")
    print(f"Threshold filter: {len(above_threshold)} above threshold, {filtered_by_threshold} filtered out")
    print(f"  (crypto >= ${ALERT_THRESHOLD_CRYPTO:,}, standard >= ${ALERT_THRESHOLD_STANDARD:,})")
    print()

    # 4. Score Pass 1 (no wallet profiling, no webhook)
    pass1_passed = []
    for trade in above_threshold:
        result = score_pass1(trade)
        trade["_score_pass1"] = result.score_pass1
        trade["_flags_pass1"] = result.flags_triggered
        if result.score_pass1 >= PASS1_THRESHOLD:
            pass1_passed.append(trade)

    print(f"Pass 1 results: {len(pass1_passed)}/{len(above_threshold)} trades >= {PASS1_THRESHOLD} pts")
    print()

    # 5. Show details
    if pass1_passed:
        print("Trades passing Pass 1:")
        print("-" * 60)
        for t in pass1_passed:
            print(f"  {t['title'][:50]}")
            print(f"    Size: {t['usdc_size']:.0f} USDC | Price: {t['price']:.2f} | Side: {t['side']}")
            prob = t.get('market_probability')
            prob_str = f"{prob:.1%}" if prob is not None else "N/A"
            vol = t.get('market_volume_24h')
            vol_str = f"{vol:,.0f}" if vol is not None else "N/A"
            print(f"    Market prob: {prob_str} | Volume 24h: {vol_str} USDC")
            print(f"    Category: {t['_market_category']} (threshold: ${t['_alert_threshold']:,})")
            print(f"    Pass 1 score: {t['_score_pass1']} pts | Flags: {t['_flags_pass1']}")
            print(f"    Wallet: {t['proxy_wallet'][:16]}...")
            print()
    else:
        print("No trades passed Pass 1 threshold.")
        print("(This is normal if all recent trades are from established whales)")
        print()

    # 6. Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Trades fetched:       {len(raw_trades)}")
    print(f"  Trades enriched:      {len(enriched)}")
    print(f"  Crypto/indices:       {crypto_count} (threshold: ${ALERT_THRESHOLD_CRYPTO:,})")
    print(f"  Standard:             {standard_count} (threshold: ${ALERT_THRESHOLD_STANDARD:,})")
    print(f"  Filtered (< thresh):  {filtered_by_threshold}")
    print(f"  Above threshold:      {len(above_threshold)}")
    print(f"  Pass 1 (>= {PASS1_THRESHOLD} pts):    {len(pass1_passed)}")
    print(f"  Webhook calls:        0 (dry run)")
    print()
    print("In production mode, trades passing Pass 1 would trigger")
    print("wallet profiling (Pass 2) and potential webhook alerts.")

    # 6. Full JSON for the first 5 enriched trades (for debugging)
    print()
    print("=" * 60)
    print(f"RAW DATA (first {min(5, len(enriched))} enriched trades)")
    print("=" * 60)
    for t in enriched[:5]:
        # Remove internal scoring fields for clean output
        clean = {k: v for k, v in t.items() if not k.startswith("_")}
        print(json.dumps(clean, indent=2, ensure_ascii=False))
        print()


def mode_production() -> None:
    """Run the full pipeline in an infinite polling loop."""
    logger.info("Carmin starting in PRODUCTION mode")
    logger.info(
        "Config: poll=%ds, filter=%d USDC, P1>=%d, P2>=%d",
        POLL_INTERVAL_SECONDS,
        FILTER_AMOUNT_USDC,
        PASS1_THRESHOLD,
        PASS2_THRESHOLD,
    )
    logger.info(
        "Alert thresholds: standard=$%d, crypto=$%d",
        ALERT_THRESHOLD_STANDARD,
        ALERT_THRESHOLD_CRYPTO,
    )
    logger.info("Webhook: %s", MAKE_WEBHOOK_URL[:50] + "..." if MAKE_WEBHOOK_URL else "NOT SET")

    # Seed dedup
    tracker = DedupTracker()
    logger.info("Seeding dedup tracker from recent trades...")
    try:
        trades = fetch_all_recent_trades()
        hashes = [t["transactionHash"] for t in trades if "transactionHash" in t]
        tracker.seed(hashes)
    except Exception as e:
        logger.error("Failed to seed dedup tracker: %s", e)
        logger.info("Starting with empty dedup set")

    # Aggregation tracker (persists across cycles within the same run)
    agg_tracker = AggregationTracker()

    # Main loop
    while True:
        try:
            # Bloc 1: poll + dedup + enrich
            logger.info("Polling trades (filterAmount=%d USDC)...", FILTER_AMOUNT_USDC)
            try:
                raw_trades = fetch_trades()
            except Exception as e:
                logger.error("API call failed: %s — will retry next cycle", e)
                raw_trades = []

            # Dedup
            new_trades = []
            for trade in raw_trades:
                tx_hash = trade.get("transactionHash")
                if not tx_hash:
                    continue
                if tracker.is_seen(tx_hash):
                    continue
                tracker.mark_seen(tx_hash)
                new_trades.append(trade)

            logger.info(
                "Received %d trades, %d new after dedup",
                len(raw_trades),
                len(new_trades),
            )

            if new_trades:
                # Enrich
                clear_market_cache()
                clear_clob_cache()
                enriched = []
                for trade in new_trades:
                    try:
                        enriched.append(enrich_trade(trade))
                    except Exception as e:
                        logger.error("Failed to enrich trade: %s", e)

                # Bloc 2: score + profile + webhook (with aggregation)
                if enriched:
                    logger.info("Passing %d trades to Bloc 2", len(enriched))
                    process_enriched_trades(enriched, aggregation_tracker=agg_tracker)

            # Cleanup
            tracker.purge_expired()
            agg_tracker.purge_expired()

        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down")
            sys.exit(0)
        except Exception as e:
            logger.error("Unexpected error in cycle: %s", e, exc_info=True)

        logger.info(
            "Sleeping %ds (dedup set: %d hashes, agg buckets: %d)",
            POLL_INTERVAL_SECONDS,
            tracker.size,
            agg_tracker.bucket_count,
        )
        try:
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Interrupted — shutting down")
            sys.exit(0)


# ── CLI ──────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Carmin — Polymarket Insider Detection Bot",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="One cycle with live data, print scoring results, no webhook",
    )
    group.add_argument(
        "--test-webhook",
        action="store_true",
        help="Send hardcoded Maduro payload to the Make webhook",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.test_webhook:
        mode_test_webhook()
    elif args.dry_run:
        mode_dry_run()
    else:
        mode_production()


if __name__ == "__main__":
    main()
