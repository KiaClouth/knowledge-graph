"""演示用端到端摄入:叙事体样本 → 抽取 → 注入 graph-owner → 落 demo 分区。

与 smoke_ingest 的区别:这个会调用 inject_owner 补全"人—能力—证据"边,并把
数据**持久化**在 demo 分区(不清理),供 visualize_graph.py 可视化查看。

用法: uv run python scripts/demo_ingest.py [叙事体文件]
默认输入 /tmp/selfdesc_narrative.txt,默认写入 group_id=demo(先清空该分区)。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from graphiti_core.nodes import EpisodeType  # noqa: E402

from kg.connection import make_graphiti  # noqa: E402
from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402
from kg.owner import inject_owner  # noqa: E402

DEMO_GROUP = "demo"
DEFAULT_SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "narrative_self_intro.txt"


async def main() -> int:
    infile = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE
    text = infile.read_text(encoding="utf-8")
    print(f"输入: {infile} ({len(text)} 字) → 分区 {DEMO_GROUP}\n")

    graphiti = make_graphiti()
    try:
        await graphiti.build_indices_and_constraints()

        # 幂等演示:先清空 demo 分区,避免重复累积
        await graphiti.driver.execute_query(
            f"MATCH (n {{group_id: '{DEMO_GROUP}'}}) DETACH DELETE n"
        )

        print("抽取中...")
        result = await graphiti.add_episode(
            name="demo-ingest",
            episode_body=text,
            source_description="demo narrative self-intro",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.text,
            group_id=DEMO_GROUP,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )
        print(f"  抽取: {len(result.nodes)} 实体, {len(result.edges)} 边")

        owner, owner_edges = await inject_owner(graphiti, result.nodes, DEMO_GROUP)
        print(f"  注入 owner: {owner.name} + {len(owner_edges)} 条能力边")

        print(f"\n完成。可视化: uv run python scripts/visualize_graph.py {DEMO_GROUP}")
        return 0
    finally:
        await graphiti.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
