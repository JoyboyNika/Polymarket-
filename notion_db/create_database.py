#!/usr/bin/env python3
"""Create the 'Trades Suspects — Carmin' Notion database.

Usage:
    python -m notion_db.create_database

Prerequisites:
    1. Copy .env.example to .env and fill in NOTION_TOKEN and NOTION_PARENT_PAGE_ID
    2. pip install -r requirements.txt
    3. Share the parent page with your Notion integration

The script will:
    - Create the database with all 29 properties
    - Print the database ID for use in other scripts / .env
"""

import json
import sys

from notion_client import Client

from notion_db.config import load_config
from notion_db.schema import DATABASE_TITLE, build_properties


def create_database(client: Client, parent_page_id: str) -> dict:
    """Create the Notion database with the full schema.

    Args:
        client: Authenticated Notion client.
        parent_page_id: ID of the parent page.

    Returns:
        The created database object from the Notion API.
    """
    properties = build_properties()

    response = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": DATABASE_TITLE}}],
        properties=properties,
    )
    return response


def main():
    config = load_config()
    client = Client(auth=config["token"])

    print(f"Creating database '{DATABASE_TITLE}'...")
    print(f"Parent page: {config['parent_page_id']}")

    try:
        db = create_database(client, config["parent_page_id"])
    except Exception as e:
        print(f"\nError creating database: {e}")
        sys.exit(1)

    db_id = db["id"]
    print(f"\nDatabase created successfully!")
    print(f"Database ID: {db_id}")
    print(f"URL: {db['url']}")

    # Count properties for verification
    prop_count = len(db["properties"])
    print(f"\nProperties created: {prop_count}")

    # List all properties with their types
    print("\nProperty verification:")
    for name, prop in sorted(db["properties"].items()):
        ptype = prop["type"]
        extra = ""
        if ptype == "formula":
            extra = f" → {prop['formula']['expression']}"
        elif ptype == "select":
            opts = [o["name"] for o in prop["select"]["options"]]
            extra = f" → {opts}"
        elif ptype == "multi_select":
            opts = [o["name"] for o in prop["multi_select"]["options"]]
            extra = f" → [{len(opts)} options]"
        print(f"  ✓ {name} ({ptype}){extra}")

    print(f"\nAdd this to your .env for other scripts:")
    print(f"NOTION_DATABASE_ID={db_id}")

    return db_id


if __name__ == "__main__":
    main()
