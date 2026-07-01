"""Project-local patches for the vendored Graphiti MCP server.

Vendored copies of the two files from the parent knowledge-graph repo's kg
package that the server needs, so the Docker image is self-contained (the
build context is just mcp_server/, no need to reach into the parent repo):

- chat_completions_client.py: strict json_schema client for constrained-decoding
  relays like dasuapi (the migration probe showed the stock OpenAIGenericClient's
  no-strict json_schema hard-fails there). Used by services/factories.py.
- sanitizing_driver.py: Neo4j driver that flattens nested-dict attribute values
  to JSON strings at the write boundary, avoiding CypherTypeError(Map{}). Used by
  graphiti_mcp_server.py's Neo4j branch.

Keep these in sync with the parent repo's src/kg/ if that source changes.
"""
