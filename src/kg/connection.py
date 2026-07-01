"""Graphiti + Neo4j connection setup.

Two factories:
  - make_driver(): the storage layer alone (no LLM/embedder key needed, but it
    DOES need a running Neo4j). Used by the connection-only healthcheck.
  - make_graphiti(): a fully-configured Graphiti with chat LLM + embedder wired
    independently. The LLM and embedder each get their own base_url/key/model,
    because they often live on different endpoints (e.g. a cheap chat relay that
    does NOT serve embeddings, plus a separate embedding provider).

Backend note: Kùzu was dropped — it is deprecated in graphiti-core and its
driver crashes on add_episode() with an explicit group_id (no _database attr).
Neo4j runs via docker-compose.yml (bolt on :7687).
"""

from __future__ import annotations

import os
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig

from kg.chat_completions_client import ChatCompletionsClient
from kg.sanitizing_driver import SanitizingNeo4jDriver

# group_id partitions (see README): Graphiti writes here atomically.
DRAFT_GROUP = "draft"          # fully automatic extraction lands here
CANONICAL_GROUP = "canonical"  # outward-facing truth; only via human-reviewed promotion

DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = "localdev_change_me"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
# Embedding dimension is baked into the graph schema on first write. Changing the
# embedder later requires rebuilding. Read from env, never hardcode.
DEFAULT_EMBED_DIM = 1536


def make_driver() -> SanitizingNeo4jDriver:
    """Construct a driver from NEO4J_* env (matches docker-compose.yml).

    Uses SanitizingNeo4jDriver (not the plain Neo4jDriver) to flatten nested-dict
    attribute values to JSON strings at the write boundary. Constrained-decoding
    endpoints occasionally emit nested objects for entity/edge attributes (e.g.
    Project.status={description: ...}); Neo4j only accepts primitives/arrays, so
    the raw driver crashes the whole ingest with CypherTypeError(Map{...}). See
    sanitizing_driver.py.
    """
    return SanitizingNeo4jDriver(
        uri=os.environ.get("NEO4J_URI", DEFAULT_NEO4J_URI),
        user=os.environ.get("NEO4J_USER", DEFAULT_NEO4J_USER),
        password=os.environ.get("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD),
    )


def _make_llm_client() -> ChatCompletionsClient:
    """Chat LLM client from OPENAI_* env (supports a custom base_url relay).

    Uses ChatCompletionsClient (chat.completions) rather than Graphiti's default
    OpenAIClient (Responses API), because the configured relay/endpoint does not
    implement the Responses API. See chat_completions_client.py for the why.

    small_model matters: Graphiti routes "simple" prompts (attribute extraction,
    dedup) to LLMConfig.small_model, which DEFAULTS to "gpt-4.1-nano". Relays
    like dasuapi don't serve that model and answer 503, so the run dies right
    after entity/edge extraction. Pin small_model to the main model (override
    via OPENAI_SMALL_MODEL only if the relay has a real cheaper model).
    """
    main_model = os.environ.get("OPENAI_MODEL", DEFAULT_CHAT_MODEL)
    config = LLMConfig(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        model=main_model,
        small_model=os.environ.get("OPENAI_SMALL_MODEL", main_model),
    )
    return ChatCompletionsClient(config=config)


def _make_embedder() -> OpenAIEmbedder:
    """Embedder from EMBEDDER_* env, falling back to OPENAI_* for key/base_url.

    embedding_dim must match the endpoint's actual output (e.g. Zhipu
    embedding-3 = 2048, OpenAI text-embedding-3-small = 1536), and is fixed into
    the graph schema on first write.
    """
    config = OpenAIEmbedderConfig(
        api_key=os.environ.get("EMBEDDER_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("EMBEDDER_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or None,
        embedding_model=os.environ.get("EMBEDDER_MODEL", DEFAULT_EMBED_MODEL),
        embedding_dim=int(os.environ.get("EMBEDDER_DIM", DEFAULT_EMBED_DIM)),
    )
    return OpenAIEmbedder(config=config)


def make_graphiti() -> Graphiti:
    """Build a fully-configured Graphiti backed by Neo4j.

    Requires a running Neo4j (see docker-compose.yml) + OPENAI_API_KEY (chat).
    Embedder uses EMBEDDER_* if set, else the OPENAI_* values. Run
    scripts/probe_endpoint.py first to confirm both endpoints work.
    """
    return Graphiti(
        graph_driver=make_driver(),
        llm_client=_make_llm_client(),
        embedder=_make_embedder(),
    )
