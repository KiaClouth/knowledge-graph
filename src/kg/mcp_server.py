"""个人知识/能力图谱的 MCP server(最小版:只提供 remember)。

对外接口:把一段对话/自述摄入图谱。挂到支持 MCP 的 agent 平台(Claude Code、
Codex)后,agent 可在对话中调用 remember 把新的技能/项目/知识沉淀进图。

remember 的动作:
  add_episode(写 draft 分区, 锁定本体抽取) → inject_owner(确定性补上
  "图主人—能力—证据"边) → 返回抽取摘要。

设计约定(见 docs/architecture.md):
- 只写 draft 分区。canonical(对外可信)由后续人工/风险晋升产生,不在此。
- 自动注入 graph-owner:抽取本身不产出 Person 节点(见 memory 抽取质量根因),
  故由 inject_owner 代码确定性补全,让写入的图直接带"我—能力—证据"结构。

已知限制(未治本,见 memory):LLM 偶尔给实体属性填嵌套对象,Neo4j 拒绝嵌套
属性会导致 add_episode 内部崩溃。remember 捕获异常并返回错误信息,避免整个
server 挂掉——单次 remember 失败不影响后续调用。

启动(stdio): uv run python -m kg.mcp_server
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from graphiti_core.nodes import EpisodeType  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from kg.connection import DRAFT_GROUP, make_graphiti  # noqa: E402
from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402
from kg.owner import inject_owner  # noqa: E402

mcp = FastMCP("knowledge-graph")


@mcp.tool()
async def remember(text: str, source: str = "unknown", occurred_at: str | None = None) -> dict[str, Any]:
    """把一段内容摄入个人知识/能力图谱(写入 draft 待晋升分区)。

    什么时候调用:当对话中出现关于本人(图主人)的、值得长期留存的信息——
    新的技能、做过的项目、使用的技术、表达出的理解或经历时。优先摄入
    **叙事体**陈述("我用 X 做了 Y"),它比能力罗列("我精通 X")能抽出更丰富、
    更可信(带证据)的关系。

    Args:
        text: 要记住的自然语言内容(一段对话、一条自述)。
        source: 来源标识,如 "claude-code" / "codex" / "chatgpt-export"。
        occurred_at: 事件发生时间(ISO8601);缺省用当前时间。

    Returns:
        摄入结果摘要:ok 标志、抽取到的实体/关系计数、owner 补出的能力边数;
        失败时 ok=False 并带 error 说明(不会使 server 崩溃)。
    """
    if not text or not text.strip():
        return {"ok": False, "error": "text 为空,无内容可摄入。"}

    try:
        ref_time = (
            datetime.fromisoformat(occurred_at) if occurred_at else datetime.now(timezone.utc)
        )
    except ValueError:
        return {"ok": False, "error": f"occurred_at 不是合法 ISO8601: {occurred_at!r}"}

    graphiti = make_graphiti()
    try:
        await graphiti.build_indices_and_constraints()
        result = await graphiti.add_episode(
            name=f"remember-{ref_time.isoformat()}",
            episode_body=text,
            source_description=f"remember via MCP (source={source})",
            reference_time=ref_time,
            source=EpisodeType.text,
            group_id=DRAFT_GROUP,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )
        owner, owner_edges = await inject_owner(graphiti, result.nodes, DRAFT_GROUP)
        return {
            "ok": True,
            "partition": DRAFT_GROUP,
            "entities_extracted": len(result.nodes),
            "edges_extracted": len(result.edges),
            "owner_edges_added": len(owner_edges),
            "owner": owner.name,
            "note": "已写入 draft 分区,待晋升为 canonical。",
        }
    except Exception as e:  # 已知脆弱点:嵌套属性等致 add_episode 崩;不拖垮 server
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "hint": "可能是 LLM 给属性填了嵌套对象(已知限制),或端点瞬时错误,可重试。",
        }
    finally:
        await graphiti.close()


def main() -> None:
    """stdio 方式启动 MCP server。"""
    mcp.run()


if __name__ == "__main__":
    main()
