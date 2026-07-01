import { createFileRoute } from '@tanstack/solid-router'
import { createSignal, onCleanup, onMount } from 'solid-js'
import { getGraph } from '../server/graph'
import { LABEL_COLOR } from '../lib/graph-theme'

export const Route = createFileRoute('/')({ component: GraphPage })

// vis-network render params, ported line-for-line from scripts/visualize_graph.py.
const VIS_OPTIONS = {
  nodes: {
    shape: 'dot',
    font: { color: '#e8eaed', size: 14 },
    borderWidth: 0,
    scaling: { min: 8, max: 36 },
  },
  edges: {
    font: { color: '#c0c4c8', size: 10, strokeWidth: 0, align: 'middle' },
    smooth: { type: 'dynamic' },
    width: 1.5,
  },
  physics: {
    barnesHut: {
      gravitationalConstant: -8000,
      springLength: 140,
      springConstant: 0.04,
    },
    stabilization: { iterations: 200 },
  },
  interaction: { hover: true, tooltipDelay: 120 },
} as const

function GraphPage() {
  const GROUP_ID = 'draft'
  let container!: HTMLDivElement
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let network: any
  const [status, setStatus] = createSignal<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [error, setError] = createSignal('')
  const [counts, setCounts] = createSignal({ nodes: 0, edges: 0 })

  onMount(async () => {
    try {
      // vis-network touches window on import → dynamic import inside onMount so it
      // never runs during SSR. standalone bundle self-contains vis-data.
      const vis = await import('vis-network/standalone')
      const data = await getGraph({ data: GROUP_ID })

      setCounts({ nodes: data.nodes.length, edges: data.edges.length })
      if (data.nodes.length === 0) {
        setStatus('empty')
        return
      }

      const nodes = new vis.DataSet(data.nodes)
      const edges = new vis.DataSet(data.edges)
      network = new vis.Network(container, { nodes, edges }, VIS_OPTIONS)
      setStatus('ready')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
    }
  })

  onCleanup(() => {
    if (network) network.destroy()
  })

  return (
    <main style={{ margin: 0, background: '#1a1c1e', color: '#e8eaed', 'min-height': '100vh' }}>
      <div style={{ padding: '12px 16px', 'border-bottom': '1px solid #333' }}>
        <h1 style={{ 'font-size': '16px', margin: '0 0 6px', 'font-weight': 600 }}>
          知识图谱 · 分区 {GROUP_ID}
        </h1>
        <div style={{ 'font-size': '12px', color: '#9aa0a6' }}>
          {status() === 'loading' && '加载中…'}
          {status() === 'ready' &&
            `${counts().nodes} 个实体 · ${counts().edges} 条关系`}
          {status() === 'empty' &&
            `分区 '${GROUP_ID}' 没有任何实体。先跑摄入,或换 group_id。`}
          {status() === 'error' && `加载失败: ${error()}`}
          <span style={{ 'margin-left': '12px' }}>
            {Object.entries(LABEL_COLOR).map(([label, color]) => (
              <span
                style={{
                  display: 'inline-block',
                  padding: '2px 8px',
                  margin: '2px 4px 2px 0',
                  'border-radius': '10px',
                  'font-size': '11px',
                  color: '#1a1c1e',
                  'font-weight': 600,
                  background: color,
                }}
              >
                {label}
              </span>
            ))}
          </span>
        </div>
      </div>
      <div ref={container} style={{ width: '100vw', height: 'calc(100vh - 78px)' }} />
    </main>
  )
}
