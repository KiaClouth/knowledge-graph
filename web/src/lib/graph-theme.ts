// Colors + node/edge mapping, ported 1:1 from scripts/visualize_graph.py.
// Kept framework-agnostic (no vis import) so it can run on server or client.

import type { GraphEdge, GraphNode } from '../types/graph'

// Entity type -> node color.
export const LABEL_COLOR: Record<string, string> = {
  Person: '#F4C430', // gold: the graph owner, visual center
  Skill: '#2E9E5B', // green: can do
  Concept: '#3B82C4', // blue: understands
  Technology: '#E8833A', // orange: tools
  Project: '#D64550', // red: works
  Experience: '#8B5CF6', // purple: history
  Organization: '#14B8A6', // teal: orgs
  Entity: '#9AA0A6', // gray: unclassified fallback
}

// Semantic edge type (stored in e.name) -> edge color.
export const EDGE_COLOR: Record<string, string> = {
  HAS_SKILL: '#2E9E5B',
  UNDERSTANDS: '#3B82C4',
  USES: '#E8833A',
  DEMONSTRATES: '#D64550',
  BUILT_WITH: '#B0641F',
  PART_OF: '#8B5CF6',
  RELATES_TO: '#B8BDC4',
}

// Neo4j nodes carry both :Entity and a specific type label; pick the specific one.
export function primaryLabel(labels: string[]): string {
  const specific = labels.filter((l) => l !== 'Entity')
  return specific.length > 0 ? specific[0] : 'Entity'
}

export function toVisNode(r: {
  uuid: string
  name: string
  labels: string[]
  summary: string | null
}): GraphNode {
  const label = primaryLabel(r.labels)
  return {
    id: r.uuid,
    label: r.name,
    group: label,
    color: LABEL_COLOR[label] ?? LABEL_COLOR.Entity,
    title: `${label}: ${r.name}` + (r.summary ? `\n${r.summary}` : ''),
    value: label === 'Person' ? 30 : 12,
  }
}

export function toVisEdge(r: {
  uuid: string
  src: string
  tgt: string
  name: string | null
  fact: string | null
}): GraphEdge {
  const name = r.name || 'RELATES_TO'
  return {
    id: r.uuid,
    from: r.src,
    to: r.tgt,
    label: name,
    color: EDGE_COLOR[name] ?? EDGE_COLOR.RELATES_TO,
    title: r.fact || '',
    arrows: 'to',
  }
}
