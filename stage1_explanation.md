# 第一阶段代码解析

## 先回答核心问题：整个流程是怎么跑的？

**是的，你的理解方向是对的。**

大模型理解自然语言 → 决定调用哪个 Tool → LangChain 执行对应的 Python 函数 → 把结果返回给模型 → 模型生成最终回答。

但更准确的说法是：**模型本身不会直接"调用"代码**，它只会输出一段文字，说"我要调用 get_error_logs，参数是 2026-03-30"。然后 **LangChain 读取这段文字，真正去执行 Python 函数**，再把结果塞回给模型。

---

## 完整流程图

```
你输入：「今天有哪些 ERROR 日志？」
            │
            ▼
┌─────────────────────────────────────────────────────┐
│                    LangChain                        │
│                                                     │
│  1. 把你的问题 + Tool 说明 + 格式要求 拼成一个 Prompt │
│     发给 qwen2.5:7b                                 │
└─────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────┐
│                 qwen2.5:7b（大模型）                 │
│                                                     │
│  思考：用户问今天的 ERROR，今天是 2026-03-30         │
│  输出：                                             │
│    Thought: 我需要调用 get_error_logs               │
│    Action: get_error_logs                           │
│    Action Input: 2026-03-30                         │
└─────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────┐
│                    LangChain                        │
│                                                     │
│  解析模型输出 → 找到 Action = get_error_logs        │
│  → 真正执行 Python 函数 get_error_logs("2026-03-30")│
│  → 拿到返回值："共 6 条 ERROR：..."                 │
└─────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────┐
│                 qwen2.5:7b（大模型）                 │
│                                                     │
│  Observation: 共 6 条 ERROR：...                    │
│  思考：已经拿到数据，可以回答了                      │
│  Final Answer: 今天共有 6 条 ERROR，主要是...        │
└─────────────────────────────────────────────────────┘
            │
            ▼
     打印给你看
```

这个 **思考 → 行动 → 观察 → 再思考** 的循环就叫 **ReAct Loop**。

---

## 逐行解析 main.py

### 第一步：初始化本地模型

```python
llm = ChatOllama(model="qwen2.5:7b", temperature=0)
```

**这行在做什么：** 创建一个"与本地 Ollama 对话"的客户端对象，类似 Java 里创建数据库连接池：

```java
// Java 类比
DataSource dataSource = new HikariDataSource(config);
```

**llm 的作用是什么：**
- 整个 Agent 的"大脑"，负责理解你的问题、决策调用哪个 Tool、分析 Tool 返回的数据、生成最终答案
- 它不执行任何代码，只做语言理解和推理

**`temperature=0` 是什么：**
- 控制模型回答的随机性，0 = 最确定、最稳定（同样的问题每次答案一致）
- 做 Agent 要设成 0，否则模型输出格式不稳定，LangChain 解析会出错
- 类比：关掉随机数种子，让程序行为可预测

---

### 第二步：注册 Tools

```python
tools = [get_error_logs, get_log_summary, search_logs]
```

**这行在做什么：** 告诉 Agent "你有这三个能力可以用"。

**Tool 是什么：** 就是你自己写的 Python 函数，加了 `@tool` 装饰器之后，LangChain 会：
1. 读取函数名 → 作为 Tool 的名字（模型用名字来决定调用哪个）
2. 读取函数的 docstring → 作为 Tool 的说明（模型靠这个判断什么时候用它）
3. 读取函数签名 → 知道要传什么参数

```python
# log_tools.py 里
@tool
def get_error_logs(date: str = "") -> str:
    """获取 ERROR 级别日志，可传入日期前缀如 '2026-03-30'，不传则返回所有 ERROR。"""
    # ↑ 这段注释极其重要！模型靠这个决定要不要用这个 Tool
```

**Java 类比：** 类似 Spring MVC 里注册 Controller，框架扫描注解后知道有哪些接口可以调用：

```java
// Java 类比
@RestController
public class LogController {
    @GetMapping("/errors")          // ← 类似 @tool
    public String getErrors(...) {} // ← 方法注释告诉框架这个接口做什么
}
```

---

### 第三步：加载 ReAct Prompt 模板

```python
prompt = hub.pull("hwchase17/react")
```

**这行在做什么：** 从 LangChain 的模板仓库下载一个现成的 Prompt 模板。

**为什么需要这个：** 模型默认不知道"ReAct 格式"是什么，这个模板会在你的问题外面包一层说明，告诉模型：

```
你是一个 Agent，有以下工具可以使用：
- get_error_logs: 获取 ERROR 级别日志...
- get_log_summary: 统计日志各级别数量...
- search_logs: 搜索关键词...

回答问题时，必须按照以下格式输出：
  Thought: 我的思考过程
  Action: 要调用的工具名
  Action Input: 传给工具的参数
  Observation: （工具返回的结果会填在这里）
  ... 可以重复多次 ...
  Final Answer: 最终回答

问题：今天日期是 2026-03-30。今天有哪些 ERROR 日志？
```

**为什么格式很重要：** LangChain 要解析模型输出的文字，找到 `Action:` 和 `Action Input:` 才能知道该执行哪个函数、传什么参数。格式乱了就解析失败。

**Java 类比：** 类似接口文档约定的请求/响应格式，双方都要遵守这个协议通信才不会出错。

---

### 第四步 & 第五步：创建 Agent 和执行器

```python
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=5)
```

**区别是什么：**

| 对象 | 职责 | Java 类比 |
|---|---|---|
| `agent` | 定义"怎么思考"：把 llm + tools + prompt 组装起来 | Service 层业务逻辑 |
| `agent_executor` | 负责"真正运行"：驱动 ReAct 循环，执行 Tool，处理异常 | DispatcherServlet |

**`max_iterations=5`：** 最多循环 5 次（防止模型陷入死循环一直调 Tool）。

**`verbose=True`：** 把模型的每一步思考过程打印出来，你在终端看到的 `Thought / Action / Observation` 就是这个开关打开后显示的，关掉就只显示最终答案。

---

## LangChain 在这个 Demo 里做了什么

你可能感觉 LangChain 很"隐形"，但它实际上做了所有脏活：

| 你写的代码 | LangChain 在背后做的事 |
|---|---|
| `@tool` 装饰器 | 把函数包装成标准 Tool 对象，提取名称、描述、参数 schema |
| `hub.pull(...)` | 下载 Prompt 模板，把 Tool 列表自动填入模板 |
| `create_react_agent(...)` | 把 llm + tools + prompt 组装成一个可运行的 Agent |
| `agent_executor.invoke(...)` | 驱动整个 ReAct 循环：发 Prompt → 解析输出 → 调 Tool → 把结果塞回 → 再发给模型 → 直到 Final Answer |

**如果不用 LangChain，你需要自己写：**
- 把 Tool 列表格式化成文字塞进 Prompt
- 解析模型输出，用正则提取 Action 和 Action Input
- 根据 Action 名字找到对应函数并调用
- 把 Observation 拼回 Prompt，再次请求模型
- 处理解析失败、循环超限、异常等情况

LangChain 把这些全包了，你只需要专注写 Tool 函数本身的业务逻辑。

---

## 一句话总结

```
你写的 Tool = 数据能力（读文件、过滤、统计）
大模型（qwen2.5:7b）= 理解意图、决策、分析、生成回答
LangChain = 中间的调度层，把两者连起来跑起 ReAct 循环
```
