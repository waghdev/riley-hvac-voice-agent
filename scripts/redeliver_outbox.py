"""Send leads still pending in the outbox to the CRM again.

    uv run python scripts/redeliver_outbox.py

Reads MOCK_CRM_URL and DATA_DIR the way the agent does (from .env). Safe to run any time: each
lead keeps its idempotency key, so one that did reach the CRM before isn't stored twice.
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from agent.config import REPO_ROOT
from agent.crm_client import CrmClient, Outbox


async def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("MOCK_CRM_URL")
    if not url:
        print("MOCK_CRM_URL isn't set; nothing to send to.")
        return 1
    outbox = Outbox(Path(os.getenv("DATA_DIR", REPO_ROOT / "data")) / "outbox.sqlite3")
    results = await CrmClient(url, outbox).redeliver_pending()
    for key, status in results.items():
        print(f"{key}  {status}")
    print(f"{len(results)} pending lead(s) tried.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
