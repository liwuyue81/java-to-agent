# Docker 部署指南

> 以 `java-to-agent` 项目为例，从零理解 Docker 部署的完整链路。

---

## 一、Docker 是什么（解决什么问题）

### 经典痛点

```
开发：「在我电脑跑得好好的！」
运维：「服务器上就是起不来！」
```

原因是：代码跑起来依赖的不只是代码本身，还有：
- Python 版本（3.11 vs 3.9）
- 安装的包版本（langchain 0.3 vs 0.2）
- 操作系统差异（macOS vs Linux）
- 环境变量是否配好

**Docker 的解决思路**：把「代码 + 依赖 + 运行环境」一起打包成一个**镜像**，
哪台机器跑镜像，环境都完全一致。

### Java 类比

| Docker 概念 | Java 世界 |
|---|---|
| **镜像**（Image） | 可执行的 JAR 包（打包好的、能跑的） |
| **容器**（Container） | 正在运行的 JVM 进程 |
| **Dockerfile** | Maven 的 `pom.xml` + 构建脚本（描述怎么打包） |
| **docker-compose** | `docker run` 的配置文件版本（管多个服务） |
| **Volume 挂载** | 外挂的数据目录（类比数据库文件不进 JAR） |
| **Registry** | Maven 私服 Nexus（存镜像的地方） |

---

## 二、Dockerfile 逐行解释

这个项目的完整 Dockerfile：

```dockerfile
# ── 构建阶段 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ── 运行阶段 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["uvicorn", "tech_showcase.fastapi_service:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--log-level", "info"]
```

### 2.1 多阶段构建（两个 FROM）

```dockerfile
FROM python:3.11-slim AS builder   # 第一阶段：专门用来装依赖
...
FROM python:3.11-slim              # 第二阶段：真正运行的镜像
```

**为什么要两个阶段？**

`pip install` 过程中会下载大量临时文件、编译工具（gcc 等）。
如果只用一个阶段，这些编译垃圾都留在最终镜像里，体积虚大。

多阶段构建：
- **builder 阶段**：装依赖（允许有垃圾）
- **runtime 阶段**：只从 builder 里复制干净的 site-packages，不带垃圾

**效果**：镜像体积通常能减少 30-50%。

---

### 2.2 先复制 requirements，再复制代码

```dockerfile
COPY requirements.txt .                          # ← 先只复制依赖文件
RUN pip install --no-cache-dir -r requirements.txt  # ← 装依赖
COPY . .                                         # ← 最后才复制业务代码
```

**Docker 的 Layer 缓存机制**：每一行指令都是一个 layer，
Docker 会缓存没变化的 layer，只重跑有变化的。

如果先 `COPY . .` 再装依赖：
- 改一行业务代码 → 所有 layer 失效 → 重新跑 `pip install`（几分钟）

先 `COPY requirements.txt` 再装依赖：
- 改业务代码 → 只有最后一个 layer 失效 → pip install 命中缓存（秒级）

**类比 Java**：就像 Maven 先下载依赖（`.m2` 缓存），
代码变了不需要重新下依赖。

---

### 2.3 `--no-cache-dir`

```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
```

pip 默认会把下载的 whl 文件缓存到磁盘（方便以后快速重装）。
容器里装完就用，不需要 pip 缓存，加 `--no-cache-dir` 让镜像小几十 MB。

---

### 2.4 `ENV PYTHONUNBUFFERED=1`

```dockerfile
ENV PYTHONUNBUFFERED=1
```

Python 默认会缓冲 stdout/stderr 输出（积累到一定量才刷）。
在容器里这会导致：程序出错崩掉了，日志还在缓冲区里没输出，
`docker logs` 看不到任何报错信息。

`PYTHONUNBUFFERED=1` 强制立即刷出，`docker logs -f` 能实时看到所有日志。

---

### 2.5 `EXPOSE 8765`

```dockerfile
EXPOSE 8765
```

**注意**：`EXPOSE` 只是一个声明（文档作用），告诉"这个容器会用 8765 端口"。
真正让外面能访问，要在 `docker run -p` 或 `docker-compose` 的 `ports` 里配。

类比：就像 Java 服务的 `server.port=8765` 告诉你用哪个端口，
但实际暴露给外网还需要防火墙/Nginx 配置。

---

### 2.6 CMD vs ENTRYPOINT

```dockerfile
CMD ["uvicorn", "tech_showcase.fastapi_service:app",
     "--host", "0.0.0.0", "--port", "8765", "--log-level", "info"]
```

- `CMD`：容器默认执行的命令，可以在 `docker run` 时覆盖
- `ENTRYPOINT`：容器的固定入口，不能轻易覆盖

`--host 0.0.0.0` 是关键——如果写 `127.0.0.1`，
容器内服务只监听本地，外面访问不到。`0.0.0.0` 表示监听所有网卡。

---

## 三、docker-compose.yml 逐行解释

```yaml
services:
  agent:
    build: .
    image: java-to-agent:latest
    container_name: java-to-agent
    ports:
      - "8765:8765"
    env_file:
      - .env
    environment:
      - PYTHONUNBUFFERED=1
    volumes:
      - ./logs:/app/logs
      - ./chroma_db:/app/chroma_db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    restart: unless-stopped
```

### 3.1 `build: .`

告诉 docker-compose：镜像从当前目录的 Dockerfile 构建。
运行 `docker compose up` 时如果镜像不存在，会自动 build。

---

### 3.2 `ports: "8765:8765"`

```yaml
ports:
  - "宿主机端口:容器内端口"
  - "8765:8765"
```

容器是隔离的网络环境，需要显式「打洞」才能从外面访问。
`8765:8765` 表示：宿主机的 8765 → 容器内的 8765。

可以改成 `"9000:8765"` 让外部用 9000 端口访问，而容器内不变。

---

### 3.3 `env_file: .env`（关键安全设计）

```yaml
env_file:
  - .env
```

**为什么这样做**：API key 等敏感信息不能进镜像。

- `.env` 在 `.dockerignore` 和 `.gitignore` 里都排除了
- 只在宿主机本地存在
- docker-compose 启动时读取 `.env`，把里面的变量注入容器
- 镜像本身干净，可以安全推到任何 Registry

类比：Spring Boot 的 `application-prod.yaml` 放在服务器本地，
不打进 JAR 包里。

---

### 3.4 `volumes` 挂载

```yaml
volumes:
  - ./logs:/app/logs         # 宿主机 logs 目录 → 容器 /app/logs
  - ./chroma_db:/app/chroma_db  # 宿主机 chroma_db → 容器 /app/chroma_db
```

**为什么需要 volume**：

容器是无状态的——容器重启，容器内的文件全部丢失。
- `logs/app.log` 是业务数据，必须持久化
- `chroma_db/` 是向量数据库，重建一次要几分钟，必须持久化

Volume 挂载让容器里的文件实际写在宿主机上，
容器重启不影响数据。

类比：数据库的数据文件挂在宿主机磁盘，而不是塞进 Docker 镜像。

---

### 3.5 `healthcheck`

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
  interval: 30s    # 每 30 秒检查一次
  timeout: 10s     # 超过 10 秒没响应算失败
  retries: 3       # 连续 3 次失败才标 unhealthy
  start_period: 15s # 容器启动后 15 秒才开始检查（等服务初始化）
```

Docker 会定期调 `/health` 端点，根据 HTTP 状态码判断服务是否健康。
`docker ps` 里能看到 `(healthy)` 或 `(unhealthy)` 状态。

---

### 3.6 `restart: unless-stopped`

```yaml
restart: unless-stopped
```

| 策略 | 含义 |
|---|---|
| `no` | 不自动重启（默认） |
| `always` | 总是重启，包括 Docker Desktop 重启后 |
| `unless-stopped` | 自动重启，除非你手动 `docker compose stop` |
| `on-failure` | 只在容器异常退出时重启 |

生产环境推荐 `unless-stopped`：服务崩了自动拉起，
手动维护时 `docker compose stop` 就能停，不会自动重拉。

---

## 四、这个项目完整部署流程

### 前置条件

- 已安装 Docker Desktop
- 项目目录下有 `.env` 文件（含 `API_KEY`、`API_BASE_URL` 等）
- `logs/app.log` 存在（向量检索依赖日志文件）

### 5 步跑起来

```bash
# 1. 进入项目目录
cd /path/to/java-to-agent

# 2. 构建镜像（第一次需要几分钟，之后有缓存很快）
docker build -t java-to-agent:latest .

# 3. 后台启动服务
docker compose up -d

# 4. 查看启动日志确认正常
docker compose logs -f
# 看到 "Uvicorn running on http://0.0.0.0:8765" 说明启动成功

# 5. 验证服务
curl http://localhost:8765/health
# 返回 {"status":"ok","provider":"dashscope","model":"qwen-plus"} 即成功
```

### 验证浏览器访问

打开 `http://localhost:8765/`，能看到聊天界面，和本地直接跑 uvicorn 效果一样。

---

## 五、常用命令速查

```bash
# 启动（后台）
docker compose up -d

# 启动并实时看日志（前台，Ctrl+C 停止）
docker compose up

# 停止服务
docker compose down

# 重启服务
docker compose restart

# 查看日志（最近 50 行）
docker compose logs --tail=50

# 实时追踪日志
docker compose logs -f

# 进入容器 shell（调试用）
docker compose exec agent bash

# 查看容器状态（含 healthy/unhealthy）
docker compose ps

# 重新构建镜像（代码或 requirements 变了之后）
docker compose build

# 重新构建并启动
docker compose up -d --build

# 查看所有镜像
docker images

# 删除旧镜像（释放磁盘）
docker image prune
```

---

## 六、.dockerignore 的作用

`.dockerignore` 和 `.gitignore` 类似，告诉 Docker 构建时忽略哪些文件：

```
.venv/          # 本地虚拟环境，镜像里不需要（镜像自己装）
.env            # API key，绝不进镜像
chroma_db/      # 运行时数据，通过 volume 挂载
__pycache__/    # Python 缓存，镜像里没用
.git/           # Git 历史，镜像不需要
docs/           # 文档，镜像不需要
```

没有 `.dockerignore` 的话，`COPY . .` 会把 `.venv`（几百 MB）
也复制进镜像，白白增大体积、减慢构建速度。

---

## 七、常见问题

**Q：改了代码，怎么更新容器？**

```bash
docker compose build   # 重新构建镜像
docker compose up -d   # 重启（自动用新镜像）
# 或者一步到位
docker compose up -d --build
```

**Q：容器起来了但访问不了？**

```bash
docker compose ps       # 看是否 healthy
docker compose logs -f  # 看有没有报错
```

常见原因：`.env` 里的 `API_KEY` 没配，服务启动但 LLM 调用会 401。

**Q：如何在服务器上部署（不是本机）？**

```bash
# 方案 1：把镜像推到 Registry，服务器 pull
docker tag java-to-agent:latest your-registry/java-to-agent:v1.0
docker push your-registry/java-to-agent:v1.0
# 服务器上：
docker pull your-registry/java-to-agent:v1.0
docker compose up -d

# 方案 2：直接把代码 scp 到服务器，服务器上 build
scp -r . user@server:/app/java-to-agent
ssh user@server "cd /app/java-to-agent && docker compose up -d --build"
```

**Q：如何完全清理所有 Docker 资源？**

```bash
docker compose down       # 停容器
docker image rm java-to-agent:latest  # 删镜像
docker volume prune       # 清悬空 volume
```
