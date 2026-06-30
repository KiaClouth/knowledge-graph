# knowledge-graph

A personal knowledge/capability graph that maintains itself from conversations.
Built on [Graphiti](https://github.com/getzep/graphiti) (temporal knowledge graph
engine) backed by an embedded [Kùzu](https://kuzudb.com/) database.

## Why this exists

To represent — for job-seeking and for briefing other agents — **what I can do**
(skills) and **what I understand** (knowledge domains), with evidence and
provenance, kept current by feeding it conversations.

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

## Status

Scaffold + connection-only healthcheck. Ontology models, normalized Episode
ingest, and the promotion-review CLI come after the healthcheck passes.

## Setup

```bash
cd ~/code/knowledge-graph
uv sync                      # create venv + install deps
cp .env.example .env         # then fill in OPENAI_API_KEY (not needed for healthcheck)
uv run python scripts/healthcheck.py
```

The healthcheck does **not** call OpenAI — it only verifies that Kùzu creates a
database and that Graphiti initializes against it.
