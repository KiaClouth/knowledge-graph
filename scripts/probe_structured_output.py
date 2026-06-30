"""结构化输出能力探针 —— 判定一个 OpenAI 兼容对话端点能否喂给 Graphiti。

背景:Graphiti 抽取实体时,要求模型严格按它给的 JSON schema 返回一个**顶层对象**
(形如 {"extracted_entities": [...]}),然后执行 ExtractedEntities(**llm_response)。
若模型返回数组、或字段名/结构不符,就会崩。所以"能返回合法 JSON"不够,必须
"严格遵守指定 schema"。本脚本检验后者。

测三档(从强到弱),对每档判定是否真正符合 schema:
  1. json_schema + strict   —— Graphiti 最需要的能力
  2. json_object            —— 仅保证合法 JSON,不保证结构
  3. 裸 prompt(无 response_format)—— 兜底连通性参照

判定标准(模拟 Graphiti 的真实期望):
  顶层必须是 dict,且含 key "extracted_entities",其值为 list。

用法:
  # 默认读 .env 的 OPENAI_* 配置:
  uv run python scripts/probe_structured_output.py
  # 或显式覆盖,方便快速试不同中转(命令行优先于 .env):
  uv run python scripts/probe_structured_output.py \\
      --base-url https://xxx/v1 --api-key sk-xxx --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# 模拟 Graphiti ExtractedEntities 的目标结构
TARGET_SCHEMA = {
    "type": "object",
    "properties": {
        "extracted_entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type": {"type": "string"},
                },
                "required": ["name", "entity_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["extracted_entities"],
    "additionalProperties": False,
}

PROMPT = (
    # 故意不描述输出结构/字段名,以真正检验"服务器端约束解码(constrained
    # decoding)"能力:真支持 Structured Outputs 的端点仅凭 json_schema 就能强制
    # 出正确结构与字段名;只是"透传"参数的端点会返回散文/Markdown/乱字段名。
    "从下面这句话中抽取所有提到的实体(技术、职业、项目等)。\n"
    "句子:我是一名前端工程师,主要用 TypeScript 和 SolidJS 构建界面。"
)


def _verdict(content: str) -> tuple[bool, str]:
    """判断返回内容是否满足 Graphiti 的结构期望。"""
    try:
        obj = json.loads(content)
    except Exception as e:  # noqa: BLE001
        return False, f"不是合法 JSON: {e}"
    if isinstance(obj, list):
        return False, "顶层是数组(list),Graphiti 期望对象(dict) → 会崩"
    if not isinstance(obj, dict):
        return False, f"顶层是 {type(obj).__name__},期望 dict"
    if "extracted_entities" not in obj:
        return False, f"缺少键 extracted_entities;实际键: {list(obj.keys())}"
    if not isinstance(obj["extracted_entities"], list):
        return False, "extracted_entities 不是数组"
    return True, f"符合 schema,抽到 {len(obj['extracted_entities'])} 个实体"


async def _try(client, model, response_format, label):
    print(f"\n=== {label} ===")
    kwargs = dict(model=model, messages=[{"role": "user", "content": PROMPT}], max_tokens=400)
    if response_format is not None:
        kwargs["response_format"] = response_format
    try:
        r = await client.chat.completions.create(**kwargs)
        content = r.choices[0].message.content or ""
        print(f"原始返回: {content[:200]}")
        ok, reason = _verdict(content)
        print(f"判定: {'✓ 通过' if ok else '✗ 不符'} —— {reason}")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"请求失败: {type(e).__name__}: {str(e)[:200]}")
        return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    ap.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    args = ap.parse_args()

    if not args.api_key:
        print("缺少 api key(--api-key 或 .env 的 OPENAI_API_KEY)")
        return 2

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=args.api_key, base_url=args.base_url or None)
    print("=" * 56)
    print("Graphiti 端点适配性检测")
    print(f"  端点: {args.base_url or '(OpenAI 官方默认)'}")
    print(f"  模型: {args.model}")
    print("=" * 56)
    print(
        "说明:Graphiti 抽取依赖『服务器端约束解码』(传 schema 后 API 强制\n"
        "      输出合规)。下面第①档是决定性检验,②③仅供参考。"
    )

    schema_ok = await _try(
        client,
        args.model,
        {
            "type": "json_schema",
            "json_schema": {"name": "ExtractedEntities", "schema": TARGET_SCHEMA, "strict": True},
        },
        "① json_schema strict  【决定性 · 只看这档】",
    )
    object_ok = await _try(
        client, args.model, {"type": "json_object"}, "② json_object        (参考,不影响结论)"
    )
    await _try(client, args.model, None, "③ 裸 prompt          (参考,连通性)")

    print("\n" + "█" * 56)
    if schema_ok:
        print("结论:✅  可用 —— 该端点真正支持约束解码,能可靠喂 Graphiti。")
        print("下一步:把 .env 的 OPENAI_BASE_URL/KEY/MODEL 指向它,跑 smoke_ingest.py。")
    else:
        why = "仅返回合法 JSON 但结构自创" if object_ok else "返回散文/Markdown,无视 schema"
        print("结论:❌  不可用 —— 该端点只是『透传』schema 参数、不做约束解码")
        print(f"        (第①档{why})。换别的端点再测。")
        print("提示:OpenAI 官方必过;国产可试 qwen-max/plus 等(需实测)。")
    print("█" * 56)
    print(f"\n(诊断细节见上方三档;判定仅取决于第①档:{'通过' if schema_ok else '未通过'})")
    return 0 if schema_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
