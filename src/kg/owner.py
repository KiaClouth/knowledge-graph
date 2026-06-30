"""确定性注入图主人(graph owner)并补全以人为中心的能力边。

为什么需要它(读 verify_extraction_quality 四次对照实验得出):
Graphiti 的 LLM 抽取在叙事体输入下能很好地抽出"项目→技术/知识"的边
(BUILT_WITH/DEMONSTRATES),但**始终不把"我"这个图主人建成 Person 节点**,
于是缺少 Person→Skill/Concept/Technology 的能力边——而这恰是本项目的核心
("我会什么/懂什么/凭什么")。指望调 prompt 或改人称都已证实无效。

策略:不靠 LLM 抽人,而在 add_episode 之后用代码**确定性**地:
  1. 确保存在唯一的 graph-owner Person 节点(幂等:按 group_id+name 复用)。
  2. 按锁定本体把 owner 连到本次抽取出的实体:
       owner --USES-->        每个 Technology
       owner --UNDERSTANDS--> 每个 Concept
       owner --DEMONSTRATES-->每个 Project / Experience
     (Skill 实体目前 LLM 很少抽出;HAS_SKILL 暂不在此合成,留待后续从
      DEMONSTRATES 证据反推,避免无依据地造 Skill。)

这些边是确定性补的,故标记 attributes['origin']='owner_synthesis',与 LLM
抽取的边区分开——晋升评审时可据此分流(合成边低风险、可直接晋升)。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.nodes import EntityNode

DEFAULT_OWNER_NAME = "图主人"

# (目标实体 label) -> (owner 指向它时用的边类型)
OWNER_EDGE_FOR_LABEL: dict[str, str] = {
    "Technology": "USES",
    "Concept": "UNDERSTANDS",
    "Project": "DEMONSTRATES",
    "Experience": "DEMONSTRATES",
}


def _label_of(node: EntityNode) -> str:
    """返回节点的本体 label(去掉 Graphiti 通用的 'Entity')。"""
    specific = [lab for lab in node.labels if lab != "Entity"]
    return specific[0] if specific else "Entity"


async def ensure_owner(graphiti: Graphiti, group_id: str, owner_name: str) -> EntityNode:
    """取得或新建该分区里的 graph-owner Person 节点(按 name 幂等)。"""
    existing = await EntityNode.get_by_group_ids(graphiti.driver, [group_id])
    for n in existing:
        if n.name == owner_name and "Person" in n.labels:
            return n

    owner = EntityNode(
        name=owner_name,
        group_id=group_id,
        labels=["Entity", "Person"],
        summary="图主人:本知识图谱所代表的人。",
        created_at=datetime.now(timezone.utc),
        attributes={"origin": "owner_synthesis"},
    )
    await owner.generate_name_embedding(graphiti.embedder)
    await owner.save(graphiti.driver)
    return owner


async def link_owner_to_entities(
    graphiti: Graphiti,
    owner: EntityNode,
    nodes: list[EntityNode],
    group_id: str,
) -> list[EntityEdge]:
    """按本体把 owner 连到抽取出的实体,返回新建的边。"""
    now = datetime.now(timezone.utc)
    new_edges: list[EntityEdge] = []
    for node in nodes:
        if node.uuid == owner.uuid:
            continue
        edge_type = OWNER_EDGE_FOR_LABEL.get(_label_of(node))
        if not edge_type:
            continue
        verb = {"USES": "使用", "UNDERSTANDS": "理解", "DEMONSTRATES": "通过项目/经历体现了对其的运用"}[
            edge_type
        ]
        edge = EntityEdge(
            group_id=group_id,
            source_node_uuid=owner.uuid,
            target_node_uuid=node.uuid,
            name=edge_type,
            fact=f"{owner.name}{verb} {node.name}。",
            created_at=now,
            attributes={"origin": "owner_synthesis"},
        )
        await edge.generate_embedding(graphiti.embedder)
        await edge.save(graphiti.driver)
        new_edges.append(edge)
    return new_edges


async def inject_owner(
    graphiti: Graphiti,
    nodes: list[EntityNode],
    group_id: str,
    owner_name: str | None = None,
) -> tuple[EntityNode, list[EntityEdge]]:
    """一站式:确保 owner 存在并连到本次抽取的实体。

    owner_name 缺省读 env GRAPH_OWNER_NAME,再缺省用 DEFAULT_OWNER_NAME。
    返回 (owner 节点, 新建的能力边列表)。
    """
    name = owner_name or os.environ.get("GRAPH_OWNER_NAME", DEFAULT_OWNER_NAME)
    owner = await ensure_owner(graphiti, group_id, name)
    edges = await link_owner_to_entities(graphiti, owner, nodes, group_id)
    return owner, edges
