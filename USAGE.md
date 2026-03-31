# java-to-agent 使用文档

Java 后端开发转 AI Agent 开发的学习项目，以日志分析 Agent 为实战载体，分五个阶段逐步实现。

---

## 环境要求

| 环境 | 版本要求 | 说明 |
|---|---|---|
| Python | 3.9+ | 推荐 3.9 或 3.11 |
| Ollama | 最新版 | 本地模型运行时 |
| qwen2.5:7b | — | 项目使用的模型，需提前下载 |
| 内存 | 16GB+ | 运行 7B 模型的推荐配置 |

---

## 安装步骤

### 1. 安装 Ollama

前往 [https://ollama.com](https://ollama.com) 下载并安装，安装后验证：

```bash
ollama --version
```

### 2. 下载模型

```bash
ollama pull qwen2.5:7b
```

下载约 4.7GB，完成后验证：

```bash
ollama list    # 应看到 qwen2.5:7b
```

### 3. 克隆项目

```bash
git clone https://github.com/你的用户名/java-to-agent.git
cd java-to-agent
```

### 4. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 5. 配置环境变量（可选）

```bash
cp .env.example .env
```

默认配置开箱即用，如需修改模型或日志路径再编辑 `.env`。

---

## 运行说明

所有命令在项目根目录下执行，使用 `.venv/bin/python` 确保使用虚拟环境的 Python。

---

## 第一阶段：最简单的日志 Agent

**文件：** `main.py`

**功能：** 单轮问答，Agent 调用 3 个基础 Tool 回答日志相关问题。

**运行：**
```bash
.venv/bin/python main.py
```

**可以问：**
```
你：今天有哪些ERROR日志？
你：日志各级别数量统计
你：搜索 DBPool 相关日志
你：quit        ← 退出
```

---

## 第二阶段：完善 Tools

**文件：** `main_stage2.py`

**功能：** 在第一阶段基础上新增 3 个 Tool，共 6 个。

| 新增 Tool | 能力 |
|---|---|
| `filter_logs_by_time` | 按时间段过滤，如 08:00-09:00 之间的日志 |
| `top_error_services` | 报错最多的服务 Top N |
| `get_log_context` | 找到某条 ERROR 前后 2 行上下文，用于根因分析 |

**运行：**
```bash
.venv/bin/python main_stage2.py
```

**可以问：**
```
你：08:00到09:00之间发生了什么？
你：哪个服务报错最多？
你：DBPool报错前后发生了什么？
你：quit        ← 退出
```

---

## 第三阶段：多轮对话（Memory）

**文件：** `main_stage3.py`

**功能：** 保存对话历史，支持追问，Agent 记得上一轮说了什么。

**运行：**
```bash
.venv/bin/python main_stage3.py
```

**可以追问（Agent 记得上下文）：**
```
你：今天有哪些ERROR日志？
Agent：共 6 条 ERROR，主要集中在 DBPool...

你：根因是什么？          ← Agent 知道你在问上面那些 ERROR
Agent：根因是连接池耗尽...

你：那WARN呢？            ← Agent 知道你还在问今天的日志
Agent：共 3 条 WARN...

你：quit        ← 退出
```

---

## 第四阶段：工程化

### 方案 A：Tool 返回结构化数据

**文件：** `main_stage4_a.py`

**功能：** Tool 返回 dict，Agent 用自然语言回答，数据同时可被程序消费。支持多轮对话。

**运行：**
```bash
.venv/bin/python main_stage4_a.py
```

---

### 方案 B：强制 JSON 输出

**文件：** `main_stage4_b.py`

**功能：** 两步走——Agent 先收集数据，再用 `with_structured_output` 强制输出符合 schema 的 JSON 对象。

**运行：**
```bash
.venv/bin/python main_stage4_b.py
```

**输出示例：**
```
─── 结构化输出结果 ───
ERROR 总数   : 6
最严重服务   : OrderService
严重程度     : high
总结         : 今天共发生 6 条 ERROR...

─── 原始 JSON ───
{
  "error_count": 6,
  "top_service": "OrderService",
  ...
}
```

---

### 运行单元测试

```bash
.venv/bin/pytest tests/ -v
```

---

## 第五阶段：异常自动告警

### 旧版（函数式）

**文件：** `monitor_main.py` + `log_simulator.py`

**开两个终端：**

**终端 1：启动监控**
```bash
.venv/bin/python monitor_main.py
```

**终端 2：模拟写入日志触发告警**
```bash
.venv/bin/python log_simulator.py
```

模拟器写入 3 条 ERROR 后，监控检测到超过阈值（≥ 2 条），调 LLM 分析并打印告警。

---

### 新版（LangGraph 版）

**文件：** `monitor_main_langgraph.py` + `log_simulator.py`

**开两个终端：**

**终端 1：启动监控**
```bash
.venv/bin/python monitor_main_langgraph.py
```

**终端 2：模拟写入日志触发告警**
```bash
.venv/bin/python log_simulator.py
```

功能与旧版完全相同，内部用 LangGraph 有向图实现，可对比两种写法的差异。

---

## 注意事项

**第一次启动告警监控：**
`alert/state.json` 不存在时，offset 从 0 开始，会把 `logs/app.log` 里已有的历史日志全部读入并触发告警。这是正常现象，之后 offset 会保存，下次只读新增的。

**重置告警状态：**
```bash
rm alert/state.json
```

**修改告警阈值或冷却时间：**
编辑 `alert/monitor.py` 顶部的常量：
```python
ERROR_THRESHOLD = 2     # 触发告警的最小 ERROR 数
COOLDOWN_MINUTES = 5    # 同类告警冷却时间（分钟）
```

**修改模型或日志路径：**
编辑 `.env` 文件：
```bash
MODEL_NAME=qwen2.5:7b
LOG_FILE=logs/app.log
```

---

## 文件索引

| 文件 | 用途 |
|---|---|
| `main.py` | 第一阶段入口 |
| `main_stage2.py` | 第二阶段入口 |
| `main_stage3.py` | 第三阶段入口（多轮对话）|
| `main_stage4_a.py` | 第四阶段方案A（Tool 返回 dict）|
| `main_stage4_b.py` | 第四阶段方案B（强制 JSON 输出）|
| `monitor_main.py` | 第五阶段告警监控（旧版）|
| `monitor_main_langgraph.py` | 第五阶段告警监控（LangGraph 版）|
| `log_simulator.py` | 模拟写入日志，用于触发告警测试 |
| `tools/log_tools.py` | 第一阶段 Tools |
| `tools/log_tools_stage2.py` | 第二/三阶段 Tools |
| `tools/log_tools_stage4.py` | 第四阶段 Tools（结构化）|
| `alert/monitor.py` | 告警核心逻辑（旧版）|
| `alert/monitor_langgraph.py` | 告警核心逻辑（LangGraph 版）|
| `alert/state.json` | 自动生成，记录 offset 和告警历史 |
| `config.py` | 全局配置入口 |
| `schemas/output.py` | 结构化输出 Pydantic schema |
| `tests/` | 单元测试 |
| `logs/app.log` | 日志文件 |
