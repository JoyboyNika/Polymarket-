#!/usr/bin/env python3
"""Insert the Maduro test entry into the Trades Suspects database.

Usage:
    python -m notion_db.create_test_entry

Prerequisites:
    - Database must already exist (run create_database.py first)
    - NOTION_DATABASE_ID must be set in .env

The test entry validates:
    - All property types accept data correctly
    - Multiplicateur gain formula returns ~14.3 (1/0.07)
    - Entry appears in the "À traiter" view (Verdict = ⬜ Non traité)
"""

import os
import sys

from notion_client import Client
from dotenv import load_dotenv

from notion_db.config import load_config


def get_database_id() -> str:
    """Get database ID from environment."""
    load_dotenv()
    db_id = os.getenv("NOTION_DATABASE_ID")
    if not db_id:
        print("Error: NOTION_DATABASE_ID not set in .env")
        print("Run create_database.py first and add the ID to your .env")
        sys.exit(1)
    return db_id


def create_test_entry(client: Client, database_id: str) -> dict:
    """Insert the Maduro test case entry.

    Args:
        client: Authenticated Notion client.
        database_id: Target database ID.

    Returns:
        The created page object from the Notion API.
    """
    properties = {
        # ── Vue liste ──
        "Marché": {
            "title": [
                {"text": {"content": "Will Maduro leave office before Jan 31?"}}
            ]
        },
        "Score": {"number": 13},
        "Montant USDC": {"number": 32000},
        "Prix d'entrée": {"number": 0.07},
        # Multiplicateur gain is a formula — computed automatically
        "Date du trade": {"date": {"start": "2025-01-15"}},
        "Verdict": {"select": {"name": "⬜ Non traité"}},
        # Date alerte is created_time — automatic

        # ── Détail ──
        "Wallet": {"url": "https://polygonscan.com/address/0xTEST"},
        "Âge du compte": {
            "rich_text": [{"text": {"content": "3 jours"}}]
        },
        "Nb transactions lifetime": {"number": 5},
        "Nb marchés actifs": {"number": 1},
        "Historique gains/pertes": {
            "rich_text": [{"text": {"content": "Aucun historique — compte neuf"}}]
        },
        "Source de financement": {
            "rich_text": [
                {"text": {"content": "Transfert direct depuis exchange (Binance)"}}
            ]
        },
        "Probabilité marché": {"number": 0.07},
        "Volume marché 24h": {"number": 45000},
        "Critères déclenchés": {
            "multi_select": [
                {"name": "wallet_neuf"},
                {"name": "mise_massive"},
                {"name": "marché_improbable"},
            ]
        },
        "Fiche Haiku": {
            "rich_text": [
                {
                    "text": {
                        "content": (
                            "[TEST] Wallet neuf (3j), mise massive (32k USDC) "
                            "sur marché à 7% de probabilité. Aucun historique. "
                            "Pattern typique d'insider trading."
                        )
                    }
                }
            ]
        },
        "Prédiction ML": {
            "rich_text": [{"text": {"content": "[TEST] Score ML: 0.87 — High risk"}}]
        },

        # ── Tracking perso ──
        # Verdict already set above
        "Raison du verdict": {"rich_text": [{"text": {"content": ""}}]},
        "Notes perso / Deep Search": {"rich_text": [{"text": {"content": ""}}]},
        "Trade pris": {"checkbox": False},
        "Somme misée": {"number": 0},

        # ── Post-résolution ──
        # Left empty — will be filled by Make cron

        # ── Technique ──
        "Condition ID marché": {
            "rich_text": [{"text": {"content": "test-maduro-condition-id"}}]
        },
        "Trade ID": {
            "rich_text": [{"text": {"content": "test-tx-hash-0x1234"}}]
        },
    }

    response = client.pages.create(
        parent={"database_id": database_id},
        properties=properties,
    )
    return response


def main():
    config = load_config()
    database_id = get_database_id()
    client = Client(auth=config["token"])

    print("Inserting Maduro test entry...")
    print(f"Database: {database_id}")

    try:
        page = create_test_entry(client, database_id)
    except Exception as e:
        print(f"\nError creating test entry: {e}")
        sys.exit(1)

    print(f"\nTest entry created successfully!")
    print(f"Page ID: {page['id']}")
    print(f"URL: {page['url']}")

    print("\nVerification checklist:")
    print("  ✓ Marché = 'Will Maduro leave office before Jan 31?'")
    print("  ✓ Score = 13")
    print("  ✓ Montant USDC = 32,000")
    print("  ✓ Prix d'entrée = 0.07")
    print("  ✓ Multiplicateur gain should show ≈14.29 (1/0.07)")
    print("  ✓ Verdict = ⬜ Non traité")
    print("  ✓ Critères: wallet_neuf, mise_massive, marché_improbable")
    print("  ✓ Condition ID marché = test-maduro-condition-id")
    print("  ✓ Trade ID = test-tx-hash-0x1234")
    print("\n  → Open the DB in Notion and check the 'À traiter' view")


if __name__ == "__main__":
    main()
