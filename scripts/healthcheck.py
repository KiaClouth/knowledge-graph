"""Connection-only healthcheck.

Verifies the storage layer (Neo4j) is reachable WITHOUT calling the LLM/embedder:
  1. Neo4jDriver connects (needs a running Neo4j — see docker-compose.yml).
  2. The Graphiti schema/indices can be created.
  3. A trivial structural query round-trips.

Run:  uv run python scripts/healthcheck.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from kg.connection import make_driver  # noqa: E402


async def main() -> int:
    driver = make_driver()
    print("[1/3] Neo4jDriver init   : ok (no LLM/embedder involved)")

    try:
        # Minimal structural read straight through the driver — proves the
        # Neo4j connection is live without invoking any LLM extraction.
        records, _, _ = await driver.execute_query("RETURN 1 AS ok")
        ok = records[0]["ok"] if records else None
        assert ok == 1, f"unexpected query result: {records!r}"
        print(f"[2/3] Driver round-trip : ok (RETURN 1 -> {ok})")

        await driver.build_indices_and_constraints()
        print("[3/3] Indices/schema    : ok")
    finally:
        await driver.close()

    print("\nHEALTHCHECK PASSED — Neo4j storage layer is reachable.")
    print("Next: uv run python scripts/smoke_ingest.py  (real extraction).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
