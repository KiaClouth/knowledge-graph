// getGraph server function: reads a Neo4j partition (group_id) and returns
// vis-network-ready {nodes, edges}. Read-only (MATCH/RETURN only).
//
// Ported from scripts/visualize_graph.py fetch_graph(): same two Cypher queries.
// Mapping to vis shapes happens HERE on the server, so the client never touches
// neo4j-driver. Queried properties are all strings (no neo4j Integer) → the
// result serializes cleanly across the server-fn boundary.

import { createServerFn } from '@tanstack/solid-start'
import { getDriver, NEO4J_DATABASE } from './neo4j'
import { toVisEdge, toVisNode } from '../lib/graph-theme'
import type { GraphData } from '../types/graph'

const NODE_CYPHER =
  'MATCH (n:Entity) WHERE n.group_id = $gid ' +
  'RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, n.summary AS summary'

const EDGE_CYPHER =
  'MATCH (n:Entity)-[e:RELATES_TO]->(m:Entity) WHERE e.group_id = $gid ' +
  'RETURN e.uuid AS uuid, n.uuid AS src, m.uuid AS tgt, e.name AS name, e.fact AS fact'

export const getGraph = createServerFn({ method: 'GET' })
  .validator((gid: unknown): string => (typeof gid === 'string' && gid ? gid : 'draft'))
  .handler(async ({ data: groupId }): Promise<GraphData> => {
    const driver = getDriver()
    const params = { gid: groupId }
    const cfg = { database: NEO4J_DATABASE }

    const [nodeRes, edgeRes] = await Promise.all([
      driver.executeQuery(NODE_CYPHER, params, cfg),
      driver.executeQuery(EDGE_CYPHER, params, cfg),
    ])

    const nodes = nodeRes.records.map((r) =>
      toVisNode({
        uuid: r.get('uuid'),
        name: r.get('name'),
        labels: r.get('labels'),
        summary: r.get('summary'),
      }),
    )
    const edges = edgeRes.records.map((r) =>
      toVisEdge({
        uuid: r.get('uuid'),
        src: r.get('src'),
        tgt: r.get('tgt'),
        name: r.get('name'),
        fact: r.get('fact'),
      }),
    )

    return { groupId, nodes, edges }
  })
