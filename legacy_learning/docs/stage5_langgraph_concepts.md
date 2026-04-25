# LangGraph 基本概念

## 三个核心概念

### 1. State（状态）

整个流程里所有节点**共享的数据容器**，每个节点都可以读它、写它。

```python
class LogAnalysisState(TypedDict):
    log_lines: list[str]       # 读取到的日志
    error_count: int           # ERROR 数量
    analysis: str              # LLM 分析结果
    should_alert: bool         # 是否需要告警
```

**Java 类比：** 就像一个在多个 Service 之间传递的 DTO，或者 Spring Batch 里的 `JobExecutionContext`，每个 Step 读写同一个上下文对象。

---

### 2. Node（节点）

图里的每一个**处理步骤**，本质是一个函数：

```
输入：当前 State
输出：对 State 的修改（部分更新）
```

```python
def read_logs_node(state: LogAnalysisState) -> dict:
    lines = read_new_lines()
    return {"log_lines": lines}       # 只更新自己负责的字段

def detect_errors_node(state: LogAnalysisState) -> dict:
    errors = [l for l in state["log_lines"] if "ERROR" in l]
    return {"error_count": len(errors)}

def llm_analyze_node(state: LogAnalysisState) -> dict:
    analysis = llm.invoke(...)
    return {"analysis": analysis}
```

**Java 类比：** 就像 Spring Batch 的 `ItemProcessor`，或者流水线上的每道工序，每个节点只做自己那一件事。

---

### 3. Edge（边）

节点之间的**跳转规则**，分两种：

**普通边：** A 执行完永远去 B

```python
graph.add_edge("read_logs", "detect_errors")
```

**条件边：** 根据 State 的值决定走哪条路

```python
def should_alert(state: LogAnalysisState) -> str:
    if state["error_count"] >= 2:
        return "llm_analyze"    # 走告警分支
    else:
        return "skip"           # 跳过

graph.add_conditional_edges("detect_errors", should_alert)
```

**Java 类比：** 普通边像顺序调用，条件边像 `if/else` 或策略模式的路由。

---

## 和 ReAct Agent 的本质区别

```
ReAct Agent（之前的写法）：
  流程由模型决定，模型说调哪个 Tool 就调哪个
  你控制不了执行路径，只能设 max_iterations 兜底

LangGraph：
  流程由你设计，模型只在节点内做分析
  执行路径完全可预测、可测试、可画出来
```

**用一句话概括：ReAct 是模型驱动，LangGraph 是开发者驱动。**

| | ReAct Agent | LangGraph |
|---|---|---|
| 流程控制 | 模型决定 | 开发者设计 |
| 执行路径 | 不可预测 | 完全可预测 |
| 调试难度 | 难 | 易（每个节点可单独测）|
| 适合场景 | 步骤不确定的开放任务 | 流程明确的复杂任务 |

---

## 日志告警流程图（LangGraph 版）

```
START
  ↓
read_logs_node（读增量日志）
  ↓
detect_errors_node（统计 ERROR 数）
  ↓
[条件边] error_count >= 2？
  ├── 否 → skip_node → END
  └── 是
        ↓
    check_cooldown_node（检查冷却期）
        ↓
    [条件边] 在冷却期内？
      ├── 是 → skip_node → END
      └── 否
            ↓
        llm_analyze_node（LLM 分析根因）
            ↓
        send_alert_node（推送告警）
            ↓
        save_state_node（保存 offset 和告警时间）
            ↓
           END
```

每个方框都是一个 Node，每个箭头都是一条 Edge，整个流程一目了然。
