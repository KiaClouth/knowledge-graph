"""验证 confidence 与 DEMONSTRATES 的抽取质量。

这是晋升设计(§1.3 按风险分流)的地基验证:晋升靠两个信号——LLM 填的
edge.attributes['confidence'] 和它画的 DEMONSTRATES 证据边。本脚本喂一段
真实自述,把抽出的边连同这两个信号全部 dump 出来供人工核对它们到底准不准。

写入独立测试分区(group_id="probe_quality"),不污染 draft/canonical。
跑完默认清理该分区。

用法:
  uv run python scripts/verify_extraction_quality.py [输入文件]
  默认输入 /tmp/selfdesc.txt
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from graphiti_core.nodes import EpisodeType  # noqa: E402

from kg.connection import make_graphiti  # noqa: E402
from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402

PROBE_GROUP = "probe_quality"
CAPABILITY_EDGES = {"HAS_SKILL", "UNDERSTANDS"}  # 高风险:对外能力宣称

# 抽取引导:自述常用第三人称"他/这名开发者"泛指,缺具名主语会导致 Person 与
# 以人为中心的能力边(HAS_SKILL/UNDERSTANDS/DEMONSTRATES)整体丢失。
# 注意:add_episode 的 custom_extraction_instructions 参数在 graphiti-core
# 0.29.2 中并未被实现消费(传了无效),故改为在文本前注入一句主语锚点——这是
# 不依赖任何 API 行为、最可靠的修法。
OWNER_PREAMBLE = (
    "【说明:以下是对我本人的描述,文中的'他/这名开发者'都指我。】\n\n"
)


async def main() -> int:
    infile = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/selfdesc.txt")
    text = infile.read_text(encoding="utf-8")
    # 第二个参数 "raw" 关闭主语锚点,用于对比实验
    use_preamble = not (len(sys.argv) > 2 and sys.argv[2] == "raw")
    body = (OWNER_PREAMBLE + text) if use_preamble else text
    print(f"输入: {infile} ({len(text)} 字)")
    print(f"主语锚点: {'开' if use_preamble else '关(raw 对比)'}\n")

    graphiti = make_graphiti()
    try:
        await graphiti.build_indices_and_constraints()
        print("正在抽取...\n")
        result = await graphiti.add_episode(
            name="verify-quality",
            episode_body=body,
            source_description="extraction quality probe",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.text,
            group_id=PROBE_GROUP,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )

        # 节点:uuid -> (labels, name),供边的端点显示用
        node_by_uuid = {}
        for n in result.nodes:
            labels = [lab for lab in n.labels if lab != "Entity"]
            node_by_uuid[n.uuid] = (labels[0] if labels else "Entity", n.name)

        print(f"=== 实体 ({len(result.nodes)}) ===")
        by_label: Counter = Counter()
        for uuid, (label, name) in node_by_uuid.items():
            by_label[label] += 1
        for label, cnt in by_label.most_common():
            names = [nm for (lb, nm) in node_by_uuid.values() if lb == label]
            print(f"  {label} ({cnt}): {', '.join(names)}")

        # === 边:重点看 confidence 与类型分布 ===
        print(f"\n=== 边 ({len(result.edges)}) ===")
        edge_type_count: Counter = Counter()
        conf_present = 0
        conf_values = []
        # 收集 DEMONSTRATES 覆盖的 (target) 节点,用于判断能力边有无证据
        demonstrated_targets = set()  # 被证据指向的节点 uuid

        for e in result.edges:
            attrs = getattr(e, "attributes", {}) or {}
            conf = attrs.get("confidence")
            edge_type_count[e.name] += 1
            if conf is not None:
                conf_present += 1
                conf_values.append(conf)
            if e.name == "DEMONSTRATES":
                demonstrated_targets.add(e.target_node_uuid)

            src = node_by_uuid.get(e.source_node_uuid, ("?", e.source_node_uuid[:8]))
            tgt = node_by_uuid.get(e.target_node_uuid, ("?", e.target_node_uuid[:8]))
            conf_str = f"conf={conf}" if conf is not None else "conf=∅"
            print(f"  [{e.name:12}] {conf_str:10} {src[1]} → {tgt[1]}")
            print(f"               fact: {e.fact}")

        # === 信号一:confidence 覆盖率与分布 ===
        print(f"\n=== 信号① confidence ===")
        print(f"  覆盖: {conf_present}/{len(result.edges)} 条边有 confidence 值")
        if conf_values:
            print(f"  范围: min={min(conf_values)} max={max(conf_values)} "
                  f"avg={sum(conf_values)/len(conf_values):.2f}")
        else:
            print("  ⚠️ 没有任何边带 confidence —— 该信号不可用,晋升只能靠证据边")

        # === 信号二:能力边的证据覆盖 ===
        print(f"\n=== 信号② DEMONSTRATES 证据覆盖 ===")
        print(f"  边类型分布: {dict(edge_type_count)}")
        cap_edges = [e for e in result.edges if e.name in CAPABILITY_EDGES]
        print(f"  能力宣称边(HAS_SKILL/UNDERSTANDS): {len(cap_edges)} 条")
        auto, review = [], []
        for e in cap_edges:
            tgt_name = node_by_uuid.get(e.target_node_uuid, ("?", "?"))[1]
            has_evidence = e.target_node_uuid in demonstrated_targets
            (auto if has_evidence else review).append((e.name, tgt_name))
        print(f"  → 有证据(可自动晋升): {len(auto)}")
        for t, n in auto:
            print(f"       ✓ {t}: {n}")
        print(f"  → 无证据(需进 review 队列): {len(review)}")
        for t, n in review:
            print(f"       ⚠ {t}: {n}")

        print("\n=== 人工核对要点 ===")
        print("  1. confidence 值是否合理区分了'确凿'与'推测'?(还是全填同一个数)")
        print("  2. DEMONSTRATES 是否真的连对了'能力←证据项目/经历'?")
        print("  3. 上面被判'无证据需 review'的能力,是否确实缺项目背书?")
        return 0
    finally:
        # 清理测试分区,不留痕
        try:
            await graphiti.driver.execute_query(
                f"MATCH (n {{group_id: '{PROBE_GROUP}'}}) DETACH DELETE n"
            )
            print(f"\n(已清理测试分区 {PROBE_GROUP})")
        except Exception as ex:
            print(f"\n(清理 {PROBE_GROUP} 失败,可手动清: {ex})")
        await graphiti.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
