# MySQL MCP Server + DB Agent 实现文档

> 目标：把 MySQL 数据库能力接入 AI Agent 工作流，实现两种访问路径：
> - **Plan A**：Claude Code 通过 `.mcp.json` 直接调 MySQL MCP Server
> - **Plan B**：Supervisor 新增 DB Agent，内置 SQLAlchemy Tool 查询 MySQL

---

## 一、整体架构

```mermaid
flowchart LR
    subgraph Plan A
        CC[Claude Code<br/>.mcp.json]
    end

    subgraph Plan B
        SUP[Supervisor LLM]
        DB[DB Agent<br/>SQLAlchemy Tool]
        SUP -->|route=db| DB
        DB --> SUP
    end

    subgraph MySQL MCP Server
        SRV[mysql_mcp_server/server.py<br/>stdio transport<br/>3 个 Tool]
    end

    subgraph MySQL Docker
        MYSQL[(MySQL 8.0<br/>localhost:3307<br/>testdb)]
    end

    CC -->|stdio| SRV
    SRV -->|SQLAlchemy| MYSQL
    DB  -->|SQLAlchemy| MYSQL
```

两条路径访问同一个 MySQL，共用相同的连接串 `MYSQL_URL`：
- MCP Server 面向**外部** AI 客户端（Plan A）
- SQLAlchemy Tool 面向 **Agent 内部**（Plan B，同进程无需 MCP 中间层）

---

## 二、MySQL Docker 环境

### docker-compose.yml 新增 mysql service

```yaml
mysql:
  image: mysql:8.0
  container_name: java-to-agent-mysql
  environment:
    MYSQL_ROOT_PASSWORD: "dev123456"
    MYSQL_DATABASE: testdb
  ports:
    - "3307:3306"          # 宿主机 3307 → 容器 3306（避免和本地 MySQL 3306 冲突）
  volumes:
    - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql  # 自动执行初始化
    - mysql_data:/var/lib/mysql                           # 数据持久化
  healthcheck:
    test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-pdev123456"]
    interval: 10s
    retries: 5
```

**关键点**：
- `3307:3306`：端口映射，宿主机 3307 是为了避免和已有本地 MySQL 冲突
- `docker-entrypoint-initdb.d/`：MySQL 官方镜像约定，放在这里的 `.sql` 文件会在首次启动时自动执行
- `mysql_data` volume：MySQL 数据文件存在宿主机，容器重启不丢数据

### 测试数据（db/init.sql）

```sql
USE testdb;

CREATE TABLE users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(100) UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (name, email) VALUES
  ('张三', 'zhangsan@example.com'),
  ('李四', 'lisi@example.com'),
  ('王五', 'wangwu@example.com');

CREATE TABLE orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  product VARCHAR(100) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  status ENUM('pending','shipped','completed') DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO orders (user_id, product, amount, status) VALUES
  (1, 'iPhone 15',   6999.00, 'completed'),
  (2, 'MacBook Pro', 12999.00, 'completed'),
  (1, 'AirPods',     1299.00, 'shipped'),
  (3, 'iPad',        4599.00, 'pending');
```

### 启动和验证

```bash
# 启动
docker compose up -d mysql

# 进入 MySQL 终端
docker compose exec mysql mysql -uroot -pdev123456 testdb

# 验证测试数据
SELECT u.name, SUM(o.amount) AS total
FROM users u JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.name
ORDER BY total DESC;
# 期望：李四 12999 / 张三 8298 / 王五 4599
```

---

## 三、Plan A：MySQL MCP Server

### 文件结构

```
mysql_mcp_server/
├── __init__.py     # 空，标记为 package
└── server.py       # MCP Server 主体（~180 行）
```

### server.py 核心结构

```python
# 暴露 3 个只读 Tool
TOOLS = [
    McpTool(name="list_tables",    ...),  # 列出所有表名
    McpTool(name="describe_table", ...),  # 查看表结构
    McpTool(name="query_database", ...),  # 执行 SELECT 查询
]

# MCP Server 两个 handler
@server.list_tools()
async def handle_list_tools() -> list[McpTool]:
    return TOOLS

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_database":
        result = await asyncio.to_thread(_query_database, arguments["sql"])
    ...
    return [TextContent(type="text", text=result)]

# stdio transport：标准输入输出作 MCP 通道
async with stdio_server() as (read_stream, write_stream):
    await server.run(read_stream, write_stream, ...)
```

### 安全约束（只读）

```python
def _query_database(sql: str) -> str:
    if not sql.strip().upper().startswith("SELECT"):
        return json.dumps({"error": "只允许 SELECT 查询，拒绝写操作"})
    # 执行查询...
```

**为什么**：MCP Server 面向外部客户端，必须防止 AI 误执行 `DROP TABLE` 等危险操作。

### 连接配置

```bash
# 连接串格式
MYSQL_URL="mysql+pymysql://user:password@host:port/database"

# 本地开发
MYSQL_URL="mysql+pymysql://root:dev123456@localhost:3307/testdb"
```

`asyncio.to_thread()`：SQLAlchemy 的 `execute()` 是同步调用，
用 `to_thread` 包起来避免阻塞 MCP 的 asyncio 事件循环（和 FastAPI SSE 一样的套路）。

### Plan A 配置：.mcp.json

```json
{
  "mcpServers": {
    "mysql": {
      "command": "/Users/photonpay/java-to-agent/.venv/bin/python",
      "args": ["/Users/photonpay/java-to-agent/mysql_mcp_server/server.py"],
      "env": {
        "MYSQL_URL": "mysql+pymysql://root:dev123456@localhost:3307/testdb",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

放在项目根目录，Claude Code 启动时自动读取，对话中可直接调 MySQL 工具。

### Plan A 执行流程

```mermaid
sequenceDiagram
    participant CC as Claude Code
    participant SRV as MySQL MCP Server
    participant DB as MySQL Docker

    CC->>SRV: 启动子进程（stdio）
    SRV->>DB: 验证数据库连接
    CC->>SRV: list_tools 请求
    SRV-->>CC: 返回 3 个 Tool 声明

    CC->>SRV: call_tool(query_database, {sql: "SELECT ..."})
    SRV->>DB: 执行 SQL
    DB-->>SRV: 返回结果集
    SRV-->>CC: TextContent(JSON 结果)
    CC-->>CC: 解析并展示给用户
```

---

## 四、Plan B：Supervisor DB Agent

### 执行流程

```mermaid
flowchart TD
    Start([用户 Query]) --> Sup{Supervisor LLM<br/>RouteDecision}
    Sup -->|route=parser| Parser[Parser Agent<br/>日志 Tool]
    Sup -->|route=analyzer| Analyzer[Analyzer Agent<br/>RAG Tool]
    Sup -->|route=reporter| Reporter[Reporter<br/>结构化输出]
    Sup -->|route=db| DB[DB Agent<br/>MySQL Tool]
    Sup -->|route=END| End([结束])
    Parser --> Sup
    Analyzer --> Sup
    Reporter --> Sup
    DB --> Sup
```

### RouteDecision 扩展

```python
class RouteDecision(BaseModel):
    next: Literal["parser", "analyzer", "reporter", "db", "END"]
    reason: str
```

新增 `"db"` 选项，Supervisor 看到数据库相关问题时路由到 DB Agent。

### DB Agent 的 3 个 Tool

```python
@tool
def list_tables() -> dict:
    """列出 MySQL 数据库中所有表名。"""
    with _get_db_engine().connect() as conn:
        rows = conn.execute(text("SHOW TABLES")).fetchall()
    return {"tables": [r[0] for r in rows]}

@tool
def describe_table(table_name: str) -> dict:
    """查看指定表的字段结构。"""
    with _get_db_engine().connect() as conn:
        rows = conn.execute(text(f"DESCRIBE `{table_name}`")).fetchall()
    return {"table": table_name, "columns": [...]}

@tool
def query_database(sql: str) -> dict:
    """执行 SELECT 查询。禁止写操作。"""
    if not sql.strip().upper().startswith("SELECT"):
        return {"error": "只允许 SELECT 查询，拒绝写操作"}
    with _get_db_engine().connect() as conn:
        result = conn.execute(text(sql))
        ...
    return {"columns": ..., "rows": ..., "count": ...}
```

### DB Agent Node

```python
db_subgraph = create_agent(
    llm,
    tools=[list_tables, describe_table, query_database],
    system_prompt="""你是数据库查询专家。
先用 list_tables 了解有哪些表，
用 describe_table 了解表结构，
用 query_database 执行 SELECT 查询，
用自然语言汇总查询结果。""",
)

def db_agent_node(state: SupervisorState) -> dict:
    result = db_subgraph.invoke(
        {"messages": [("user", state["user_query"])]},
        {"recursion_limit": 10},
    )
    output = result["messages"][-1].content
    return {"agent_outputs": [f"[DB] {output}"]}
```

### Supervisor Prompt 新增路由规则

```
- 含"用户/订单/数据库/查询 MySQL/业务数据"等关键词 → db
```

### Plan B 实际运行结果

```bash
export MYSQL_URL="mysql+pymysql://root:dev123456@localhost:3307/testdb"
.venv/bin/python tech_showcase/langgraph_supervisor.py \
  --query "查询所有用户和他们的订单总金额，按金额降序排列"
```

```
🎯 [Supervisor] 路由 → db（用户查询涉及数据库订单统计）
─── [DB Agent] 开始查询数据库 ───

第 1 步：[DB] 查询结果显示了所有用户及其订单的总金额，按金额从高到低排序：
1. 李四 - 12999.0 元
2. 张三 - 8298.0 元（iPhone 15 + AirPods）
3. 王五 - 4599.0 元

流程结束，共调度 2 次 Supervisor
```

---

## 五、两种方案对比

| 维度 | Plan A（MCP Server） | Plan B（DB Agent） |
|---|---|---|
| 使用者 | 外部 AI 客户端（Claude Code / Claude Desktop / Cursor） | 本项目 Supervisor Agent |
| 通信方式 | stdio + MCP JSON-RPC 协议 | 同进程函数调用（SQLAlchemy） |
| 代码位置 | `mysql_mcp_server/server.py` | `tech_showcase/langgraph_supervisor.py` |
| 安全约束 | `query_database` 拒绝非 SELECT | 同上 |
| 启动方式 | Claude Code 读 `.mcp.json` 自动启动子进程 | 随 Supervisor Graph 启动 |
| 适用场景 | 日常对话查数据、跨项目复用 Tool | 多 Agent 工作流内的数据库查询 |

---

## 六、Java 类比速查

| 概念 | Java 世界 |
|---|---|
| MySQL MCP Server | 独立的 gRPC / Dubbo 服务，暴露数据查询接口 |
| MCP stdio transport | 本地进程间通信（类比 Unix Domain Socket） |
| `.mcp.json` | Spring Cloud 的服务注册配置 |
| `@tool` 装饰器 | `@Service` 注解 |
| SQLAlchemy `create_engine` | `DataSource` / `HikariCP` 连接池 |
| `query_database` 只允许 SELECT | DAO 层只开 `findXxx` 不开 `deleteXxx` |
| DB Agent ReAct 循环 | 自动拼 SQL 的"智能 DAO" |

---

## 七、常用命令

```bash
# 启动 MySQL Docker
docker compose up -d mysql

# 进入 MySQL 终端
docker compose exec mysql mysql -uroot -pdev123456 testdb

# 本地测试 MySQL MCP Server（stdin EOF 会退出）
MYSQL_URL="mysql+pymysql://root:dev123456@localhost:3307/testdb" \
  .venv/bin/python mysql_mcp_server/server.py < /dev/null

# 跑 DB Agent（Plan B）
export MYSQL_URL="mysql+pymysql://root:dev123456@localhost:3307/testdb"
.venv/bin/python tech_showcase/langgraph_supervisor.py --query "查询 pending 状态的订单"

# 停止 MySQL
docker compose stop mysql
```
