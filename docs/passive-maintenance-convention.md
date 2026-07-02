# 知识图谱被动维护约定（跨 agent 通用）

把下面「约定正文」整段复制进任意 agent 的规则文件即可让它被动维护知识图谱：
Claude Code → `CLAUDE.md`；Cursor → `.cursorrules`；Windsurf → rules；
其它 client → 各自的 system/rules 位置。正文刻意不依赖任何单一平台的特性。

前提：该 agent 已连接本项目的 `kg` MCP server（提供 `add_memory` / `search_nodes`
等工具）。约定只规定「何时写、以什么形态写」；「写得好不好」由 server 端的
instructions 与 `add_memory` docstring 兜底（二者已内置同样的形态铁律）。

---

## 约定正文（复制以下整段）

<knowledge-graph-passive-maintenance>
你可访问一个名为 `kg` 的知识图谱记忆服务（MCP），记录图谱主人「会什么、懂什么、
做过什么」。在正常对话中，当主人透露了值得长期沉淀的能力/经历信息时，你应**主动**
调用 `kg` 的 `add_memory` 把它写入，无需等待明确指令。这叫被动维护。

### 何时写
满足以下任一，且是关于**图谱主人本人**的、较稳定的事实时写入：
- 主人陈述自己做过的项目、产品、工程（"我做了/写了/搭了 X"）。
- 主人陈述掌握或使用的技术、工具、框架、语言。
- 主人陈述理解的概念/知识领域，或从某段经历中获得的理解。
- 主人陈述的角色、职位、就职/求学经历。

**不要写**：一次性的操作请求、调试细节、临时状态、闲聊、关于第三方而非主人的信息、
你不确定是否属实或是否该长期保留的内容。存疑就不写——宁可漏，不可污染。

### 怎么写（形态决定抽取质量，务必遵守）
- `source="message"`，`episode_body` 用**第一人称对话体**，且以**固定 speaker 前缀**开头：
  `"KiaClouth: 我用 <技术> 做了 <项目>，……"`。speaker 前缀是主人被抽成 Person 锚点、
  并长出能力边（USES/UNDERSTANDS/DEMONSTRATES）的关键。用 `text` 或第三人称叙述会导致
  **没有 Person 节点、没有能力边**。
- 写成**叙事体**——"我用 X 做了 Y，它让我更懂 Z"——**不要**写成能力罗列"我精通 X"。
  叙事体才产出带 confidence 的 BUILT_WITH/DEMONSTRATES 边；罗列体只塌缩成无价值的
  RELATES_TO。
- **speaker 恒为 `KiaClouth`**，跨所有 agent、所有 episode 都用这一个。换名会新建一个
  不与既有主人节点合并的 Person 节点。
- **`group_id="draft"`**。自动写入一律落 draft 分区，由人工晋升到 canonical。
  **绝不直接写 canonical。**
- 一次 `add_memory` 只承载一个连贯主题；主人一段话涉及多个不相关项目时可拆成多条。
- `name` 给一个简短可辨识的标题（如 `"rgrep CLI 项目"`），`source_description` 标明
  来源（如 `"对话中的自述"`）。

### 写入后
- `add_memory` 是异步入队，立即返回、后台抽取，不要因为"没马上查到"而重复写。
- 不必向主人复述你写了什么流水账；简短确认即可（如"已记入图谱 draft"）。若主人表示
  不必记录，则尊重并跳过。

### 一个合规调用示例
add_memory(
  name="rgrep CLI 项目",
  episode_body="KiaClouth: 我用 Rust 写了个命令行工具 rgrep，类似 ripgrep 的高性能
    文本搜索器。用 clap 做参数解析，rayon 做多线程并行。做这个让我对并发和内存安全
    理解更深了。",
  source="message",
  source_description="对话中的自述",
  group_id="draft"
)
</knowledge-graph-passive-maintenance>

---

## 备注

- **speaker 已锁定为 `KiaClouth`**。若日后要改，必须同时改三处并做数据迁移：本文件、
  server 端 `graphiti_mcp_server.py` 的 instructions/docstring、以及所有已分发的 agent
  规则文件——否则会产生不合并的重复 Person 节点。
- 该约定与 server 端形态铁律**内容一致、互为冗余**：agent 端约定负责「主动写 + 落
  draft」，server 端负责「任何 client 接入都被告知正确形态」。两层都在，换一个没读过
  本约定的 agent 直接连 server 也不会写坏形态。
- draft → canonical 的人工晋升是刻意的质量闸门，被动维护只负责喂 draft。
