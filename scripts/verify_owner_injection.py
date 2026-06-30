"""验证 graph-owner 确定性注入:叙事体抽取 + inject_owner,确认能力边补全。

接续 verify_extraction_quality 的发现:叙事体能抽出项目→技术/知识边,但缺
Person。本脚本在 add_episode 后调用 inject_owner,核对:
  - 是否建出唯一 owner Person 节点
  - owner 是否按本体连上了 Technology(USES)/Concept(UNDERSTANDS)/Project(DEMONSTRATES)
  - 二次运行是否幂等(不重复建 owner)

独立测试分区 probe_owner,跑完清理。
用法: uv run python scripts/verify_owner_injection.py [叙事体文件]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from graphiti_core.nodes import EntityNode, EpisodeType  # noqa: E402

from kg.connection import make_graphiti  # noqa: E402
from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402
from kg.owner import inject_owner  # noqa: E402

PROBE_GROUP = "probe_owner"


async def main() -> int:
    infile = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/selfdesc_narrative.txt")
    text = infile.read_text(encoding="utf-8")
    print(f"输入: {infile} ({len(text)} 字)\n")

    graphiti = make_graphiti()
    try:
        await graphiti.build_indices_and_constraints()
        print("正在抽取...")
        result = await graphiti.add_episode(
            name="verify-owner",
            episode_body=text,
            source_description="owner injection probe",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.text,
            group_id=PROBE_GROUP,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )
        print(f"抽取: {len(result.nodes)} 实体, {len(result.edges)} 边\n")

        print("注入 graph-owner...")
        owner, owner_edges = await inject_owner(graphiti, result.nodes, PROBE_GROUP)
        print(f"owner: [{','.join(owner.labels)}] {owner.name} (uuid={owner.uuid[:8]})")
        print(f"新建能力边: {len(owner_edges)}\n")

        # 名称映射,显示边端点
        name_by_uuid = {n.uuid: n.name for n in result.nodes}
        name_by_uuid[owner.uuid] = owner.name
        from collections import Counter
        by_type: Counter = Counter()
        print("=== owner 能力边 ===")
        for e in owner_edges:
            by_type[e.name] += 1
            tgt = name_by_uuid.get(e.target_node_uuid, e.target_node_uuid[:8])
            print(f"  [{e.name:13}] {owner.name} → {tgt}")
        print(f"\n边类型分布: {dict(by_type)}")

        # 幂等性:再注入一次,owner 不应重复建
        print("\n=== 幂等性检查(二次注入) ===")
        owner2, edges2 = await inject_owner(graphiti, result.nodes, PROBE_GROUP)
        same = owner2.uuid == owner.uuid
        print(f"  owner uuid 一致: {'✓' if same else '✗ 重复建了!'}")
        all_persons = [
            n for n in await EntityNode.get_by_group_ids(graphiti.driver, [PROBE_GROUP])
            if "Person" in n.labels
        ]
        print(f"  分区内 Person 节点数: {len(all_persons)} (应为 1)")

        print("\n=== 核对要点 ===")
        print("  1. owner 是否连上了全部 Technology(USES)/Concept(UNDERSTANDS)/Project(DEMONSTRATES)?")
        print("  2. 二次注入是否幂等(Person 仍为 1)?")
        return 0
    finally:
        try:
            await graphiti.driver.execute_query(
                f"MATCH (n {{group_id: '{PROBE_GROUP}'}}) DETACH DELETE n"
            )
            print(f"\n(已清理测试分区 {PROBE_GROUP})")
        except Exception as ex:
            print(f"\n(清理 {PROBE_GROUP} 失败: {ex})")
        await graphiti.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
