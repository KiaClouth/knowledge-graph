"""前置实验:公式 OpenAIGenericClient(无 strict) vs 自建 ChatCompletionsClient
(strict=True),× 对话体(message) vs 叙事体(text),共 4 组对照。

这是"迁移到公式 Graphiti MCP server + 远程部署"方案的地基。两个待定开关:

  开关一 strict —— 公式 server 用的 OpenAIGenericClient 在 json_schema 模式下
    故意省略 strict:true(openai_generic_client.py:113-124)。而 dasuapi"支持
    约束解码"是在 strict=True(probe 第①档)下验证的。→ 无 strict 在 dasuapi
    上抽取质量够不够?会不会退回早期踩的 entity_name≠name 字段错位坑?
    判定:无 strict 组若字段错位/质量骤降 → 迁移须强制 strict。

  开关二 owner 注入 —— 公式实体类型内建 User/Assistant 概念,Graphiti 是为
    对话记忆设计的,预期输入是 EpisodeType.message + 显式 speaker。message 与
    text 走不同抽取 prompt(extract_message 强制"把冒号前的说话者抽成第一个
    实体、优先 speaker→target 边",extract_nodes.py:130)。→ 若喂对话体
    ("User: 我用X做了Y"),"我"=User 会不会自然成 Person,免掉 owner 注入?
    判定:message+User 组若自然产出 Person 与能力边 → 迁移后弃用 owner 注入,
    改喂对话体;否则保留 owner 注入作为兜底。

每组写独立分区(probe_gen_*),跑完清理。不需要部署远程/公式 server——本地
graphiti-core 已含 OpenAIGenericClient,直接构造对比即可。

用法:
  uv run python scripts/probe_generic_extraction.py
  # 只跑某几组(组名: gen_msg gen_text strict_msg strict_text):
  uv run python scripts/probe_generic_extraction.py gen_msg strict_msg
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from graphiti_core import Graphiti  # noqa: E402
from graphiti_core.llm_client.config import LLMConfig  # noqa: E402
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient  # noqa: E402
from graphiti_core.nodes import EpisodeType  # noqa: E402

import os  # noqa: E402

from kg.chat_completions_client import ChatCompletionsClient  # noqa: E402
from kg.connection import DEFAULT_CHAT_MODEL, _make_embedder, make_driver  # noqa: E402
from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
NARRATIVE = EXAMPLES / "narrative_self_intro.txt"          # 叙事体(text)
CONVERSATIONAL = EXAMPLES / "conversational_self_intro.txt"  # 对话体(message, 每行 "User: …")

CAPABILITY_EDGES = {"HAS_SKILL", "UNDERSTANDS"}


def _llm_config() -> LLMConfig:
    """与 connection._make_llm_client 同源的 dasuapi 配置。small_model 兜底到主
    模型(公式 generic client 其实忽略 size 恒用主模型,但自建 client 会按 size
    切,故仍显式 pin,避免落到 gpt-4.1-nano 触发 503)。"""
    main_model = os.environ.get("OPENAI_MODEL", DEFAULT_CHAT_MODEL)
    return LLMConfig(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        model=main_model,
        small_model=os.environ.get("OPENAI_SMALL_MODEL", main_model),
    )


def _make_generic_client() -> OpenAIGenericClient:
    """公式 server 走的 client:json_schema 但**无 strict**(默认)。"""
    return OpenAIGenericClient(config=_llm_config(), structured_output_mode="json_schema")


def _make_strict_client() -> ChatCompletionsClient:
    """我们自建的 client:json_schema + **strict=True**。"""
    return ChatCompletionsClient(config=_llm_config())


# 组名 -> (client 工厂, EpisodeType, 输入文件, 一句话说明)
GROUPS: dict[str, tuple] = {
    "gen_msg": (_make_generic_client, EpisodeType.message, CONVERSATIONAL,
                "公式 generic(无 strict) + 对话体(message, User speaker)"),
    "gen_text": (_make_generic_client, EpisodeType.text, NARRATIVE,
                 "公式 generic(无 strict) + 叙事体(text)"),
    "strict_msg": (_make_strict_client, EpisodeType.message, CONVERSATIONAL,
                   "自建 strict=True + 对话体(message, User speaker)"),
    "strict_text": (_make_strict_client, EpisodeType.text, NARRATIVE,
                    "自建 strict=True + 叙事体(text)"),
}


async def run_group(name: str) -> dict:
    """跑一组,返回指标 dict。异常被捕获记入 error,不中断其它组。"""
    make_client, ep_type, infile, desc = GROUPS[name]
    group_id = f"probe_gen_{name}"
    text = infile.read_text(encoding="utf-8")

    print(f"\n{'='*70}\n[{name}] {desc}")
    print(f"  输入: {infile.name} ({len(text)} 字), source={ep_type.value}")

    graphiti = Graphiti(
        graph_driver=make_driver(),
        llm_client=make_client(),
        embedder=_make_embedder(),
    )
    metrics: dict = {"name": name, "desc": desc, "error": None}
    try:
        await graphiti.build_indices_and_constraints()
        # 先清一次,避免上次残留污染幂等
        await graphiti.driver.execute_query(
            f"MATCH (n {{group_id: '{group_id}'}}) DETACH DELETE n"
        )
        print("  正在抽取...")
        result = await graphiti.add_episode(
            name=f"probe-{name}",
            episode_body=text,
            source_description="generic vs strict extraction probe",
            reference_time=datetime.now(timezone.utc),
            source=ep_type,
            group_id=group_id,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )

        # --- 节点指标 ---
        node_by_uuid = {}
        label_count: Counter = Counter()
        for n in result.nodes:
            labels = [lab for lab in n.labels if lab != "Entity"]
            label = labels[0] if labels else "Entity"
            node_by_uuid[n.uuid] = (label, n.name)
            label_count[label] += 1

        # --- 边指标 ---
        edge_type_count: Counter = Counter()
        conf_present = 0
        conf_values = []
        for e in result.edges:
            edge_type_count[e.name] += 1
            attrs = getattr(e, "attributes", {}) or {}
            conf = attrs.get("confidence")
            if conf is not None:
                conf_present += 1
                conf_values.append(conf)

        cap_edges = sum(edge_type_count[t] for t in CAPABILITY_EDGES)
        metrics.update(
            entities=len(result.nodes),
            persons=label_count.get("Person", 0),
            label_count=dict(label_count),
            edges=len(result.edges),
            edge_type_count=dict(edge_type_count),
            capability_edges=cap_edges,
            demonstrates=edge_type_count.get("DEMONSTRATES", 0),
            conf_present=conf_present,
            conf_values=conf_values,
        )

        # --- 打印本组明细 ---
        print(f"  实体({len(result.nodes)}): {dict(label_count)}")
        person_names = [nm for (lb, nm) in node_by_uuid.values() if lb == "Person"]
        print(f"  Person: {person_names or '∅'}")
        print(f"  边({len(result.edges)}): {dict(edge_type_count)}")
        conf_desc = "∅"
        if conf_values:
            conf_desc = (f"{conf_present}/{len(result.edges)} 条, "
                         f"min={min(conf_values)} max={max(conf_values)} "
                         f"avg={sum(conf_values)/len(conf_values):.2f}")
        print(f"  confidence: {conf_desc}")
        for e in result.edges:
            src = node_by_uuid.get(e.source_node_uuid, ("?", e.source_node_uuid[:8]))
            tgt = node_by_uuid.get(e.target_node_uuid, ("?", e.target_node_uuid[:8]))
            print(f"    [{e.name:12}] {src[1]} → {tgt[1]}")
    except Exception as ex:  # 记录、不中断其它组(如已知的嵌套属性崩溃)
        metrics["error"] = f"{type(ex).__name__}: {ex}"
        print(f"  ✗ 抽取失败: {metrics['error']}")
        traceback.print_exc()
    finally:
        try:
            await graphiti.driver.execute_query(
                f"MATCH (n {{group_id: '{group_id}'}}) DETACH DELETE n"
            )
            print(f"  (已清理 {group_id})")
        except Exception as ex:
            print(f"  (清理 {group_id} 失败: {ex})")
        await graphiti.close()
    return metrics


def print_summary(results: list[dict]) -> None:
    print(f"\n\n{'#'*70}\n对照汇总\n{'#'*70}")
    header = f"{'组':12} {'实体':>4} {'Person':>7} {'边':>4} {'能力边':>7} {'DEMOS':>6} {'conf':>6}"
    print(header)
    print("-" * len(header))
    for m in results:
        if m["error"]:
            print(f"{m['name']:12} {'—— 失败: ' + m['error'][:48]}")
            continue
        print(f"{m['name']:12} {m['entities']:>4} {m['persons']:>7} {m['edges']:>4} "
              f"{m['capability_edges']:>7} {m['demonstrates']:>6} "
              f"{m['conf_present']:>6}")
    for m in results:
        if not m["error"]:
            print(f"\n[{m['name']}] 边类型: {m['edge_type_count']}")

    print(f"\n{'='*70}\n判定要点\n{'='*70}")
    print("开关一 strict:对比 gen_* 与 strict_* 同输入组。若 gen_*(无 strict)"
          "\n  实体/边骤降或 Person/能力边异常、或抽取报字段错位 → 迁移须强制 strict。")
    print("开关二 owner:对比 *_msg 与 *_text。若 *_msg(对话体+User speaker)"
          "\n  自然产出 Person(≥1) 且有能力边(HAS_SKILL/UNDERSTANDS)→ 迁移后可"
          "\n  弃用 owner 注入,改喂对话体;否则保留 owner 注入兜底。")


async def main() -> int:
    which = sys.argv[1:] or list(GROUPS.keys())
    unknown = [w for w in which if w not in GROUPS]
    if unknown:
        print(f"未知组名: {unknown}。可选: {list(GROUPS.keys())}")
        return 2
    print(f"跑 {len(which)} 组: {which}")
    results = []
    for name in which:
        results.append(await run_group(name))
    print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
