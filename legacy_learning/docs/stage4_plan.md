# 第四阶段技术方案：工程化

## 目标

把前三阶段「能跑但不够健壮」的代码，改造成接近生产标准的状态。

---

## 一、配置文件管理

### 现状问题

模型名、日志路径、参数都硬编码在代码里，换个环境就要改代码。

### 业界标准做法

用 `.env` 文件 + `pydantic-settings` 管理配置，和 Spring Boot 的 `application.yml` 思路完全一样。

**文件职责：**

```
.env                    ← 本地配置，不提交 git
.env.example            ← 示例文件，提交 git，告诉别人需要配哪些变量
config.py               ← 读取配置的入口，全局只初始化一次
```

所有配置从 `config.py` 读，其他文件不直接读环境变量。这样换模型、换日志路径只改 `.env`，不动代码。

---

## 二、结构化输出

### 现状问题

Agent 返回的是自然语言字符串，下游程序无法消费。比如想把分析结果存数据库、发告警、展示在前端，都很难处理。

### 业界标准做法

两种方案，根据场景选择：

**方案 A：Tool 返回结构化数据**

Tool 函数直接返回 dict，在 Agent 层再格式化成自然语言。同一份数据既能给模型看，也能给程序用。

**方案 B：`with_structured_output` 强制模型输出 JSON（主流）**

LangChain 提供 `llm.with_structured_output(schema)` 方法，配合 Pydantic 模型定义输出格式，模型被约束只能输出符合 schema 的 JSON：

```python
class LogAnalysisResult(BaseModel):
    error_count: int
    top_service: str
    summary: str
    severity: Literal["low", "medium", "high"]
```

这是业界主流做法，尤其是 Agent 对接其他系统时必须用结构化输出。

> **注意：** 7B 小模型对 structured output 的遵守程度有限，复杂 schema 容易出错，简单 schema 基本可用。

---

## 三、错误处理与重试

### 现状问题

- Tool 读文件失败会直接抛异常，整个 Agent 崩掉
- 模型输出格式不对时 `handle_parsing_errors=True` 只是静默跳过，没有日志
- 没有超时控制，模型卡住了就一直等

### 业界标准做法

**Tool 层：所有 Tool 函数内部消化异常**

返回错误描述字符串而不是抛异常。模型收到错误描述后会自行决策（重试、换参数、或告知用户），这是 Agent 容错的核心设计：

```python
@tool
def get_error_logs(date: str = "") -> str:
    try:
        ...
    except FileNotFoundError:
        return "日志文件不存在，请确认路径配置是否正确。"
    except Exception as e:
        return f"读取日志失败：{e}"
```

**调用层：超时控制**

`ChatOllama` 支持 `timeout` 参数，防止模型卡住无响应。

**日志：用 `logging` 替代 `print`**

用 Python 标准库 `logging` 按级别输出，生产环境只看 WARNING 以上，开发环境看 DEBUG 全量。

---

## 四、单元测试

### 现状问题

Tool 函数完全没有测试，改动后不知道是否破坏了原有功能。

### 业界标准做法

用 `pytest`，分三层测试：

**第一层：Tool 函数单测（最重要）**

Tool 是纯函数（输入固定 → 输出固定），最适合单测。用 `tmp_path` 创建临时日志文件，不依赖真实文件：

```python
def test_get_error_logs_with_date(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("2026-03-31 08:00:00 ERROR SvcA - error\n")
    result = get_error_logs.invoke("2026-03-31")
    assert "SvcA" in result
    assert "1 条" in result
```

**第二层：参数解析单测**

专门测 `_parse_value`、`_parse_date` 这类辅助函数，覆盖边界情况（空字符串、带引号、不带引号等）。

**第三层：集成测试（可选，慢）**

真正启动 Agent 问一个问题，验证端到端流程。跑 CI 时可以跳过。

---

## 工程化后的目录结构

```
log-agent/
├── config.py               ← 配置入口
├── .env                    ← 本地配置（不提交 git）
├── .env.example            ← 配置模板（提交 git）
├── main_stage4.py          ← 入口
├── tools/
│   └── log_tools.py        ← 带错误处理的 Tools
├── schemas/
│   └── output.py           ← Pydantic 结构化输出定义
├── tests/
│   ├── test_log_tools.py   ← Tool 单测
│   └── test_parse.py       ← 参数解析单测
└── logs/
    └── app.log
```

---

## 建议的实施顺序

| 顺序 | 内容 | 理由 |
|---|---|---|
| 1 | 配置管理 | 改动小，收益大，后续所有代码都受益 |
| 2 | 错误处理 | 让 Agent 更健壮，测试时不容易崩 |
| 3 | 单元测试 | 有了稳定代码再补测试，测试反过来保护重构 |
| 4 | 结构化输出 | 改动最大，对小模型有风险，放最后验证效果 |
