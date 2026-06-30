"""Connection-only healthcheck.

Verifies the storage/engine layer works WITHOUT calling OpenAI by talking to the
Kùzu driver directly (NOT through Graphiti, whose constructor eagerly builds an
OpenAI client and would demand a key):
  1. Kùzu creates an on-disk database.
  2. The driver connects.
  3. The Graphiti schema can be created on it.
  4. A trivial structural query round-trips.

Run:  uv run python scripts/healthcheck.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make `import kg` work when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kg.connection import make_driver, resolve_db_path  # noqa: E402


async def main() -> int:
    db_path = resolve_db_path()
    print(f"[1/4] Kùzu DB path     : {db_path}")

    driver = make_driver(db_path)
    print("[2/4] KuzuDriver init    : ok (no OpenAI client involved)")

    try:
        driver.setup_schema()  # synchronous in KuzuDriver
        print("[3/4] Schema setup       : ok")

        # Minimal structural read straight through the driver — proves the
        # Kùzu connection is live without invoking any LLM extraction.
        records, _, _ = await driver.execute_query("RETURN 1 AS ok")
        ok = records[0]["ok"] if records else None
        assert ok == 1, f"unexpected query result: {records!r}"
        print(f"[4/4] Driver round-trip : ok (RETURN 1 -> {ok})")
    finally:
        await driver.close()

    print("\nHEALTHCHECK PASSED — storage/engine layer is wired up.")
    print("Next: add OPENAI_API_KEY to .env, then we build the ontology + ingest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
