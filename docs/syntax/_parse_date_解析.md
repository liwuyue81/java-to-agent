# `_parse_date` 方法语法解析

> 文件位置：`tools/log_tools.py` 第 8–14 行

---

## 完整代码

```python
def _parse_date(raw: str) -> str:
    """从模型输出中提取真实日期值，兼容 '2026-03-30' 和 "date: '2026-03-30'" 两种格式。"""
    if not raw:
        return ""
    # 提取形如 YYYY-MM-DD 的日期
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""
```

---

## 方法签名

```python
def _parse_date(raw: str) -> str:
```

| Python | Java 等价写法 | 说明 |
|--------|-------------|------|
| `def` | `private` 方法声明 | Python 用 `def` 定义方法 |
| `_parse_date` | 方法名以 `_` 开头 | 下划线前缀 = Java 中的 `private`，约定俗成，非强制 |
| `raw: str` | `String raw` | 参数类型注解，Python 是动态类型，这里只是提示，不强制 |
| `-> str` | 返回值 `String` | 声明返回类型，同样只是注解，不强制 |

**等价 Java 签名：**
```java
private String _parseDate(String raw)
```

---

## 文档字符串（Docstring）

```python
"""从模型输出中提取真实日期值，兼容 '2026-03-30' 和 "date: '2026-03-30'" 两种格式。"""
```

- 三引号 `"""..."""` 是 Python 的多行字符串，放在方法第一行时叫 **Docstring**
- 相当于 Java 的 `/** ... */` Javadoc 注释
- 可以通过 `help(_parse_date)` 或 IDE 查看

---

## 空值判断

```python
if not raw:
    return ""
```

- `not raw` 在以下情况均为 `True`：`None`、`""`（空字符串）、`0`
- 等价 Java 写法：
```java
if (raw == null || raw.isEmpty()) {
    return "";
}
```

> **注意差异**：Python 用缩进表示代码块，没有 `{}` 和 `;`

---

## 正则匹配

```python
match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
```

| 部分 | 含义 |
|------|------|
| `re.search(pattern, string)` | 在字符串中搜索第一个匹配，类似 Java 的 `Matcher.find()` |
| `r"..."` | raw string，`r` 前缀让反斜杠不转义，正则里常用，等价 Java 的 `"\\d{4}-\\d{2}-\\d{2}"` |
| `\d{4}` | 匹配4位数字（年） |
| `-` | 字面连字符 |
| `\d{2}` | 匹配2位数字（月/日） |

**等价 Java 写法：**
```java
Pattern pattern = Pattern.compile("\\d{4}-\\d{2}-\\d{2}");
Matcher matcher = pattern.matcher(raw);
```

---

## 三元表达式返回值

```python
return match.group(0) if match else ""
```

- Python 三元表达式语法：`值A if 条件 else 值B`
- 等价 Java：`条件 ? 值A : 值B`

**等价 Java 写法：**
```java
return matcher.find() ? matcher.group(0) : "";
```

- `match.group(0)` = 整个正则匹配到的字符串，如 `"2026-03-30"`
- `group(0)` 在 Java 的 `Matcher` 里叫 `group(0)` 或 `group()`，含义相同

---

## 整体逻辑总结

```
输入：raw = "date: '2026-03-30'"  或  "2026-03-30"  或  ""  或  null

1. raw 为空 → 直接返回 ""
2. 用正则在 raw 中找 YYYY-MM-DD 格式
3. 找到 → 返回匹配的日期字符串 "2026-03-30"
   找不到 → 返回 ""
```

**用一句话说**：不管模型输出的日期格式多乱，这个方法只负责从中提取出干净的 `YYYY-MM-DD` 日期字符串。

---

## 完整 Java 等价实现（参考）

```java
import java.util.regex.Matcher;
import java.util.regex.Pattern;

private String parseDate(String raw) {
    if (raw == null || raw.isEmpty()) {
        return "";
    }
    Pattern pattern = Pattern.compile("\\d{4}-\\d{2}-\\d{2}");
    Matcher matcher = pattern.matcher(raw);
    return matcher.find() ? matcher.group(0) : "";
}
```
