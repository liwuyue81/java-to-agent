# LangGraph 版告警系统代码解析

## 先回答核心问题：整个流程是怎么跑的？

旧版把所有逻辑写在一个函数 `run_once()` 里，流程藏在 `if/else` 里。

LangGraph 版把每个步骤拆成独立的 **Node（节点）**，用 **Edge（边）** 连接，整个流程像一张地铁线路图，每一站做什么、到哪一站换乘，显式声明，一目了然。

---

## 完整执行流程图

```
monitor_main_langgraph.py
每 30 秒调一次 run_once_langgraph()
            │
            ▼
  初始化 AlertState（从 state.json 读 offset 和 alerted）
            │
            ▼
┌───────────────────────────────────────────────┐
│              alert_graph.invoke(state)        │
│                                               │
│  ┌─────────────────┐                          │
│  │  read_logs_node │ 从 offset 开始读新增行    │
│  └────────┬────────┘                          │
│           ↓                                   │
│  ┌──────────────────────┐                     │
│  │  detect_errors_node  │ 提取 ERROR 行和 key │
│  └────────┬─────────────┘                     │
│           ↓                                   │
│    [条件边] ERROR 数 >= 2 ？                   │
│      ├── 否 ──────────────────────┐           │
│      └── 是                       │           │
│           ↓                       │           │
│  ┌──────────────────────┐         │           │
│  │ check_cooldown_node  │         │           │
│  └────────┬─────────────┘         │           │
│           ↓                       │           │
│    [条件边] 在冷却期内？           │           │
│      ├── 是 ──────────────────┐   │           │
│      └── 否                   │   │           │
│           ↓                   ↓   ↓           │
│  ┌──────────────────┐   ┌──────────────┐      │
│  │ llm_analyze_node │   │  skip_node   │      │
│  └────────┬─────────┘   └──────┬───────┘      │
│           ↓                    ↓              │
│  ┌──────────────────┐         END             │
│  │ send_alert_node  │                         │
│  └────────┬─────────┘                         │
│           ↓                                   │
│  ┌──────────────────┐                         │
│  │  save_state_node │                         │
│  └────────┬─────────┘                         │
│           ↓                                   │
│          END                                  │
└───────────────────────────────────────────────┘
```

---

## 核心概念逐一解析

### State：所有节点共享的数据容器

```python
class AlertState(TypedDict):
    new_lines:   list[str]  # 新增日志行
    error_lines: list[str]  # ERROR 行
    alert_key:   str        # 去重 key（服务名）
    analysis:    str        # LLM 分析结果
    offset:      int        # 新的文件读取位置
    alerted:     dict       # 历史告警记录
```

**作用：** 节点之间不通过函数参数传递数据，而是统一读写 State。每个节点只更新自己负责的字段，返回一个 dict，LangGraph 自动合并到 State 里。

**Java 类比：** Spring Batch 的 `JobExecutionContext`，或者在多个 Service 之间流转的 DTO 对象。

```
read_logs_node     → 写入 new_lines、offset
detect_errors_node → 写入 error_lines、alert_key
llm_analyze_node   → 写入 analysis
```

---

### Node：每个节点只做一件事

每个 Node 的签名固定：**输入当前 State，输出对 State 的部分更新**。

```python
def read_logs_node(state: AlertState) -> dict:
    """节点1：增量读取日志"""
    new_lines, new_offset = read_new_lines()
    return {"new_lines": new_lines, "offset": new_offset}  # 只更新这两个字段
```

```python
def detect_errors_node(state: AlertState) -> dict:
    """节点2：提取 ERROR 行，找出告警 key"""
    error_lines = detect_errors(state["new_lines"])  # 从 State 读上一步的结果
    ...
    return {"error_lines": error_lines, "alert_key": alert_key}
```

**为什么这样设计：**
- 每个节点职责单一，可以独立测试
- 节点之间解耦，改一个不影响其他
- 类比 Spring Batch 的 `ItemProcessor`，每道工序只处理自己的事

---

### Edge：普通边 vs 条件边

**普通边：** A 执行完，永远去 B，没有分支。

```python
graph.add_edge("read_logs",   "detect_errors")  # 读完日志 → 必然检测 ERROR
graph.add_edge("llm_analyze", "send_alert")     # 分析完 → 必然推送
graph.add_edge("send_alert",  "save_state")     # 推送完 → 必然保存状态
```

**条件边：** 根据 State 的值，动态决定去哪个节点。

```python
def route_by_threshold(state: AlertState) -> str:
    if len(state["error_lines"]) >= ERROR_THRESHOLD:
        return "check_cooldown"   # 返回节点名字符串
    return "skip"

graph.add_conditional_edges(
    "detect_errors",        # 从哪个节点出发
    route_by_threshold,     # 路由函数，返回下一节点名
    {
        "check_cooldown": "check_cooldown",  # 返回值 → 目标节点
        "skip":           "skip",
    }
)
```

**Java 类比：** 普通边像顺序调用，条件边像策略模式的路由，或者 Spring Batch 的 `JobExecutionDecider`。

---

### 建图：流程即文档

```python
def build_alert_graph():
    graph = StateGraph(AlertState)

    # 第一步：注册节点（声明有哪些处理步骤）
    graph.add_node("read_logs",      read_logs_node)
    graph.add_node("detect_errors",  detect_errors_node)
    graph.add_node("check_cooldown", check_cooldown_node)
    graph.add_node("llm_analyze",    llm_analyze_node)
    graph.add_node("send_alert",     send_alert_node)
    graph.add_node("save_state",     save_state_node)
    graph.add_node("skip",           skip_node)

    # 第二步：声明入口
    graph.set_entry_point("read_logs")

    # 第三步：连接普通边
    graph.add_edge("read_logs",   "detect_errors")
    graph.add_edge("llm_analyze", "send_alert")
    graph.add_edge("send_alert",  "save_state")
    graph.add_edge("save_state",  END)
    graph.add_edge("skip",        END)

    # 第四步：连接条件边
    graph.add_conditional_edges("detect_errors",  route_by_threshold, {...})
    graph.add_conditional_edges("check_cooldown", route_by_cooldown,  {...})

    return graph.compile()   # 编译成可执行的图
```

**`graph.compile()` 做了什么：** 验证图的合法性（有没有死节点、有没有孤立节点），生成可执行对象。类比 Spring 容器的 `refresh()`，把所有 Bean 装配好，验证依赖关系。

---

### 执行入口

```python
def run_once_langgraph() -> None:
    current = _load_state()

    # 初始化 State（空数据 + 从磁盘读的持久化数据）
    initial_state: AlertState = {
        "new_lines":   [],
        "error_lines": [],
        "alert_key":   "",
        "analysis":    "",
        "offset":      current["offset"],   # 上次读到哪行
        "alerted":     current["alerted"],  # 历史告警记录
    }

    # 触发图执行，LangGraph 接管后续所有节点的调度
    alert_graph.invoke(initial_state)
```

`alert_graph.invoke(state)` 之后，你不需要关心节点的调用顺序，LangGraph 按照建图时声明的边自动调度，遇到条件边就执行路由函数决定走哪条路。

---

## LangGraph 在这里做了什么

| 你写的代码 | LangGraph 在背后做的事 |
|---|---|
| `StateGraph(AlertState)` | 创建图，绑定 State 的数据结构 |
| `add_node(name, fn)` | 注册节点，把名字和函数绑定 |
| `add_edge(a, b)` | 声明 a 执行完后调 b |
| `add_conditional_edges(...)` | 声明条件分支，运行时调路由函数决定下一步 |
| `graph.compile()` | 验证图合法性，生成可执行对象 |
| `graph.invoke(state)` | 从入口节点开始，按边的声明依次执行，把每个节点的返回值合并回 State |

**如果不用 LangGraph，你需要自己写：**
- 手动维护节点调用顺序
- 手动在每个条件判断后决定调哪个函数
- 手动在函数间传递中间数据
- 出错时手动回溯排查是哪一步失败的

---

## 一句话总结

```
Node      = 每道工序（只做一件事）
Edge      = 流水线传送带（决定数据流向）
State     = 工序间流转的产品（共享数据容器）
LangGraph = 流水线调度系统（按图执行，你只管建图）
```
