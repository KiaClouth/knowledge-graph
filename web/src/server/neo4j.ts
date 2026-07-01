// Server-only Neo4j driver: module-level lazy singleton.
//
// The driver holds a connection pool internally, so it must be created ONCE and
// reused across requests — never per-request (that leaks sockets). We never call
// driver.close(); the process lifetime owns it.
//
// SECURITY: this module reads process.env.NEO4J_* (no VITE_ prefix, so Vite will
// not inline it into the client bundle) and is only imported by server functions
// in server/graph.ts. Never import it from a .tsx component body.

import neo4j, { type Driver } from 'neo4j-driver'

let driver: Driver | undefined

export const NEO4J_DATABASE = process.env.NEO4J_DATABASE || 'neo4j'

export function getDriver(): Driver {
  if (!driver) {
    const uri = process.env.NEO4J_URI || 'bolt://localhost:7687'
    const user = process.env.NEO4J_USER || 'neo4j'
    const password = process.env.NEO4J_PASSWORD || 'localdev_change_me'
    driver = neo4j.driver(uri, neo4j.auth.basic(user, password))
  }
  return driver
}
