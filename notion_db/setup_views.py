#!/usr/bin/env python3
"""Guide and validate the 3 filtered views for the Trades Suspects database.

The Notion API does not support creating database views programmatically.
This script prints the exact configuration to apply manually in Notion,
then queries the database to verify the filters would work correctly.

Usage:
    python -m notion_db.setup_views

Views to create:
    1. "À traiter"  — Verdict = ⬜ Non traité OR 🟠 À définir, sorted by Date alerte desc
    2. "Insiders"    — Verdict = 🔴 Insider, sorted by Score desc
    3. "Mes trades"  — Trade pris = checked, sorted by Date du trade desc
"""

import os
import sys

from notion_client import Client
from dotenv import load_dotenv

from notion_db.config import load_config

# View definitions used for both documentation and validation queries
VIEWS = [
    {
        "name": "À traiter",
        "description": "Trades non encore analysés",
        "filter": {
            "or": [
                {"property": "Verdict", "select": {"equals": "⬜ Non traité"}},
                {"property": "Verdict", "select": {"equals": "🟠 À définir"}},
            ]
        },
        "sort": [{"property": "Date alerte", "direction": "descending"}],
    },
    {
        "name": "Insiders",
        "description": "Trades confirmés insider",
        "filter": {
            "property": "Verdict",
            "select": {"equals": "🔴 Insider"},
        },
        "sort": [{"property": "Score", "direction": "descending"}],
    },
    {
        "name": "Mes trades",
        "description": "Trades que j'ai pris",
        "filter": {
            "property": "Trade pris",
            "checkbox": {"equals": True},
        },
        "sort": [{"property": "Date du trade", "direction": "descending"}],
    },
]


def print_view_instructions():
    """Print manual setup instructions for each view."""
    print("=" * 60)
    print("FILTERED VIEWS — Manual Setup Instructions")
    print("=" * 60)
    print()
    print("The Notion API does not support creating views.")
    print("Create these 3 views manually in Notion:\n")

    for i, view in enumerate(VIEWS, 1):
        print(f"── View {i}: \"{view['name']}\" ──")
        print(f"   Description: {view['description']}")
        print(f"   Type: Table view")

        # Filter description
        filt = view["filter"]
        if "or" in filt:
            conditions = filt["or"]
            print(f"   Filter: (OR)")
            for cond in conditions:
                prop = cond["property"]
                for ftype, fval in cond.items():
                    if ftype != "property":
                        val = list(fval.values())[0]
                        print(f"     - {prop} {ftype}.equals \"{val}\"")
        else:
            prop = filt["property"]
            for ftype, fval in filt.items():
                if ftype != "property":
                    val = list(fval.values())[0]
                    print(f"   Filter: {prop} {ftype}.equals \"{val}\"")

        # Sort description
        for s in view["sort"]:
            print(f"   Sort: {s['property']} {s['direction']}")
        print()

    print("Steps in Notion:")
    print("  1. Open the database")
    print("  2. Click '+' next to existing views (top-left)")
    print("  3. Choose 'Table' layout")
    print("  4. Name the view")
    print("  5. Click 'Filter' → add the conditions above")
    print("  6. Click 'Sort' → add the sort above")
    print("  7. Repeat for each view")
    print()


def validate_views(client: Client, database_id: str):
    """Query the database with each view's filter to verify they work.

    Args:
        client: Authenticated Notion client.
        database_id: Target database ID.
    """
    print("=" * 60)
    print("VALIDATION — Querying database with view filters")
    print("=" * 60)
    print()

    for view in VIEWS:
        print(f"Testing \"{view['name']}\"...")
        try:
            results = client.databases.query(
                database_id=database_id,
                filter=view["filter"],
                sorts=view["sort"],
            )
            count = len(results["results"])
            print(f"  ✓ Query successful — {count} result(s)")

            # Show titles of matching entries
            for page in results["results"]:
                title_prop = page["properties"].get("Marché", {})
                title_parts = title_prop.get("title", [])
                title = title_parts[0]["plain_text"] if title_parts else "(untitled)"
                print(f"    → {title}")
        except Exception as e:
            print(f"  ✗ Query failed: {e}")
        print()


def main():
    print_view_instructions()

    # Optionally validate if database ID is available
    load_dotenv()
    db_id = os.getenv("NOTION_DATABASE_ID")

    if not db_id:
        print("NOTION_DATABASE_ID not set — skipping validation.")
        print("Set it in .env to validate filters against the actual DB.")
        return

    config = load_config()
    client = Client(auth=config["token"])
    validate_views(client, db_id)


if __name__ == "__main__":
    main()
