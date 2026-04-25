# `log_tools.py` 剩余代码语法解析

> 文件位置：`tools/log_tools.py`

---

## 一、路径构造

```python
LOG_FILE = Path(__file__).parent.parent / "logs" / "app.log"
```

### 逐段拆解

| 部分 | 含义 | Java 类比 |
|------|------|-----------|
| `Path` | 路径操作类，来自 `pathlib` | `java.nio.file.Path` / `java.io.File` |
| `__file__` | 当前 `.py` 文件的绝对路径（内置变量） | 无直接等价，类似 `getClass().getResource("")` |
| `.parent` | 取上一级目录 | `file.getParentFile()` |
| `.parent.parent` | 取上两级目录 | `file.getParentFile().getParentFile()` |
| `/ "logs" / "app.log"` | 路径拼接，`/` 是运算符重载 | `Paths.get(base, "logs", "app.log")` |

**等价 Java：**
```java
// 假设当前文件在 project/tools/log_tools.py
// __file__.parent.parent 就是 project/
Path LOG_FILE = Paths.get(baseDir, "logs", "app.log");
```

> **关键差异**：Python 重载了 `/` 运算符，让路径拼接像写文件系统路径一样自然。Java 要用 `Paths.get()` 或字符串拼接。

---

## 二、`_read_lines` — 读取日志行

```python
def _read_lines(date: str = "") -> list[str]:
    """读取日志行，可按日期前缀过滤。"""
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    if date:
        lines = [l for l in lines if l.startswith(date)]
    return lines
```

### 默认参数

```python
def _read_lines(date: str = ""):
```

- `= ""` 表示参数有默认值，调用时可以不传
- 等价 Java（Java 没有默认参数，通常用重载）：
```java
private List<String> readLines() { return readLines(""); }
private List<String> readLines(String date) { ... }
```

### with 语句（上下文管理器）

```python
with open(LOG_FILE, "r") as f:
    lines = f.readlines()
```

- `with` 会在代码块结束后**自动关闭资源**，无论是否抛异常
- 等价 Java 的 try-with-resources：
```java
try (BufferedReader f = new BufferedReader(new FileReader(LOG_FILE.toFile()))) {
    List<String> lines = f.lines().collect(Collectors.toList());
}
```

- `"r"` = 只读模式（read），类似 Java `FileReader`
- `f.readlines()` = 读取所有行，返回 `list[str]`，每行末尾带 `\n`

### 列表推导式（List Comprehension）

```python
lines = [l for l in lines if l.startswith(date)]
```

这是 Python 最常见的语法之一，结构为：

```
[表达式  for 变量 in 可迭代对象  if 过滤条件]
```

等价 Java Stream：
```java
lines = lines.stream()
             .filter(l -> l.startsWith(date))
             .collect(Collectors.toList());
```

- `l.startswith(date)` = Java 的 `l.startsWith(date)`（Python 是小写）

---

## 三、`@tool` 装饰器

```python
@tool
def get_error_logs(date: str = "") -> str:
```

- `@tool` 是**装饰器**，相当于对函数做了一层包装
- 来自 `langchain.tools`，它把这个普通函数注册为 AI Agent 可调用的工具
- 类比 Java 注解：`@Component`、`@Bean`，告诉框架"这个方法需要特殊处理"

```java
// 类比
@Component
public String getErrorLogs(String date) { ... }
```

> 本质区别：Java 注解在编译期/运行期通过反射处理；Python 装饰器在**函数定义时**直接执行包装逻辑，`@tool` 等于 `get_error_logs = tool(get_error_logs)`。

---

## 四、`get_error_logs` — 获取 ERROR 日志

```python
@tool
def get_error_logs(date: str = "") -> str:
    errors = [l.strip() for l in _read_lines(_parse_date(date)) if "ERROR" in l]
    if not errors:
        return "未找到 ERROR 日志。"
    return f"共 {len(errors)} 条 ERROR：\n" + "\n".join(errors)
```

### 核心一行拆解

```python
errors = [l.strip() for l in _read_lines(_parse_date(date)) if "ERROR" in l]
```

从内到外读：

1. `_parse_date(date)` → 清洗日期字符串
2. `_read_lines(...)` → 读取（并过滤）日志行列表
3. `for l in ...` → 遍历每一行
4. `if "ERROR" in l` → 过滤，只保留包含 "ERROR" 的行
5. `l.strip()` → 去掉行首尾的空白/换行符

等价 Java：
```java
List<String> errors = readLines(parseDate(date)).stream()
    .filter(l -> l.contains("ERROR"))
    .map(String::strip)
    .collect(Collectors.toList());
```

### f-string 格式化字符串

```python
return f"共 {len(errors)} 条 ERROR：\n" + "\n".join(errors)
```

| 语法 | 含义 | Java 等价 |
|------|------|-----------|
| `f"..."` | f-string，`{}` 内直接写表达式 | `String.format(...)` 或 `"" + 变量` |
| `len(errors)` | 列表长度 | `errors.size()` |
| `"\n".join(errors)` | 用换行符连接列表所有元素 | `String.join("\n", errors)` |

---

## 五、`get_log_summary` — 日志统计

```python
counts = {level: sum(1 for l in lines if level in l) for level in ("INFO", "WARN", "ERROR")}
```

这是**字典推导式**，结构：

```
{key表达式: value表达式  for 变量 in 可迭代对象}
```

拆解：

```python
# 等价展开
counts = {}
for level in ("INFO", "WARN", "ERROR"):        # 遍历三个级别
    counts[level] = sum(1 for l in lines if level in l)  # 统计包含该级别的行数
```

- `("INFO", "WARN", "ERROR")` 是**元组**（tuple），类似不可变的 `List`，这里当枚举用
- `sum(1 for l in lines if level in l)` = 满足条件的行数，等价 `(int) lines.stream().filter(l -> l.contains(level)).count()`

等价 Java：
```java
Map<String, Long> counts = new HashMap<>();
for (String level : List.of("INFO", "WARN", "ERROR")) {
    counts.put(level, lines.stream().filter(l -> l.contains(level)).count());
}
```

---

## 六、`search_logs` — 关键词搜索

```python
results = [l.strip() for l in _read_lines() if keyword.lower() in l.lower()]
```

- `_read_lines()` 不传参 → 读取全部日志（默认参数 `date=""` 不过滤）
- `keyword.lower()` / `l.lower()` → 全转小写，实现大小写不敏感搜索
- 等价 Java：`l.toLowerCase().contains(keyword.toLowerCase())`

### f-string 含变量

```python
return f"未找到包含 '{keyword}' 的日志。"
```

- 单引号 `'` 在双引号 f-string 里直接写，无需转义
- 等价 Java：`"未找到包含 '" + keyword + "' 的日志。"`

---

## 整体结构总结

```
LOG_FILE                  → 全局常量，文件路径（类比 Java static final）
_parse_date(raw)          → private，清洗日期字符串
_read_lines(date)         → private，读文件 + 按日期过滤
get_error_logs(date)      → public @tool，过滤 ERROR 行
get_log_summary(date)     → public @tool，统计各级别数量
search_logs(keyword)      → public @tool，关键词搜索
```

> `_` 开头 = private 工具方法；无 `_` + `@tool` = 暴露给 AI Agent 的公开接口。
