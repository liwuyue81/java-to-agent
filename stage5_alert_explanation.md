# 第五阶段代码解析：异常自动告警

## 文件职责

```
alert/
├── __init__.py
└── monitor.py       ← 核心逻辑：增量读取、规则检测、去重、LLM 分析、推送
monitor_main.py      ← 入口：定时循环，每 30 秒调一次 monitor.py
log_simulator.py     ← 测试工具：模拟向日志文件追加新日志，触发告警
alert/state.json     ← 自动生成：持久化 offset 和告警历史
```

---

## 完整流程

```
monitor_main.py 每 30 秒触发一次
          ↓
     run_once()
          ↓
  读取 state.json 拿到上次的 offset
          ↓
  从 offset 开始读 app.log 新增行
          ↓
  提取新增行里的 ERROR
          ↓
  ERROR 数 < 阈值（2）？ → 跳过，更新 offset
          ↓ 超过阈值
  检查冷却：同类问题 5 分钟内已告警？ → 跳过
          ↓ 未在冷却期
  调 LLM 分析根因，生成摘要
          ↓
  终端打印告警
          ↓
  更新 state.json（新 offset + 告警时间）
```

---

## 核心代码逐段解析

### 1. 增量读取

```python
def read_new_lines() -> tuple[list[str], int]:
    state = _load_state()
    offset = state["offset"]          # 上次读到第几行

    with open(settings.log_file) as f:
        all_lines = f.readlines()

    new_lines = all_lines[offset:]    # 只取新增的部分
    new_offset = len(all_lines)       # 新的 offset = 当前总行数
    return new_lines, new_offset
```

**为什么这样设计：**

不能每次读全量日志，否则历史 ERROR 会重复触发告警。用 offset 记录「上次读到哪里」，类比 MySQL binlog 消费的位点机制。

offset 存在 `state.json` 里，程序重启后不会从头开始：

```json
{
  "offset": 17,
  "alerted": {
    "DBPool": "2026-03-31T12:31:37"
  }
}
```

---

### 2. 硬规则检测

```python
ERROR_THRESHOLD = 2

error_lines = detect_errors(new_lines)

if len(error_lines) < ERROR_THRESHOLD:
    # 未达阈值，跳过，但仍更新 offset
    _save_state({**state, "offset": new_offset})
    return
```

**为什么用硬规则而不是全部交给 LLM：**

- 硬规则快（毫秒级），LLM 慢（秒级）
- 硬规则确定性强，不会有模型幻觉
- LLM 只在确认有问题后才调，节省资源

两者职责分工：**硬规则判断要不要告警，LLM 负责分析为什么**。

---

### 3. 告警去重（冷却机制）

```python
COOLDOWN_MINUTES = 5

def is_in_cooldown(keyword: str, alerted: dict) -> bool:
    if keyword not in alerted:
        return False
    last_alert_time = datetime.fromisoformat(alerted[keyword])
    return datetime.now() - last_alert_time < timedelta(minutes=COOLDOWN_MINUTES)
```

**为什么需要这个：**

监控每 30 秒跑一次，一个故障可能持续 10 分钟。如果不做去重，同一个问题会发 20 条告警，这比没有告警更烦人。冷却期内同类问题只告警一次。

**去重 key 的提取：** 用第一条 ERROR 日志里的服务名（如 `DBPool`）作为 key，相同服务的连续报错视为同一事件。

---

### 4. LLM 分析

```python
def llm_analyze(error_lines: list[str]) -> str:
    llm = ChatOllama(model=settings.model_name, temperature=0)
    log_text = "\n".join(error_lines)
    prompt = f"""以下是最新检测到的 ERROR 日志：

{log_text}

请用 2-3 句话简要分析：根因是什么？影响了哪些服务？建议排查方向？"""
    response = llm.invoke(prompt)
    return response.content
```

**这里不用 Agent，直接调 LLM：**

Agent 适合「需要决策调哪个 Tool」的场景。这里数据已经准备好了（error_lines），只需要模型做一件事：分析文字。直接调 LLM 更快、更简单，不需要 Tool 调用的开销。

---

### 5. 定时循环

```python
CHECK_INTERVAL = 30

while True:
    run_once()
    time.sleep(CHECK_INTERVAL)
```

用最简单的 `while + sleep` 实现定时，不引入额外依赖。生产环境会用 `APScheduler` 或系统级 cron，但原理相同。

---

## 为什么必须用 `.venv/bin/python` 才能启动

这是 Python 虚拟环境（venv）的核心机制，用 Java 类比理解：

| 概念 | Java | Python venv |
|---|---|---|
| 依赖隔离 | Maven 本地仓库 `~/.m2` | `.venv/lib/python3.9/site-packages/` |
| 项目专属依赖 | `pom.xml` 声明 | `requirements.txt` 声明 |
| 使用指定依赖 | IDE 选择 JDK | 用 `.venv/bin/python` 启动 |

**问题原因：**

你的 Mac 上有多个 Python：
```
/usr/bin/python3          ← 系统 Python，没有 langchain 等依赖
.venv/bin/python          ← 项目 venv，装了所有依赖
```

直接运行 `python monitor_main.py`，系统找到的是 `/usr/bin/python3`，它不认识 `langchain_ollama`，所以报 `ModuleNotFoundError`。

**两种正确启动方式：**

**方式一：用完整路径（推荐，最明确）**
```bash
cd /Users/photonpay/ai
.venv/bin/python monitor_main.py
```

**方式二：激活 venv，临时修改 PATH**
```bash
cd /Users/photonpay/ai
source .venv/bin/activate   # 激活后终端前缀变成 (.venv)
python monitor_main.py       # 此时 python 指向 .venv/bin/python
```

`source .venv/bin/activate` 做的事就是把 `.venv/bin` 插到 PATH 最前面，让 `python` 命令优先找到 venv 里的解释器。关闭终端或运行 `deactivate` 后恢复原状。

**PyCharm 为什么不用这样：** PyCharm 在运行配置里自动选择了 `.venv/bin/python`，所以在 IDE 里点运行不会有这个问题。命令行手动运行时需要自己指定。
