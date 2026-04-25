# ChatGPT / Claude 的 Tool 从哪来

## 1. 内置 Tool（平台自带）

ChatGPT、Claude 这类产品，官方预置了一批 Tool：

| Tool | 能力 |
|---|---|
| `web_search` | 联网搜索 |
| `code_interpreter` | 执行 Python 代码 |
| `file_read` | 读取上传的文件 |
| `image_generation` | 生成图片（DALL·E）|

你问「帮我画一张图」，它调 `image_generation`；你问「最新新闻」，它调 `web_search`。**这些 Tool 是平台工程师提前写好注册进去的，和你写 `get_error_logs` 本质完全一样。**

---

## 2. Claude Code 的 Tool（你现在用的）

Claude Code 比普通 ChatGPT 多了一批专门针对编程的 Tool：

```
Read        → 读文件
Write       → 写文件
Edit        → 修改文件
Bash        → 执行终端命令
Grep        → 搜索代码
Glob        → 查找文件
WebFetch    → 抓网页
```

你说「帮我修这个 bug」，Claude Code 在背后：

```
Thought: 先读一下文件
Action: Read("main.py")
Observation: [文件内容]
Thought: 找到问题，修改它
Action: Edit("main.py", ...)
```

**和你的日志 Agent 结构完全相同**，只是 Tool 的内容不同。

---

## 3. MCP（Model Context Protocol）— 最关键的扩展机制

这是 Anthropic 2024 年推出的标准，**解决"Tool 从哪来"的根本问题**。

核心思想：**Tool 不必内置，第三方可以按标准协议提供。**

```
你的 Claude Code
      │
      │  MCP 协议
      ├──────────→  GitHub MCP Server  （提供 create_pr、list_issues 等 Tool）
      ├──────────→  数据库 MCP Server  （提供 query_sql、list_tables 等 Tool）
      ├──────────→  Slack MCP Server   （提供 send_message、list_channels 等 Tool）
      └──────────→  你自己写的 MCP Server（任何自定义能力）
```

**类比 Java：** MCP 就像 **SPI 机制**，定义了接口标准，任何人都可以按标准实现自己的插件，框架自动发现并加载。

---

## 回到你的日志 Agent

你现在做的事，和大厂的思路完全一致：

```
大厂：内置几十个通用 Tool（搜索、代码执行、文件读写...）
你：  针对日志场景写专用 Tool（过滤、统计、根因分析...）
```

区别只是 **Tool 的数量和通用性**，架构是一样的。

日志 Agent 做到后期，也可以把它包成一个 MCP Server，让 Claude Code 直接调你的日志分析能力——这就是第四阶段进阶的方向之一。
