"""端到端冒烟测试:用锁定本体跑一次真实 add_episode,把结果写入 draft 分区。

这是第一次真正消耗 API(对话抽取 + 嵌入),但只跑一小段文本,成本极低。
跑通后你能看到:从一段自我描述里抽出了哪些实体(Skill/Concept/...)和关系。

前置:scripts/probe_endpoint.py 两项都通过;.env 里 EMBEDDER_DIM 与端点维度一致。

运行: uv run python scripts/smoke_ingest.py
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

from kg.connection import DRAFT_GROUP, make_graphiti  # noqa: E402
from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402

SAMPLE = (
    "我是一名前端工程师,主要用 TypeScript 和 SolidJS 构建界面。"
    "最近在做一个叫 ToramCalculator 的项目,用 SolidStart 和 Kysely,"
    "并且自己设计了基于 XState 的状态机架构。我对响应式编程和图数据库有比较深的理解。"
)


async def main() -> int:
    graphiti = make_graphiti()
    try:
        # 首次写入会按 embedder 维度固化 schema。
        await graphiti.build_indices_and_constraints()

        print("正在抽取(调用对话模型 + 嵌入)...")
        result = await graphiti.add_episode(
            name="smoke-self-intro",
            episode_body=SAMPLE,
            source_description="smoke test self-introduction",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.text,
            group_id=DRAFT_GROUP,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )

        print(f"\n=== 抽出的实体({len(result.nodes)}) ===")
        for n in result.nodes:
            labels = [lab for lab in n.labels if lab != "Entity"]
            print(f"  [{', '.join(labels) or 'Entity'}] {n.name}")

        print(f"\n=== 抽出的关系({len(result.edges)}) ===")
        for e in result.edges:
            print(f"  {e.name}: {e.fact}")

        print(f"\n写入分区: {DRAFT_GROUP}。冒烟测试完成。")
        return 0
    finally:
        await graphiti.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
