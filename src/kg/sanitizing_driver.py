"""写入层加固:把非原始类型的属性值扁平化,避免 Neo4j 的 Map{} 崩溃。

背景(已知限制1,见 MEMORY.md):graphiti 0.29.2 在约束解码端点下,LLM 偶尔给
实体/边的 attributes 填**嵌套对象**(如 Project.status={description:"..."})。
Neo4j 的属性只接受原始类型或其数组,遇到 Map 直接抛
  CypherTypeError: Property values can only be of primitive types or arrays
  thereof. Encountered: Map{}.
崩点在 graphiti 内部两条写路径,我方代码在 add_episode 里介入不到:
  1. 批量: utils/bulk_utils.add_nodes_and_edges_bulk_tx 把每个 node.attributes
     摊平成顶层属性(entity_data[k]=v),经 session.execute_write→tx.run 写入。
  2. 单条: nodes.EntityNode.save / edges.EntityEdge.save,经 driver.execute_query
     写入(同样把 attributes 摊平成顶层属性)。

治本策略(方案里点名的"包 driver 写入层扁平化非原始值"):在 Neo4j 驱动的
**写入边界**拦截所有查询参数,把任何 dict / 含 dict 的 list 属性值 JSON 序列化
成字符串。这样:
  - 嵌套属性不再让整次摄入崩溃(间歇性打断彻底消除);
  - 序列化后的值反而更贴合本体(status 本就该是 str),读回是 JSON 字符串;
  - 不改动 vendored graphiti_core,升级安全(纯子类覆盖 + 会话代理)。

只对 Neo4j(本项目唯一后端)。原始类型 / 数组 / 向量(name_embedding 是
float 列表)/ datetime 全部原样透传,只有 Map 型值被序列化。
"""

from __future__ import annotations

import json
from typing import Any

from graphiti_core.driver.neo4j_driver import Neo4jDriver


def _flatten_value(v: Any) -> Any:
    """单个属性值:若是 Map(dict) 或含 dict 的数组,JSON 序列化成字符串;否则原样。

    ensure_ascii=False 保留中文可读;default=str 兜底 datetime 等嵌套非 JSON 原生类型。
    """
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, list) and any(isinstance(x, dict) for x in v):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def _sanitize_param(value: Any) -> Any:
    """清洗单个查询参数。

    参数可能是:
      - 属性 map(节点/边的 entity_data,或 execute_query 的 params 字典)→ 扁平化其每个值;
      - 属性 map 的列表(批量写的 nodes / entity_edges / episodes)→ 逐个清洗;
      - 其它(字符串/数字/向量/datetime/纯量列表)→ 原样。
    只下探一层:map 的**值**若是嵌套 Map 才序列化,map 本身保持为 map
    (Cypher 的 SET n = $entity_data 需要它仍是 map)。
    """
    if isinstance(value, dict):
        return {k: _flatten_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_param(x) if isinstance(x, dict) else x for x in value]
    return value


def _sanitize_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """清洗一组 query 参数(execute_query 的 **kwargs 或 tx.run 的 **kwargs)。

    'params' 是 Neo4j execute_query 的参数容器(dict),需下探清洗其内容;
    其它 kwargs(如 entity_data=…, nodes=…, entity_edges=…)是查询参数本身。
    database_ 等控制项不是 map,原样透传。
    """
    out: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k == "params" and isinstance(v, dict):
            out[k] = {pk: _sanitize_param(pv) for pk, pv in v.items()}
        else:
            out[k] = _sanitize_param(v)
    return out


class _SanitizingTx:
    """代理 Neo4j 事务:run() 前清洗 kwargs。用于批量写路径(execute_write)。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def run(self, query: str, **kwargs: Any) -> Any:
        return await self._inner.run(query, **_sanitize_kwargs(kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _SanitizingSession:
    """代理 Neo4j 会话:execute_write 把事务包成 _SanitizingTx;run 也清洗。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def execute_write(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        async def wrapped(tx: Any, *a: Any, **k: Any) -> Any:
            return await func(_SanitizingTx(tx), *a, **k)

        return await self._inner.execute_write(wrapped, *args, **kwargs)

    async def execute_read(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.execute_read(func, *args, **kwargs)

    async def run(self, query: str, **kwargs: Any) -> Any:
        return await self._inner.run(query, **_sanitize_kwargs(kwargs))

    async def close(self) -> None:
        await self._inner.close()

    async def __aenter__(self) -> "_SanitizingSession":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._inner.__aexit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class SanitizingNeo4jDriver(Neo4jDriver):
    """Neo4jDriver + 写入边界扁平化非原始属性值,规避嵌套属性 Map{} 崩溃。

    覆盖两个入口:
      - execute_query: 单条 save / 各类查询(清洗 params 与额外 kwargs);
      - session:       批量写(execute_write→tx.run,经 _SanitizingSession 代理)。
    """

    async def execute_query(self, cypher_query_: Any, **kwargs: Any) -> Any:
        return await super().execute_query(cypher_query_, **_sanitize_kwargs(kwargs))

    def session(self, database: str | None = None) -> Any:
        return _SanitizingSession(super().session(database))
