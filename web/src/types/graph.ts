// vis-network-ready graph shapes. The server function maps Neo4j records into
// these on the server side, so the client just hands them to vis.DataSet.
// All fields are plain strings/numbers (no neo4j Integer) → serialization-safe.

export interface GraphNode {
  id: string
  label: string
  group: string
  color: string
  title: string
  value: number
}

export interface GraphEdge {
  id: string
  from: string
  to: string
  label: string
  color: string
  title: string
  arrows: string
}

export interface GraphData {
  groupId: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}
