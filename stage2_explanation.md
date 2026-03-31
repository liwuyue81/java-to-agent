# 第二阶段代码解析

## 改动概览

| 文件 | 变化 |
|---|---|
| `tools/log_tools_stage2.py` | 在第一阶段 3 个 Tool 基础上，新增 3 个 Tool，新增 `_parse_value` 辅助函数 |
| `main_stage2.py` | 注册了全部 6 个 Tool，其余结构与第一阶段完全相同 |
| `tools/log_tools.py` / `main.py` | **保持不动** |

---

## 新增的核心内容

### 一、`_parse_value`：防御性参数解析

**问题背景：** 7B 小模型（qwen2.5:7b）有时不严格遵守 ReAct 格式，传参会带上参数名：

```
# 期望模型传：
DBPool

# 实际模型传：
keyword="DBPool"
```

Tool 拿到的是整个字符串 `keyword="DBPool"`，用它去搜日志当然找不到。

**解决方案：** 在 Tool 函数内部，先用正则把真实值提取出来：

```python
def _parse_value(raw: str) -> str:
    match = re.search(r'=\s*["\']?([^"\'=\s]+)["\']?', raw)
    if match:
        return match.group(1)   # 提取 = 号后面的值
    return raw.strip()          # 没有 = 号，直接用原始值
```

**为什么这是小模型开发的常见做法：**
- 70B 以上的大模型或 GPT-4 基本不会有此问题
- 本地小模型能力有限，在 Tool 层做防御性解析比换模型成本低得多
- 类比 Java：就像对外部接口入参做格式兼容处理，不能假设调用方总是完全规范

---

## 三个新 Tool 详解

### Tool 4：`filter_logs_by_time` — 按时间段过滤

**能回答：** 「08:00 到 09:00 之间发生了什么？」

```python
@tool
def filter_logs_by_time(time_range: str) -> str:
    """按时间范围过滤日志，格式为 'HH:MM-HH:MM'，如 '08:00-09:00'。"""
```

**实现思路：**

```
输入: "08:00-09:00"
  │
  ▼
正则提取 start="08:00", end="09:00"
  │
  ▼
遍历所有日志行，用正则提取每行的时间 HH:MM
  │
  ▼
字符串比较：start <= 行时间 <= end
（"08:15" 在 "08:00"~"09:00" 之间 → 保留）
  │
  ▼
返回符合条件的日志行
```

**关键细节：** 用字符串直接比较时间（`"08:15" <= "09:00"`）而不是转成时间对象，因为 `HH:MM` 格式的字符串字典序和时间顺序完全一致，更简洁。

---

### Tool 5：`top_error_services` — 报错服务排行

**能回答：** 「哪个服务报错最多？」

```python
@tool
def top_error_services(top_n: str = "3") -> str:
    """统计报错最多的服务 Top N，传入数字字符串如 '3'，默认 Top 3。"""
```

**实现思路：**

```
过滤出所有 ERROR 行
  │
  ▼
正则提取服务名
日志格式：2026-03-30 08:15:22 ERROR DBPool - Connection...
正则：ERROR\s+(\w+)\s+-  →  提取 "DBPool"
  │
  ▼
用 dict 统计每个服务的出现次数
{"OrderService": 2, "DBPool": 1, "PaymentService": 1}
  │
  ▼
sorted() 按次数降序，取前 N 个
  │
  ▼
格式化输出
```

**类比 Java：**

```java
// 等价的 Java 流式写法
errors.stream()
    .collect(Collectors.groupingBy(line -> extractService(line), Collectors.counting()))
    .entrySet().stream()
    .sorted(Map.Entry.comparingByValue(Comparator.reverseOrder()))
    .limit(n)
    .collect(Collectors.toList());
```

---

### Tool 6：`get_log_context` — 根因上下文分析

**能回答：** 「DBPool 报错前后发生了什么？」

```python
@tool
def get_log_context(keyword: str) -> str:
    """找到包含关键词的 ERROR 行，并返回其前 2 行和后 2 行上下文。"""
```

**实现思路：**

```
遍历所有日志行，记录行号 i
  │
  ▼
找到满足条件的行：包含 keyword 且 包含 ERROR
  │
  ▼
取上下文：[i-2, i+3) 范围内的行（前2行 + 本行 + 后2行）
  │
  ▼
用 >>> 标记出错那一行，其余行用空格对齐
```

**输出示例：**

```
      08:05:33 INFO  OrderService - Order created          ← 出错前2行
      08:10:45 WARN  DBPool - Connection pool usage 80%    ← 出错前1行（WARN 预警！）
  >>> 08:15:22 ERROR DBPool - Connection pool exhausted    ← 出错行
      08:15:23 ERROR OrderService - Create order failed    ← 出错后1行（级联影响）
      08:15:24 ERROR PaymentService - Payment failed       ← 出错后2行（级联影响）
```

**这个 Tool 的价值：** 上下文揭示了一个典型的级联故障链：
1. WARN 阶段：连接池使用率 80%，已有预警但未处理
2. ERROR 触发：连接池耗尽
3. 级联扩散：下游 OrderService、PaymentService 跟着失败

这种分析单靠 `grep ERROR` 是看不出来的，需要上下文。

---

## 与第一阶段的对比

| 维度 | 第一阶段 | 第二阶段 |
|---|---|---|
| Tool 数量 | 3 个 | 6 个 |
| 查询维度 | 级别、关键词 | 级别、关键词、时间段、服务排行、上下文 |
| 参数解析 | 只处理日期格式 | 日期 + 通用值都做防御解析 |
| 能回答的问题 | 「有哪些 ERROR」 | 「什么时候出的问题、哪里最严重、为什么出错」 |

---

## 一个重要的设计原则

第二阶段体现了 Agent 开发的核心原则：

> **Tool 负责提供数据，LLM 负责推理分析。**

- `get_log_context` 只是把前后 5 行原始日志返回出去
- 「这是一个级联故障，根因是连接池耗尽」这个结论是模型看到数据后自己分析的
- Tool 不做判断，LLM 做判断

这和后端的分层设计一样：DAO 层只管取数据，Service 层做业务逻辑，职责分离。
