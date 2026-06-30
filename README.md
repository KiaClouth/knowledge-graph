# knowledge-graph

A personal knowledge/capability graph that maintains itself from conversations.
Built on [Graphiti](https://github.com/getzep/graphiti) (temporal knowledge graph
engine) backed by [Neo4j](https://neo4j.com/).

## Goal

A **cross-platform, self-maintaining personal knowledge/capability graph** —
one shared graph usable across multiple agent platforms.

- **Purpose** — when job-seeking and when briefing other agents, to express
  *what I can do, what I understand, and the evidence for it* — a trustworthy
  representation of my knowledge scope and capabilities.
- **Maintenance** — kept current through everyday conversation + imported chat
  history, so the graph maintains itself rather than being hand-curated.
- **Stretch goals (lower priority)** — render the graph to images / generate a
  site from it.

### Key requirements (in the order they were clarified)

1. **Cross-platform sharing** — one graph shared across Codex, ChatGPT web,
   Perplexity, Claude Code, Gemini web, etc. Reality: only Codex / Claude Code
   can attach tools; web platforms are ingested by exporting and parsing chat
   history. Both entry points normalize into one pipeline.
2. **Passive maintenance, not active invocation** — "just by conversing and
   importing history, the graph maintains itself." Approach: fully-automatic
   writes + human confirmation (auto-write to `draft` → human-promote to
   `canonical`), because this graph represents me outwardly — mis-attributing a
   capability is worse than missing one.
3. **No readability requirement at the storage layer; performance first.**
   Generating docs/graphs from the underlying data is a separate, deferred
   design.
4. **Layered presentation** — layer one guarantees readability; layer two aims
   for good visualization.

## Architecture

### Two ingestion entry points, one pipeline

Every input is normalized to an **Episode** (`source`, `timestamp`, `speaker`,
`text`, `content_hash`):

- **Live (MCP-capable platforms: Claude Code, Codex)** — feed Episodes in real time.
- **Export-parse (web platforms: ChatGPT / Perplexity / Gemini)** — export chat
  history, parse to the same Episode shape (one adapter per platform).

Both flow into the same pipeline: dedup gate (`content_hash`) → Graphiti
extraction + entity resolution → write.

### Two-layer graph (Graphiti `group_id` partitions)

Graphiti writes atomically (extract → resolve → write); it has no built-in
"pending review" state. We get human-in-the-loop by partitioning:

- **`draft`** partition — Graphiti writes here fully automatically.
- **`canonical`** partition — the outward-facing source of truth. Things only
  arrive here by being **promoted** from `draft` after human review.

"Human confirmation" = a promotion step (a small CLI), not a hack of Graphiti's
write path. The draft layer can be fully automatic; the canonical layer is
human-gated because this graph represents me publicly.

### Locked ontology

7 entity types (`Person`, `Skill`, `Concept`, `Technology`, `Project`,
`Experience`, `Organization` — `Skill` = *can do* vs `Concept` = *understands*,
kept distinct) and 7 edge types. See `src/kg/ontology.py`. "Locked" constrains
the extraction *vocabulary*, not off-ontology node pairs absolutely.

## Requirements

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker (for Neo4j via `docker-compose.yml`)
- A chat LLM endpoint that supports **server-side constrained decoding**
  (`response_format: json_schema` with `strict: true`) — Graphiti's extraction
  depends on it. Many OpenAI-compatible relays only *pass through* the schema
  without enforcing it; those don't work. Verify any endpoint with
  `scripts/probe_structured_output.py` before relying on it.
- A separate embeddings endpoint (the chat relay often doesn't serve embeddings).

## Setup

```bash
cd ~/code/knowledge-graph
uv sync                      # create venv + install deps
cp .env.example .env         # then fill in the chat + embedder endpoints

docker compose up -d         # start Neo4j (bolt :7687, browser http://localhost:7474)
uv run python scripts/healthcheck.py   # verify the Neo4j storage layer
```

### Configuration (`.env`)

The chat LLM and the embedder are configured **independently** because they
usually live on different endpoints:

- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` — chat extraction.
- `OPENAI_SMALL_MODEL` — Graphiti routes "simple" tasks (attribute extraction,
  dedup) to a *small model*. Its built-in default is `gpt-4.1-nano`, which most
  relays don't serve (→ 503). Leave this blank to fall back to the main model;
  only set it if your endpoint has a real cheaper model.
- `EMBEDDER_*` — embeddings endpoint. `EMBEDDER_DIM` must match the endpoint's
  actual output (e.g. Zhipu embedding-3 = 2048) and is **baked into the graph
  schema on first write** — changing it later means rebuilding.

## Scripts

| Script | Purpose |
| --- | --- |
| `healthcheck.py` | Verify Neo4j is reachable (no LLM/embedder calls). |
| `probe_structured_output.py` | Test whether an endpoint truly supports `json_schema` strict decoding. The **decisive** check before trusting any relay. |
| `probe_endpoint.py` | Smoke-test chat + embedder connectivity. |
| `validate_ontology.py` | Offline-validate the ontology models against Graphiti's reserved-field rules. |
| `smoke_ingest.py` | End-to-end: extract from a sample self-intro and write to the `draft` partition. |

## End-to-end ingest

```bash
uv run python scripts/smoke_ingest.py
```

This makes real API calls (extraction + embeddings) on a short sample and writes
the extracted entities/edges into the `draft` partition.

> Note: on a fresh/empty graph the first run prints many `01N52` Neo4j
> notification warnings (`name_embedding`/`fact_embedding`/… property does not
> exist). These are **harmless** — they're just empty-table vector lookups. The
> real error, if any, appears after them.

## Status

Ingestion pipeline works end-to-end against Neo4j (entity + edge extraction,
attribute hydration, embeddings, write to `draft`). Next up: the promotion-review
CLI (`draft` → `canonical`), then per-platform chat-export parsers, then
visualization / site export.
