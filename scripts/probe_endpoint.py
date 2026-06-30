"""端点能力探测:在跑 add_episode 之前,分别单独验证"对话"和"嵌入"两种能力。

为什么单独探测:Graphiti 的 add_episode 会一次性用到 LLM + embedder,若其中一项
端点不支持,报错会混在抽取流程里,既费 key 又难定位。本脚本各打一个最小请求,
分别报告通/不通、用的哪个端点与模型。

配置来源(均读自 .env):
  对话  : OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
  嵌入  : EMBEDDER_API_KEY / EMBEDDER_BASE_URL / EMBEDDER_MODEL
          (留空则分别回退到对话的 KEY / BASE_URL)

运行: uv run python scripts/probe_endpoint.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"


def _mask(key: str | None) -> str:
    if not key:
        return "(未设置)"
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "(已设置)"


async def probe_chat() -> bool:
    from openai import AsyncOpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    model = os.environ.get("OPENAI_MODEL", DEFAULT_CHAT_MODEL)
    print(f"[对话] key={_mask(api_key)}  base_url={base_url or '(官方默认)'}  model={model}")
    if not api_key:
        print("[对话] 跳过:OPENAI_API_KEY 未设置")
        return False
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "reply with the single word: ok"}],
            max_tokens=5,
        )
        text = (resp.choices[0].message.content or "").strip()
        print(f"[对话] ✓ 成功,返回: {text!r}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[对话] ✗ 失败: {type(e).__name__}: {e}")
        return False


async def probe_embeddings() -> bool:
    from openai import AsyncOpenAI

    api_key = os.environ.get("EMBEDDER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("EMBEDDER_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or None
    model = os.environ.get("EMBEDDER_MODEL", DEFAULT_EMBED_MODEL)
    print(f"[嵌入] key={_mask(api_key)}  base_url={base_url or '(官方默认)'}  model={model}")
    if not api_key:
        print("[嵌入] 跳过:无可用 key")
        return False
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.embeddings.create(model=model, input="hello")
        dim = len(resp.data[0].embedding)
        print(f"[嵌入] ✓ 成功,向量维度: {dim}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[嵌入] ✗ 失败: {type(e).__name__}: {e}")
        return False


async def main() -> int:
    print("=== 端点能力探测 ===\n")
    chat_ok = await probe_chat()
    print()
    embed_ok = await probe_embeddings()
    print("\n=== 结论 ===")
    print(f"对话能力: {'可用' if chat_ok else '不可用'}")
    print(f"嵌入能力: {'可用' if embed_ok else '不可用'}")
    if chat_ok and embed_ok:
        print("两项都通过 —— 可以进入 add_episode 抽取步骤。")
        return 0
    if chat_ok and not embed_ok:
        print("对话通、嵌入不通 —— 在 .env 里把 EMBEDDER_BASE_URL/KEY/MODEL")
        print("指向一个提供嵌入的端点(如 OpenAI 官方),再重跑本脚本。")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
