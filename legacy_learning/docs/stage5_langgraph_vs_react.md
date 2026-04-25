# 旧版 vs LangGraph 版：告警系统两种写法对比

## 代码结构对比

### 旧版（monitor.py）

所有逻辑集中在一个函数 `run_once()` 里：

```python
def run_once() -> None:
    state = _load_state()
    new_lines, new_offset = read_new_lines()       # 步骤1

    if not new_lines:                              # 判断1
        _save_state({...})
        return

    error_lines = detect_errors(new_lines)         # 步骤2

    if len(error_lines) < ERROR_THRESHOLD:         # 判断2
        _save_state({...})
        return

    if is_in_cooldown(alert_key, state["alerted"]): # 判断3
        _save_state({...})
        return

    analysis = llm_analyze(error_lines)            # 步骤3
    send_alert(error_lines, analysis)              # 步骤4
    _save_state(...)                               # 步骤5
```

**流程藏在代码里**，不读完函数体看不出走哪条路。

---

### 新版（monitor_langgraph.py）

每个步骤是独立函数，流程显式声明：

```python
# 注册节点（每个节点只做一件事）
graph.add_node("read_logs",      read_logs_node)
graph.add_node("detect_errors",  detect_errors_node)
graph.add_node("check_cooldown", check_cooldown_node)
graph.add_node("llm_analyze",    llm_analyze_node)
graph.add_node("send_alert",     send_alert_node)
graph.add_node("save_state",     save_state_node)
graph.add_node("skip",           skip_node)

# 声明流程（add_edge 就是流程文档）
graph.add_edge("read_logs",   "detect_errors")
graph.add_edge("llm_analyze", "send_alert")
graph.add_edge("send_alert",  "save_state")

# 声明分支（条件跳转）
graph.add_conditional_edges("detect_errors",  route_by_threshold, {...})
graph.add_conditional_edges("check_cooldown", route_by_cooldown,  {...})
```

**流程即代码**，看建图部分就知道整体流程，不需要读函数体。

---

## 流程图对比

### 旧版流程（隐式）

```
run_once()
  ├── 无新日志？ → return
  ├── ERROR < 阈值？ → return
  ├── 在冷却期？ → return
  └── LLM 分析 → 推送 → 保存状态
```

必须阅读代码才能画出这张图。

### 新版流程（显式）

```
START
  ↓
read_logs_node
  ↓
detect_errors_node
  ↓
[条件] ERROR 数 >= 阈值？
  ├── 否 → skip_node → END
  └── 是
        ↓
    check_cooldown_node
        ↓
    [条件] 在冷却期？
      ├── 是 → skip_node → END
      └── 否
            ↓
        llm_analyze_node
            ↓
        send_alert_node
            ↓
        save_state_node
            ↓
           END
```

这张图可以直接从 `add_edge` 和 `add_conditional_edges` 的调用顺序推导出来。

---

## 优劣对比

### 旧版优点

| 优点 | 说明 |
|---|---|
| 代码量少 | 不需要定义 State 类、不需要建图，直接写函数 |
| 上手快 | 没有新概念，就是普通 Python 函数 |
| 适合简单流程 | 步骤少、没有分支时，一个函数足够清晰 |

### 旧版缺点

| 缺点 | 说明 |
|---|---|
| 流程不透明 | 必须读完整个函数才能理解流程走向 |
| 步骤耦合 | 所有逻辑混在一起，改一处容易影响其他 |
| 难以扩展 | 新增步骤要改 `run_once()`，破坏已有逻辑 |
| 难以测试 | 无法单独测某一个步骤，只能测整个函数 |
| 不支持并行 | 步骤只能串行执行 |

---

### LangGraph 版优点

| 优点 | 说明 |
|---|---|
| 流程可视化 | `add_edge` 声明本身就是流程文档 |
| 步骤隔离 | 每个 Node 是独立函数，改一个不影响其他 |
| 易于扩展 | 新增步骤只需加节点、加边，不动现有代码 |
| 可单独测试 | 每个 Node 函数可以独立单测，输入 State、验证输出 |
| 支持并行 | 多个节点可以同时执行（如同时统计 ERROR 和 WARN）|
| 状态统一管理 | 所有中间数据放在 State 里，不用通过函数参数层层传递 |

### LangGraph 版缺点

| 缺点 | 说明 |
|---|---|
| 代码量多 | 需要定义 State、注册节点、建图，初始成本高 |
| 学习曲线 | 需要理解节点、边、State 等新概念 |
| 小流程杀鸡用牛刀 | 3 个步骤以内的简单任务，用 LangGraph 反而更复杂 |

---

## 什么时候选哪种

| 场景 | 推荐 |
|---|---|
| 快速验证想法、原型开发 | 旧版（直接写函数） |
| 流程步骤 ≤ 3，无分支 | 旧版 |
| 流程步骤多、有明确分支 | LangGraph |
| 需要并行执行多个步骤 | LangGraph |
| 需要和其他系统对接、流程要透明 | LangGraph |
| 生产环境、需要长期维护 | LangGraph |

---

## 一句话总结

> **旧版**：适合写得快、改得少的场景，流程藏在代码里。
>
> **LangGraph**：适合流程复杂、长期维护的场景，流程即文档，代码即架构图。

对于日志 Agent 这个项目，第一阶段用旧版快速跑通是对的；随着功能增多（告警、分析、报告），切换到 LangGraph 让流程更可控是自然的演进路径。这也是业界的普遍实践：**先跑通，再架构**。
