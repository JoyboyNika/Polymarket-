#!/usr/bin/env python3
"""One-shot setup: create Notion DB, insert test entry, print view instructions.

Usage:
    python setup.py

This runs the full setup sequence:
    1. Creates the database with all 29 properties
    2. Inserts the Maduro test entry
    3. Prints instructions for creating the 3 filtered views manually
"""

import os
import sys

from notion_client import Client
from dotenv import load_dotenv

from notion_db.config import load_config
from notion_db.create_database import create_database
from notion_db.create_test_entry import create_test_entry
from notion_db.setup_views import print_view_instructions, validate_views
from notion_db.schema import DATABASE_TITLE


def main():
    config = load_config()
    client = Client(auth=config["token"])

    # Step 1 — Create database
    print("=" * 60)
    print("STEP 1 — Creating database")
    print("=" * 60)
    print()

    try:
        db = create_database(client, config["parent_page_id"])
    except Exception as e:
        print(f"Error creating database: {e}")
        sys.exit(1)

    db_id = db["id"]
    print(f"Database '{DATABASE_TITLE}' created.")
    print(f"ID:  {db_id}")
    print(f"URL: {db['url']}")
    print(f"Properties: {len(db['properties'])}")
    print()

    # Step 2 — Insert test entry
    print("=" * 60)
    print("STEP 2 — Inserting Maduro test entry")
    print("=" * 60)
    print()

    try:
        page = create_test_entry(client, db_id)
    except Exception as e:
        print(f"Error inserting test entry: {e}")
        sys.exit(1)

    print(f"Test entry created: {page['url']}")
    print()

    # Step 3 — Views
    print_view_instructions()

    # Validate filters against the DB
    validate_views(client, db_id)

    # Summary
    print("=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print()
    print(f"Database URL: {db['url']}")
    print(f"Database ID:  {db_id}")
    print()
    print("Next steps:")
    print("  1. Add NOTION_DATABASE_ID={} to your .env".format(db_id))
    print("  2. Create the 3 views manually in Notion (see instructions above)")
    print("  3. Verify the Maduro test entry in the 'À traiter' view")
    print("  4. Check Multiplicateur gain shows ≈14.29")


if __name__ == "__main__":
    main()
