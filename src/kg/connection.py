"""Graphiti + Kùzu connection setup.

This module only wires up the storage/engine layer. It deliberately does NOT
configure an LLM or embedder by default, so it can be initialized (and the Kùzu
schema created) without any API key. Extraction (which needs OpenAI) is added in
a later step.
"""

from __future__ import annotations

import os
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver

# group_id partitions (see README): Graphiti writes here atomically.
DRAFT_GROUP = "draft"          # fully automatic extraction lands here
CANONICAL_GROUP = "canonical"  # outward-facing truth; only via human-reviewed promotion

DEFAULT_DB_PATH = "./data/graphiti.kuzu"


def resolve_db_path() -> str:
    """Resolve the Kùzu DB path from env, defaulting to ./data/graphiti.kuzu."""
    path = os.environ.get("KUZU_DB_PATH", DEFAULT_DB_PATH)
    # Kùzu creates the database itself, but its parent directory must exist.
    parent = Path(path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    return path


def make_driver(db_path: str | None = None) -> KuzuDriver:
    """Construct a KuzuDriver against a local on-disk database."""
    return KuzuDriver(db=db_path or resolve_db_path())


def make_graphiti(db_path: str | None = None) -> Graphiti:
    """Build a Graphiti instance backed by Kùzu.

    NOTE: Graphiti's constructor eagerly creates an OpenAIClient when no
    llm_client is supplied, and AsyncOpenAI requires a key at construction time.
    So this requires OPENAI_API_KEY to be set even before any extraction call.
    Used by the real ingest step, NOT by the connection-only healthcheck — the
    healthcheck talks to KuzuDriver directly (see make_driver) to stay key-free.
    """
    return Graphiti(graph_driver=make_driver(db_path))
