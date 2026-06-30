# 架构设计：对外接口与数据流

> 状态：设计稿（未实现）。本文件定清楚"对外提供什么"和"被动维护如何落地",
> 作为后续编码的依据。已实现部分仅为摄入管线(`add_episode` → Neo4j `draft`)。

## 0. 一句话

本项目对外提供的是一个 **"个人能力记忆" MCP server**:别的 agent 通过它
**写入**(把对话沉淀进图)和**读取**(查询"我会什么/懂什么/凭什么")。底层
Neo4j 不对外暴露。

---

## 1. 对外提供什么

对外只有一个产物:**一个 MCP server**,暴露两类工具。

| 工具 | 方向 | 作用 | 落点 |
| --- | --- | --- | --- |
| `remember(text, source, occurred_at?)` | 写 | 把一段对话/事实摄入,自动抽取实体与关系 | `draft` 分区 |
| `recall(query, ...)` | 读 | 检索能力/知识/证据,供求职或对接 agent 时引用 | `canonical` 分区(默认) |

设计原则:
- **写读分区不同**。`remember` 永远只写 `draft`(全自动、可能有噪音);
  `recall` 默认只读 `canonical`(已晋升、对外可信)。这把"自动维护"与
  "对外可信"用 `group_id` 物理隔开,呼应需求2。
- **MCP server 不做晋升**。draft→canonical 的晋升是**独立 CLI/后台逻辑**,
  不在 server 里(server 要能全自动运行)。
- **晋升默认自动、按风险分流**(见 §1.3,这是对"人工确认"的关键修正)。
- **底层不可读不要紧**(需求3)。`recall` 返回的是结构化检索结果,不是给
  人读 Neo4j。面向人的"分层呈现/可视化"(需求4)是另一层,押后。

### 1.1 `remember` 契约(草案)

```
remember(
  text: str,              # 要记住的内容(一段对话、一条自述)
  source: str,            # 来源标识,如 "claude-code" / "chatgpt-export"
  occurred_at?: str,      # ISO8601;缺省用当前时间
) -> { episode_id, extracted: {entities: [...], edges: [...]} }
```
内部即调用现有 `add_episode(group_id="draft", entity_types=..., edge_types=...,
edge_type_map=...)`。返回抽取摘要,让调用方/用户能立即看到记了什么。

### 1.2 `recall` 契约(草案)

```
recall(
  query: str,             # 自然语言,如 "这个人会哪些前端技能"
  partition?: str,        # 默认 "canonical";调试可传 "draft"
  edge_types?: [str],     # 可选,按边类型过滤(见下)
  limit?: int,
) -> { facts: [{fact, edge_type, source_node, target_node, valid_at, episodes}] }
```
底层用 Graphiti 的 `search` / `search_`(混合检索:向量+全文+图)。

**"我会什么 / 懂什么 / 凭什么" 直接映射到本体的边:**
- *我会什么* → `HAS_SKILL` 边(Person→Skill)
- *我懂什么* → `UNDERSTANDS` 边(Person→Concept)
- *我用什么* → `USES` 边(Person/Project→Technology)
- *凭什么(证据)* → `DEMONSTRATES` 边(Project/Experience→Skill/Concept)。
  这是求职可信度的核心:一项能力背后挂着哪个项目/经历作证。

`recall` 的一个高价值预设查询:给定一个 Skill/Concept,沿 `DEMONSTRATES`
反查支撑它的 Project/Experience,即"凭什么"。

### 1.3 晋升策略:默认自动、按风险分流(对"人工确认"的关键修正)

**问题**:若 canonical 只能靠逐条人工晋升填充,那它在你做完大量枯燥 review
前就是空的、没用的——晋升变成永远还不完的家务,体验很差。

**澄清两个被混淆的概念**:
- *何时确认* —— `remember` 写 draft 立即返回,**从不在对话中阻塞**。确认这件
  事永远是**异步、批量、按你的节奏**(如投简历前过一遍 / 每周一次),决不
  实时、决不每次对话后。
- *确认什么* —— 当初"错配能力比漏记更糟"的论据,**只对'对外的能力宣称'成立**
  (`HAS_SKILL`/`UNDERSTANDS`)。技术节点、`USES`/`BUILT_WITH` 这类客观事实
  低风险、无争议,不值得占用你的注意力。

**策略:大部分自动晋升,只有高风险能力宣称进 review 队列。** 用本体里已设计、
但尚未启用的 `confidence` 字段 + `DEMONSTRATES` 证据边做分流:

| 事实类别 | 处理 | 理由 |
| --- | --- | --- |
| Technology 节点;`USES`/`BUILT_WITH`/`PART_OF`/`RELATES_TO` 边 | **自动晋升** | 低风险、客观 |
| `HAS_SKILL`/`UNDERSTANDS` 且**有 `DEMONSTRATES` 证据支撑** | **自动晋升** | 有项目/经历背书,可信 |
| `HAS_SKILL`/`UNDERSTANDS` 但**无证据 或 confidence 低** | **进 review 队列** | 正是"自吹"风险所在 |

结果:绝大多数时候零确认;review 队列只剩少量"无证据的能力宣称"——恰好是求职
场景下最该你亲自把关的几条。家务量从"每条都看"降到"偶尔扫几条可疑的"。

**风险(实现前必须验证)**:此策略依赖 LLM 填的 `confidence` 和它画的
`DEMONSTRATES` 边是否可靠,目前**未验证**。跑通后应用真实数据观察抽取质量
再定阈值。若 `confidence` 不可信,退而用"有无证据边"这个更硬的信号兜底。

---

## 2. 被动维护如何落地

**关键认知:"被动维护"分两档,做不到所有平台都全自动。**

### A 档 · 能挂工具的平台(Claude Code、Codex)→ 接近全自动

- 给平台挂上本 MCP server,`remember` 工具即可用。
- 但 agent 不会无故调工具。要"对话着就自动记",需在**平台侧常驻指令**里写
  触发规则,例如 Claude Code 的 `CLAUDE.md` / Codex 的 system prompt:
  > "当对话中出现用户新的技能、项目、使用的技术或表达出的理解时,调用
  > `remember` 工具记录,source 填本平台名。"
- 因此本质是 **"配置一次指令 → 之后对话即自动触发"**,而非 100% 无感。

### B 档 · 纯网页平台(ChatGPT / Perplexity / Gemini web)→ 只能事后批量

- 这些平台挂不了工具,对话当下无法写图。
- 唯一路径:**定期导出聊天记录 → 平台专属解析器转成 Episode → 喂同一管线**。
- 这是偏手动的一档:导出动作需用户做,解析+导入可一条命令搞定。

### 两档归一

```
A 档: agent --(MCP remember)--> ┐
                                ├─→ 统一管线 ─→ draft ──(人工晋升 CLI)──→ canonical
B 档: 导出文件 --(解析器)--> Episode ┘                                         │
                                                                    recall 读这里 ◄┘
```
统一管线 = dedup 闸门(`content_hash`) → Graphiti 抽取+实体消解 → 写 `draft`。

---

## 3. 数据流全景

```
┌─────────────┐   ┌──────────────┐
│ A: MCP 写入 │   │ B: 导出解析  │
│ remember()  │   │ adapters/*   │
└──────┬──────┘   └──────┬───────┘
       │   归一为 Episode  │
       └────────┬─────────┘
                ▼
       ┌─────────────────┐
       │ dedup(content_  │  同一段内容不重复摄入
       │   hash 闸门)     │
       └────────┬────────┘
                ▼
       ┌─────────────────┐
       │ Graphiti        │  add_episode + 锁定本体
       │ 抽取/消解/写入   │  (主模型 gpt-5.4, small_model 兜底)
       └────────┬────────┘
                ▼
          [ draft 分区 ]
                │
       ┌────────┴─────────────┐
       │ 晋升:按风险分流       │  低风险事实 + 有证据的能力 → 自动晋升
       │ draft → canonical    │  无证据/低 confidence 的能力宣称 → review 队列
       └────────┬─────────────┘
                ▼
        [ canonical 分区 ] ◄──── recall() 默认读这里
                │
       ┌────────┴────────┐
       │ (押后)呈现层     │  分层:① 可读文档 ② 可视化/建站
       └─────────────────┘
```

---

## 4. 组件清单与现状

| 组件 | 状态 | 说明 |
| --- | --- | --- |
| 摄入管线(`add_episode`→draft) | ✅ 已实现 | `connection.py` + `smoke_ingest.py` 验证通 |
| 锁定本体(7 实体/7 边) | ✅ 已实现 | `ontology.py` |
| 约束解码端点适配 | ✅ 已实现 | `chat_completions_client.py` + probe |
| **MCP server(`remember`/`recall`)** | ⬜ 待做 | **对外接口,当前完全缺失** |
| 晋升逻辑(按风险分流,自动+review 队列) | ⬜ 待做 | 默认自动晋升;只有无证据的能力宣称需人工 |
| 导出解析器(每平台一个 adapter) | ⬜ 待做 | B 档摄入 |
| 呈现层(文档/可视化) | ⬜ 押后 | 需求4,分两层 |
| 平台侧触发指令(CLAUDE.md 等) | ⬜ 待做 | A 档"被动"的关键,属配置非代码 |

---

## 5. 待定决策(实现前需拍板)

1. **MCP server 用什么写?** Python FastMCP(与现有 `src/kg` 同栈,直接复用
   `make_graphiti()`,首选) vs 其他。
2. **`remember` 是否同步返回抽取结果?** 同步等抽取完会慢几秒(多次 LLM 调用);
   可选异步(先回执、后台抽取)。先做同步,简单。
3. **dedup 粒度**:`content_hash` 按整段还是按句?先整段。
4. **晋升分流的判定信号**(§1.3):优先用 `DEMONSTRATES` 证据边(硬信号),
   `confidence` 阈值为辅(软信号,需先验证可靠性)。具体阈值跑真实数据后定。
5. **review 队列的形态**:进队列的只是少量"无证据能力宣称"。逐条 review
   (批准→晋升 / 拒绝→留 draft 或删 / 补证据)。形态待定:CLI 交互式 vs
   生成一份待办清单让你勾选。
6. **`recall` 默认只读 canonical**:但 canonical 为空时是否回退读 draft?
   倾向不回退,显式提示"尚无 canonical 数据"。

---

## 6. 建议的实现顺序

先做**最小 MCP server(仅 `remember` 直写 draft)**:它让你能立刻在 Claude Code
挂上,形成"对话→入图"闭环、最早看到价值;`recall` 和晋升 CLI 随后。理由:先有
对外接口,跨平台才谈得上;晋升 CLI 虽在路线图靠前,但它不产生任何对外可用能力。
