"""把 Neo4j 某个分区(group_id)导出成自包含 HTML 图,浏览器直接打开查看。

纯读取,不写图。用 vis-network(从 CDN 加载)渲染,数据内联进 HTML。
节点按实体类型着色,边按类型用不同颜色+标签区分,便于一眼看清
"人—能力—证据"结构。

Graphiti 存储约定(读自其 Cypher):所有实体边都是 Neo4j 的 RELATES_TO
关系类型,语义类型(HAS_SKILL/USES/DEMONSTRATES...)放在关系的 e.name 属性。

用法:
  uv run python scripts/visualize_graph.py [group_id] [输出.html]
  默认 group_id=draft, 输出 /tmp/kg_<group_id>.html
"""

from __future__ import annotations

import asyncio
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from kg.connection import make_driver  # noqa: E402

# 实体类型 -> 颜色(vis-network 节点色)
LABEL_COLOR = {
    "Person": "#F4C430",       # 金:图主人,视觉中心
    "Skill": "#2E9E5B",        # 绿:能做
    "Concept": "#3B82C4",      # 蓝:懂得
    "Technology": "#E8833A",   # 橙:工具
    "Project": "#D64550",      # 红:作品
    "Experience": "#8B5CF6",   # 紫:经历
    "Organization": "#14B8A6", # 青:组织
    "Entity": "#9AA0A6",       # 灰:未分类兜底
}

# 边类型 -> 颜色
EDGE_COLOR = {
    "HAS_SKILL": "#2E9E5B",
    "UNDERSTANDS": "#3B82C4",
    "USES": "#E8833A",
    "DEMONSTRATES": "#D64550",
    "BUILT_WITH": "#B0641F",
    "PART_OF": "#8B5CF6",
    "RELATES_TO": "#B8BDC4",
}


def _primary_label(labels: list[str]) -> str:
    specific = [lab for lab in labels if lab != "Entity"]
    return specific[0] if specific else "Entity"


async def fetch_graph(group_id: str) -> tuple[list[dict], list[dict]]:
    driver = make_driver()
    try:
        node_res = await driver.execute_query(
            "MATCH (n:Entity) WHERE n.group_id = $gid "
            "RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, n.summary AS summary",
            gid=group_id,
        )
        edge_res = await driver.execute_query(
            "MATCH (n:Entity)-[e:RELATES_TO]->(m:Entity) WHERE e.group_id = $gid "
            "RETURN e.uuid AS uuid, n.uuid AS src, m.uuid AS tgt, e.name AS name, e.fact AS fact",
            gid=group_id,
        )
    finally:
        await driver.close()

    nodes = []
    for r in node_res.records:
        label = _primary_label(r["labels"])
        nodes.append({
            "id": r["uuid"],
            "label": r["name"],
            "group": label,
            "color": LABEL_COLOR.get(label, LABEL_COLOR["Entity"]),
            "title": f"{label}: {r['name']}" + (f"\n{r['summary']}" if r["summary"] else ""),
            "value": 30 if label == "Person" else 12,
        })
    edges = []
    for r in edge_res.records:
        name = r["name"] or "RELATES_TO"
        edges.append({
            "id": r["uuid"],
            "from": r["src"],
            "to": r["tgt"],
            "label": name,
            "color": EDGE_COLOR.get(name, EDGE_COLOR["RELATES_TO"]),
            "title": r["fact"] or "",
            "arrows": "to",
        })
    return nodes, edges


def render_html(group_id: str, nodes: list[dict], edges: list[dict]) -> str:
    legend_items = "".join(
        f'<span class="chip" style="background:{c}">{lab}</span>' for lab, c in LABEL_COLOR.items()
    )
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>知识图谱 · {group_id}</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin:0; font-family:system-ui,-apple-system,"PingFang SC",sans-serif; background:#1a1c1e; color:#e8eaed; }}
  #head {{ padding:12px 16px; border-bottom:1px solid #333; }}
  #head h1 {{ font-size:16px; margin:0 0 6px; font-weight:600; }}
  #head .meta {{ font-size:12px; color:#9aa0a6; }}
  .chip {{ display:inline-block; padding:2px 8px; margin:2px 4px 2px 0; border-radius:10px;
           font-size:11px; color:#1a1c1e; font-weight:600; }}
  #net {{ width:100vw; height:calc(100vh - 78px); }}
</style></head>
<body>
  <div id="head">
    <h1>知识图谱 · 分区 {group_id}</h1>
    <div class="meta">{len(nodes)} 个实体 · {len(edges)} 条关系 &nbsp;|&nbsp; {legend_items}</div>
  </div>
  <div id="net"></div>
<script>
  const nodes = new vis.DataSet({json.dumps(nodes, ensure_ascii=False)});
  const edges = new vis.DataSet({json.dumps(edges, ensure_ascii=False)});
  const container = document.getElementById('net');
  new vis.Network(container, {{nodes, edges}}, {{
    nodes: {{ shape:'dot', font:{{color:'#e8eaed', size:14}}, borderWidth:0, scaling:{{min:8,max:36}} }},
    edges: {{ font:{{color:'#c0c4c8', size:10, strokeWidth:0, align:'middle'}},
              smooth:{{type:'dynamic'}}, width:1.5 }},
    physics: {{ barnesHut:{{gravitationalConstant:-8000, springLength:140, springConstant:0.04}},
                stabilization:{{iterations:200}} }},
    interaction: {{ hover:true, tooltipDelay:120 }}
  }});
</script>
</body></html>
"""


async def main() -> int:
    group_id = sys.argv[1] if len(sys.argv) > 1 else "draft"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"/tmp/kg_{group_id}.html")

    nodes, edges = await fetch_graph(group_id)
    if not nodes:
        print(f"分区 '{group_id}' 没有任何实体。先跑摄入(如 smoke_ingest.py)或换 group_id。")
        return 1

    out.write_text(render_html(group_id, nodes, edges), encoding="utf-8")
    print(f"已生成: {out}  ({len(nodes)} 实体, {len(edges)} 边)")
    print(f"浏览器打开: file://{out.resolve()}")
    try:
        webbrowser.open(f"file://{out.resolve()}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
