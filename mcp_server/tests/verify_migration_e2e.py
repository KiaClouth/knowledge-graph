"""端到端验证:通过公式 MCP server 的服务层跑通 add_memory + search。

不走 MCP 网络协议(那是 transport 层),而是直接驱动 server 的 GraphitiService
——它内部经工厂造 LLM/embedder/driver,正好覆盖我们的两个补丁:
  1. factories 强制 strict:非官方端点(dasuapi)返回 ChatCompletionsClient(strict=True);
  2. graphiti_mcp_server Neo4j 分支用 SanitizingNeo4jDriver(规避嵌套属性 Map{} 崩溃)。

并验证迁移开关二:喂对话体(EpisodeType.message,"User: 我用X做了Y")能否**原生**
产出 Person + 能力边(免 owner 注入)。

流程:GraphitiService.initialize() → client.add_episode(message 对话体,写独立测试
分区)→ search_nodes / search_memory_facts 读回 → 打印实体/边/Person/能力边指标 →
清理测试分区。

前置:Neo4j 在跑;仓库根 .env 已配 dasuapi + 智谱;CONFIG_PATH 指向 config.kg.yaml。
用法(从 mcp_server 目录):
  cd ~/code/knowledge-graph && set -a && . ./.env && set +a && cd mcp_server \
    && CONFIG_PATH=config/config.kg.yaml uv run --project .. python tests/verify_migration_e2e.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# server 源码在 mcp_server/src
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from graphiti_core.nodes import EpisodeType  # noqa: E402

from config.schema import GraphitiConfig  # noqa: E402
from graphiti_mcp_server import GraphitiService  # noqa: E402
from kg.chat_completions_client import ChatCompletionsClient  # noqa: E402
from kg.sanitizing_driver import SanitizingNeo4jDriver  # noqa: E402

TEST_GROUP = "probe_migration_e2e"
SAMPLE = (
    Path(__file__).resolve().parent.parent.parent
    / "examples"
    / "conversational_self_intro.txt"
)
CAPABILITY_EDGES = {"HAS_SKILL", "UNDERSTANDS"}


async def main() -> int:
    text = SAMPLE.read_text(encoding="utf-8")
    print(f"输入: {SAMPLE.name} ({len(text)} 字), source=message(对话体)\n")

    cfg = GraphitiConfig()
    service = GraphitiService(cfg, semaphore_limit=6)
    await service.initialize()
    client = await service.get_client()

    # --- 确认两个补丁真的生效(而非退回公式默认) ---
    llm_ok = isinstance(client.llm_client, ChatCompletionsClient)
    drv_ok = isinstance(client.driver, SanitizingNeo4jDriver)
    print(f"补丁① LLM = {type(client.llm_client).__name__} "
          f"(strict ChatCompletionsClient: {'✓' if llm_ok else '✗'})")
    print(f"补丁② driver = {type(client.driver).__name__} "
          f"(SanitizingNeo4jDriver: {'✓' if drv_ok else '✗'})\n")

    try:
        # 先清测试分区,避免残留
        await client.driver.execute_query(
            f"MATCH (n {{group_id: '{TEST_GROUP}'}}) DETACH DELETE n"
        )

        print("摄入(add_episode, message 对话体)...")
        result = await client.add_episode(
            name="verify-migration",
            episode_body=text,
            source_description="migration e2e probe",
            source=EpisodeType.message,
            group_id=TEST_GROUP,
            reference_time=datetime.now(timezone.utc),
            entity_types=service.entity_types,
            edge_types=service.edge_types,
            edge_type_map=service.edge_type_map,
        )

        # --- 摄入指标 ---
        label_count: Counter = Counter()
        persons = []
        for n in result.nodes:
            labels = [lab for lab in n.labels if lab != "Entity"]
            label = labels[0] if labels else "Entity"
            label_count[label] += 1
            if label == "Person":
                persons.append(n.name)
        edge_count: Counter = Counter()
        conf_present = 0
        for e in result.edges:
            edge_count[e.name] += 1
            attrs = getattr(e, "attributes", {}) or {}
            if attrs.get("confidence") is not None:
                conf_present += 1
        cap_edges = sum(edge_count[t] for t in CAPABILITY_EDGES)

        print(f"\n=== 摄入结果 ===")
        print(f"  实体({len(result.nodes)}): {dict(label_count)}")
        print(f"  Person: {persons or '∅'}")
        print(f"  边({len(result.edges)}): {dict(edge_count)}")
        print(f"  能力边(HAS_SKILL/UNDERSTANDS): {cap_edges}")
        print(f"  DEMONSTRATES: {edge_count.get('DEMONSTRATES', 0)}")
        print(f"  confidence 覆盖: {conf_present}/{len(result.edges)}")

        # --- search_nodes 路径(client.search_) ---
        from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF
        from graphiti_core.search.search_filters import SearchFilters

        node_res = await client.search_(
            query="前端 技术栈",
            config=NODE_HYBRID_SEARCH_RRF,
            group_ids=[TEST_GROUP],
            search_filter=SearchFilters(),
        )
        print(f"\n=== search_nodes('前端 技术栈') ===")
        print(f"  命中 {len(node_res.nodes)} 节点: "
              f"{[n.name for n in node_res.nodes[:8]]}")

        # --- search_memory_facts 路径(client.search) ---
        facts = await client.search(
            query="用什么技术做了什么",
            group_ids=[TEST_GROUP],
            num_results=8,
        )
        print(f"\n=== search_memory_facts('用什么技术做了什么') ===")
        print(f"  命中 {len(facts)} 条事实:")
        for e in facts[:8]:
            print(f"    [{e.name}] {e.fact}")

        # --- 判定 ---
        print(f"\n=== 判定 ===")
        ok_person = len(persons) >= 1
        ok_cap = cap_edges >= 1
        ok_search = len(node_res.nodes) >= 1 and len(facts) >= 1
        print(f"  {'✓' if llm_ok else '✗'} strict 补丁生效(无 Map{{}} 崩溃即证 driver 补丁也在)")
        print(f"  {'✓' if ok_person else '✗'} 对话体原生产出 Person(免 owner 注入)")
        print(f"  {'✓' if ok_cap else '✗'} 原生产出能力边")
        print(f"  {'✓' if ok_search else '✗'} search_nodes / search_memory_facts 可读回")
        all_ok = llm_ok and drv_ok and ok_person and ok_cap and ok_search
        print(f"\n{'✅ 迁移本地跑通' if all_ok else '⚠️ 有未通过项,见上'}")
        return 0 if all_ok else 1
    finally:
        try:
            await client.driver.execute_query(
                f"MATCH (n {{group_id: '{TEST_GROUP}'}}) DETACH DELETE n"
            )
            print(f"\n(已清理测试分区 {TEST_GROUP})")
        except Exception as ex:
            print(f"\n(清理 {TEST_GROUP} 失败: {ex})")
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
