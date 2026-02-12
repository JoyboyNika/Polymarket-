"""Configuration loader for Notion API credentials."""

import os
import sys

from dotenv import load_dotenv


def load_config() -> dict:
    """Load and validate configuration from environment variables.

    Returns:
        dict with 'token' and 'parent_page_id' keys.

    Raises:
        SystemExit: If required environment variables are missing.
    """
    load_dotenv()

    token = os.getenv("NOTION_TOKEN")
    parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID")

    missing = []
    if not token:
        missing.append("NOTION_TOKEN")
    if not parent_page_id:
        missing.append("NOTION_PARENT_PAGE_ID")

    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    return {"token": token, "parent_page_id": parent_page_id}
