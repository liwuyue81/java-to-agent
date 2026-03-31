# 第三阶段代码解析：Memory 多轮对话

## 改动概览

| 文件 | 变化 |
|---|---|
| `main_stage3.py` | 新增入口，引入 Memory 和 react-chat 模板 |
| `tools/log_tools_stage2.py` | **保持不动**，复用第二阶段全部 6 个 Tool |
| `main.py` / `main_stage2.py` | **保持不动** |

---

## 第一阶段 vs 第三阶段的本质区别

**第一/二阶段：每次对话都是全新的**

```
你：今天有哪些 ERROR？
Agent：共 6 条 ERROR...

你：根因是什么？         ← 模型不记得你刚才问的是什么
Agent：请问你指的是哪条错误？  ← 无法追问
```

**第三阶段：对话历史被保存并传给模型**

```
你：今天有哪些 ERROR？
Agent：共 6 条 ERROR，主要是 DBPool 连接池耗尽...

你：根因是什么？         ← 模型记得上一轮说了 DBPool
Agent：根因是 DBPool 连接池在 08:10 就出现 80% 使用率预警，未处理导致耗尽...

你：那 WARN 呢？         ← 模型知道你还在问今天的日志
Agent：今天共 3 条 WARN...
```

---

## 核心改动逐行解析

### 改动一：换用支持多轮的 Prompt 模板

```python
# 第一/二阶段
prompt = hub.pull("hwchase17/react")

# 第三阶段
prompt = hub.pull("hwchase17/react-chat")
```

**区别是什么：**

| 模板 | 输入变量 | 适用场景 |
|---|---|---|
| `react` | `input`, `tools`, `agent_scratchpad` | 单轮问答 |
| `react-chat` | `input`, `tools`, `agent_scratchpad`, **`chat_history`** | 多轮对话 |

`react-chat` 比 `react` 多了一个 `{chat_history}` 占位符，每次发给模型的 Prompt 里会包含历史对话记录。模型看到历史，自然就能理解「根因是什么」中的「根因」指的是上一轮提到的问题。

---

### 改动二：创建 Memory 对象

```python
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
)
```

**`ConversationBufferMemory` 是什么：**

最简单的 Memory 类型，把每一轮对话原文完整保存，类比数据库里不做任何处理直接存全量日志。

```
第1轮后 memory 里存着：
  Human: 今天有哪些 ERROR？
  AI: 共 6 条 ERROR...

第2轮后 memory 里存着：
  Human: 今天有哪些 ERROR？
  AI: 共 6 条 ERROR...
  Human: 根因是什么？
  AI: 根因是 DBPool...

第3轮发给模型时，chat_history 里带着以上全部内容
```

**两个参数说明：**

| 参数 | 值 | 含义 |
|---|---|---|
| `memory_key` | `"chat_history"` | 必须和 Prompt 模板里的占位符名称一致 |
| `return_messages` | `True` | 以消息对象列表格式存储，适配 ChatOllama |

**类比 Java：** Memory 就像一个 `List<Message>` 的 Session 对象，每次请求都把这个 Session 拼进请求体发给模型。

---

### 改动三：把 Memory 挂载到 AgentExecutor

```python
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,    # ← 新增这一行
    verbose=True,
    max_iterations=6,
    handle_parsing_errors=True,
)
```

AgentExecutor 接管了 Memory 的读写：
- **每次调用前**：自动从 memory 读出历史，填入 `chat_history`
- **每次调用后**：自动把本轮的问题和回答写入 memory

你不需要手动管理历史记录，框架全包了。

---

## Memory 的完整数据流

```
第 N 轮调用：agent_executor.invoke({"input": "根因是什么？"})
                          │
                          ▼
              AgentExecutor 从 memory 读出历史
              chat_history = [第1轮, 第2轮, ..., 第N-1轮]
                          │
                          ▼
              拼成完整 Prompt 发给 qwen2.5:7b：
              ┌─────────────────────────────────┐
              │ 你有以下工具可以使用：...        │
              │                                 │
              │ 对话历史：                       │
              │   Human: 今天有哪些 ERROR？      │  ← chat_history
              │   AI: 共 6 条 ERROR...           │
              │                                 │
              │ 当前问题：根因是什么？            │  ← input
              └─────────────────────────────────┘
                          │
                          ▼
              模型结合历史上下文推理，调 Tool，返回答案
                          │
                          ▼
              AgentExecutor 把本轮写入 memory
              memory 现在多了一条：
                Human: 根因是什么？
                AI: 根因是 DBPool...
```

---

## Memory 的类型与取舍

目前用的是最简单的 `ConversationBufferMemory`，LangChain 还提供其他类型：

| Memory 类型 | 存储方式 | 优点 | 缺点 |
|---|---|---|---|
| `BufferMemory` | 全量原文 | 信息完整，不丢失细节 | 对话越长 Token 越多，成本上升 |
| `SummaryMemory` | 用模型压缩成摘要 | Token 消耗稳定 | 摘要可能丢失细节 |
| `BufferWindowMemory` | 只保留最近 K 轮 | Token 可控 | 丢失早期对话 |

**对于本地小模型（qwen2.5:7b）：**
- 上下文窗口约 32K Token，短对话用 `BufferMemory` 完全够用
- 如果对话很长（超过 20 轮），考虑换 `BufferWindowMemory(k=10)` 只保留最近 10 轮

---

## 关于 DeprecationWarning

运行时会看到一条警告：

```
LangChainDeprecationWarning: Please see the migration guide at: https://python.langchain.com/docs/versions/migrating_memory/
```

**不影响运行**。LangChain 0.3.x 在推动用新的 `RunnableWithMessageHistory` 写法替代旧的 Memory 类，旧写法仍然有效。

当前阶段先用旧写法跑通多轮对话的概念，后续熟悉后可以按官方迁移指南升级。

---

## 三个阶段对比总结

| | 第一阶段 | 第二阶段 | 第三阶段 |
|---|---|---|---|
| Tool 数量 | 3 个 | 6 个 | 6 个（复用） |
| 对话能力 | 单轮 | 单轮 | **多轮追问** |
| Memory | 无 | 无 | BufferMemory |
| Prompt 模板 | react | react | **react-chat** |
| 能回答 | 「有哪些 ERROR」 | 「哪里最严重、为什么」 | 「那...呢？」「刚才说的...」|
