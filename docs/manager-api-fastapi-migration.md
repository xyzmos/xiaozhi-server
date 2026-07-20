# manager-api 到 FastAPI 迁移说明

## 目标与边界

`main/manager-api-fastapi` 是 `main/manager-api` 的兼容替代实现。迁移只替换管理 API
进程，不改变 MySQL 表、Liquibase 历史、Redis 业务语义，也不要求 manager-web、
manager-mobile 或 xiaozhi-server 修改现有 URL。Java 实现继续保留，作为行为基线和
回滚实现。

本次迁移不采用双写。灰度期间，每个业务域在任一时刻只有一个写入方；读流量可以按
请求切分，写流量必须按业务域整体切换。

## 架构

```mermaid
flowchart LR
    C["Web / Mobile / xiaozhi-server / Device"] --> N["Nginx /xiaozhi"]
    N --> A["FastAPI API workers"]
    A --> R["Routers"]
    R --> S["Services / transaction boundaries"]
    S --> P["Repositories / SQLAlchemy async"]
    S --> I["External integration clients"]
    P --> M[("Existing MySQL schema")]
    S --> D[("Redis Java compatibility layer")]
    J["Standalone jobs worker"] --> S
    L["Original Liquibase changelog"] --> X["Migration runner"]
    X --> M
```

代码按职责分为：

- `app/routers`：URL、HTTP 方法、Header/Query/Body 绑定和响应形态。
- `app/services`：权限后的业务规则、事务边界、跨表级联和外部调用编排。
- `app/repositories`：现有 MySQL 表上的参数化 SQL、行锁和分页。
- `app/schemas`：兼容现有字段别名及请求模型。
- `app/integrations`：LLM、MQTT gateway、MCP、RAGFlow、语音克隆和声纹客户端。
- `app/jobs`：独立的定时任务进程；API worker 不启动定时任务。
- `app/core`：数据库 Token 认证、国际化、Java JSON/Long 兼容、SM2、Redis 编解码、
  Snowflake ID 和健康检查。

所有业务路由保留 `/xiaozhi` 前缀。普通 API 返回 `{code,msg,data}`；认证过滤器、
业务异常和请求校验均由兼容处理器转换，不把 FastAPI 默认的 401、403 或 422 直接
暴露给客户端。OTA、播放和文件下载等原本返回裸 JSON、文本或二进制的接口继续保持
其原始响应类型。

## 数据库兼容策略

### Schema 与迁移

原目录 `main/manager-api/src/main/resources/db/changelog/` 仍是唯一 schema source of
truth。不得把既有 changeset 改写成 Alembic，也不得修改已应用 changeset 的 ID、作者或
校验和。

Python 部署必须先运行独立迁移镜像或 `scripts/run-migrations.sh`。迁移 runner 直接打包
原 Java Liquibase 资源，因此与保留的 Java 服务使用相同的 `DATABASECHANGELOG` 历史。
宿主机执行脚本时，`JAVA_RESOURCES_DIR` 必须指向仓库中的
`main/manager-api/src/main/resources`；不要使用只存在于应用镜像内的
`/opt/xiaozhi/java-resources`。本机隔离数据库的完整命令见“配置与启动 / 本地”。

`docker compose` 中 `manager-api-fastapi` 和 `manager-api-jobs` 都等待
`manager-api-migrate` 成功退出，避免应用在未完成迁移时接流量。

### 事务、锁与 ID

- Service 层在一次事务中完成智能体创建/更新/删除、插件/标签/纠错词映射、设备解绑、
  快照恢复及其他多表操作；异常时显式回滚。
- 智能体更新和恢复先对 `ai_agent` 执行 `SELECT ... FOR UPDATE`，序列化同一智能体的
  快照版本分配和状态令牌校验。
- 快照版本仍使用 `(agent_id, version_no)` 唯一约束及同一事务内的 `MAX+1` 插入；行锁
  防止并发恢复或更新竞争。
- 需要 Long 主键的管理表继续使用与 Java epoch/node/sequence 布局一致的 Snowflake
  生成器；原本使用 32 位 UUID 的业务表仍使用无连字符 UUID。
- 不新增数据库外键，也不改表、索引、字符集或 MySQL 类型。

### Java/Python 并存

并存期必须给写请求建立确定的域路由，例如 `agent/*` 全部指向一个实现，不能把同一域
中的增删改请求在 Java 与 Python 之间随机分配。建议域切换顺序为只读配置、系统管理、
模型/音色、设备、智能体、知识库和外部集成。域回切前先停止该域的新写入并等待在途
请求完成。

## Redis 兼容策略

默认继续使用 Java 已有 key 名称和 TTL。`app/core/redis.py` 实现 Spring Data
`RedisSerializer.json()` 使用的 Jackson wire format，包括：

- Map 的 `@class`、List/Set 的 wrapper-array；
- Object 槽位中 Long 的 `java.lang.Long` 包装；
- `java.util.Date` 的 epoch 毫秒包装；
- Java DTO/Entity 缓存所需的具体类名和字段类型；
- Hash 缓存写入后的 86400 秒默认 TTL。

该兼容层使 Java 回滚进程可以读取 FastAPI 写入的缓存。应用启动和正常测试不会执行
`FLUSHALL`；隔离测试脚本的 `reset` 只操作其自建 Redis 实例。定时任务使用 Redis
分布式锁和自动续租 watchdog，即使启动多个 jobs 容器，同一个任务也只有一个执行者。

## 安全与协议兼容

- 用户 Token 仍保存在 `sys_user_token`，按数据库过期时间校验；没有替换为 JWT。
- 登录密文继续使用 SM2 C1C3C2，黄金向量由 Java 和 Python 双向解密测试校验。
- `/config/*`、聊天记录上报/摘要/标题及地址簿内部接口继续校验数据库中的
  `server.secret` Bearer 值。
- OTA、WebSocket 和 MQTT 保留原 HMAC、Base64、时间戳、Client-Id/Device-Id 及 token
  格式。
- 密钥只通过环境变量或原参数表提供；`.env.example` 和部署文档不包含真实凭证。

## 配置与启动

### 本地

`.env.example` 是容器 Compose 模板，其中的 `mysql`、`redis` 是 Compose 服务名，
`/opt/xiaozhi/java-resources` 是镜像内路径，不能原样复制后用于宿主机进程。下面的流程
显式使用 `127.0.0.1:13316` 上的隔离 MySQL、`127.0.0.1:16379` 上的隔离 Redis，以及
仓库原始 Liquibase/i18n 资源；不会连接或迁移现有开发数据库：

```bash
cd main/manager-api-fastapi
uv sync --locked

./scripts/isolated-env.sh start

LIQUIBASE_URL='jdbc:mysql://127.0.0.1:13316/manager_fastapi_test?useUnicode=true&characterEncoding=UTF-8&serverTimezone=Asia/Shanghai&allowMultiQueries=true' \
LIQUIBASE_USERNAME='xiaozhi_test' \
LIQUIBASE_PASSWORD='isolated-test-only' \
JAVA_RESOURCES_DIR="$PWD/../manager-api/src/main/resources" \
MAVEN_BIN="$PWD/../../.runtime/maven/bin/mvn" \
MAVEN_LOCAL_REPOSITORY="$PWD/../../.runtime/m2" \
JAVA_HOME="$PWD/../../.runtime/jdk" \
./scripts/run-migrations.sh

eval "$(./scripts/isolated-env.sh env)"
export APP_ENVIRONMENT=development
export APP_DATABASE_URL="$TEST_FASTAPI_DATABASE_URL"
export APP_REDIS_URL="$TEST_FASTAPI_REDIS_URL"
export APP_JAVA_RESOURCES_DIR="$PWD/../manager-api/src/main/resources"
export APP_UPLOAD_DIR="$PWD/.test-runtime/local-uploadfile"
mkdir -p "$APP_UPLOAD_DIR"
./scripts/start-api.sh
```

上述 `eval` 会得到明确的 localhost URL（FastAPI 测试库和 Redis DB 2）。定时任务必须
作为单独进程启动；新终端需要重复 `eval` 及四个 `APP_*` 路径/URL 导出，不能让 jobs
进程落回 `.env.example` 的 Docker DNS：

```bash
cd main/manager-api-fastapi
eval "$(./scripts/isolated-env.sh env)"
export APP_ENVIRONMENT=development
export APP_DATABASE_URL="$TEST_FASTAPI_DATABASE_URL"
export APP_REDIS_URL="$TEST_FASTAPI_REDIS_URL"
export APP_JAVA_RESOURCES_DIR="$PWD/../manager-api/src/main/resources"
export APP_UPLOAD_DIR="$PWD/.test-runtime/local-uploadfile"
./scripts/start-jobs.sh
```

API 默认监听 `0.0.0.0:8002`，兼容根路径为
`http://127.0.0.1:8002/xiaozhi`。`APP_WORKERS` 可以大于 1；任务不会随 API worker
复制。验证结束后运行 `./scripts/isolated-env.sh stop`。生产环境不得设置
`APP_ALLOW_START_WITHOUT_DEPENDENCIES=true`。

仓库统一启动脚本继承当前 shell 的上述环境变量；FastAPI 是默认实现，保留的 Java
实现可直接用于本地回滚：

```bash
cd "$(git rev-parse --show-toplevel)"
scripts/restart-local-services.sh --manager-api fastapi --wait 180
scripts/restart-local-services.sh --manager-api java --wait 180
```

### 容器

下面的 `mysql`、`redis` 只在容器网络确实提供对应 DNS 名时有效，否则必须替换为该网络
可访问的真实主机名。API 镜像内的 Java 资源路径是 `/opt/xiaozhi/java-resources`，迁移
镜像则把同一仓库资源打包到 `/migration/java-resources`。以下示例中的凭证必须替换，
并应通过部署平台的 secret 注入而不是提交到仓库：

```bash
cd main/manager-api-fastapi
export LIQUIBASE_URL='jdbc:mysql://mysql:3306/xiaozhi_esp32_server?serverTimezone=Asia/Shanghai'
export MYSQL_USER='xiaozhi'
export MYSQL_PASSWORD='replace-me'
export FASTAPI_DATABASE_URL='mysql+asyncmy://xiaozhi:replace-me@mysql:3306/xiaozhi_esp32_server?charset=utf8mb4'
export REDIS_URL='redis://redis:6379/0'
export MANAGER_API_UPSTREAM='manager-api-fastapi:8002'
docker compose build
docker compose up -d
```

若 `MANAGER_API_UPLOAD_SOURCE` 指向保留 Java 服务的宿主机上传目录，必须在启动前让 Java
运行用户与容器 UID 10001 都具备读写和目录遍历权限；不要盲目 `chown -R` 导致 Java 失去
访问权，应使用部署环境的共享组或 ACL。空 named volume 在 Docker 通常会继承镜像中
`/data/uploads` 的 UID，但并非所有 OCI runtime 都实现相同 copy-up 语义；必须以容器内
UID 10001 做一次写入预检。`/xiaozhi/health/ready` 同时检查上传目录可写性，权限不正确时
返回 HTTP 503 和 `data.uploads=false`，不得绕过该检查接入流量。Apple Container 的一次性
卷初始化实测命令和结果记录在测试报告中。

`MANAGER_API_UPSTREAM` 默认值是 `manager-api-fastapi:8002`。修改变量后必须重建 Nginx
容器才能重新渲染配置；切到 FastAPI 和整服务回滚到 Java 的命令分别为：

```bash
MANAGER_API_UPSTREAM='manager-api-fastapi:8002' \
  docker compose up -d --no-deps --force-recreate manager-api-nginx

MANAGER_API_UPSTREAM='<Nginx 容器可访问的 Java 主机名或 IP>:8002' \
  docker compose up -d --no-deps --force-recreate manager-api-nginx
```

Java 地址必须能从 Nginx 容器网络解析和访问。内置 Nginx 的这个变量会切换整个
`/xiaozhi`；逐业务域灰度需要在上层网关按路径配置两个 upstream，仍须遵守“同一业务域
只有一个写入方”。

API 镜像（包括 jobs 命令）和迁移镜像都声明 `USER 10001:10001`，以非 root 用户运行。
Compose 还为 API/jobs 设置只读根文件系统和 `/tmp` tmpfs；`/data/uploads` 是它们唯一的
持久写目录，并通过 `/app/uploadfile` 符号链接兼容数据库中的 Java 相对路径。迁移容器是
一次性非 root 进程，但 Compose 没有把它标为只读根文件系统。Nginx 镜像没有声明
非 root `USER`，不能将其描述为非 root 镜像；它通过 Compose 的 `read_only: true` 及
`/var/cache/nginx`、`/var/run`、`/tmp` 三个 tmpfs 加固。Nginx 保留 `/xiaozhi/` 路径，
关闭上传请求缓冲并设置 100 MiB 上限。健康检查分为：

- `/xiaozhi/health/live`：进程存活；
- `/xiaozhi/health/ready`：MySQL、Redis 和上传目录写权限都可用才返回 HTTP 200，否则
  HTTP 503；`data.database`、`data.redis`、`data.uploads` 可直接定位失败项。

SIGTERM 触发 Uvicorn 优雅关闭；compose 给 API 40 秒清理在途请求和连接池。

### 容器验证边界

本次仓库内的实际容器运行验证使用 Apple Container 1.0.0，覆盖镜像构建、隔离 MySQL
迁移、双 API worker、独立 jobs、Nginx 路由、只读文件系统、上传卷和 SIGTERM 优雅
关闭。`docker-compose.yml` 已通过 YAML 解析和自动化部署断言，但当前验证主机没有执行
`docker compose up`，因此不能把 Apple Container 的运行结果表述为 Docker Compose
端到端通过。镜像摘要、实际命令和运行结果见
`docs/manager-api-fastapi-test-report.md`；在目标 Docker/Compose 环境切流前，仍需按上面
命令执行一次迁移、ready 检查和 Nginx upstream 冒烟测试。

## 灰度切流

1. 备份当前配置并确认 Java 基线健康；不要停止 Java。
2. 对目标数据库执行原 Liquibase runner，确认 changeset 数量和校验和无差异。
3. 启动 FastAPI API 但暂不接写流量，检查 live/ready、日志和外部 mock。Python jobs
   只在隔离环境验证后停止，生产中暂不持续运行，避免与 Java 调度器同时写入。
4. 先镜像或回放脱敏的只读请求，比较状态、Body、Header、数据库读结果和缓存读取。
5. 按业务域把只读流量从 1% 提升到 10%、50%、100%，监控错误码、P95、数据库连接、
   Redis 命中与外部服务错误。
6. 对一个完整业务域建立维护窗口，停止该域 Java 新写入，等待在途事务结束，然后把该域
   写路由切到 FastAPI。记录切换时间和最后写入方。
7. 逐域重复；稳定观察期内保留 Java 镜像、配置和回切路由。
8. 所有域稳定后才把 jobs 所有权切给 Python；Java 的定时任务进程必须同时停用，避免
   两套调度器并行。

## 回滚

1. 冻结待回滚业务域的新写入，等待 FastAPI 在途请求和 jobs 当前轮次结束。
2. 停止 Python jobs，确认 Redis 分布式锁已释放；不要清空 Redis。
3. 将该域的 Nginx upstream 切回原 Java `manager-api`，保持 `/xiaozhi` 路径不变。
4. 用 Java 健康检查和代表性读请求确认 Token、缓存、上传文件与数据库数据可读。
5. 恢复 Java 写流量并记录回滚边界；不要让 FastAPI 继续写该域。
6. 若问题来自新 changeset，只能新增一个经评审的 Liquibase 前向修复；不得删除或改写
   `DATABASECHANGELOG` 历史。

容器整服务回滚时，先把 `<JAVA_UPSTREAM>` 替换为 Nginx 容器可访问的真实地址，再只
重建代理；`--no-deps` 可避免回滚命令意外重启 FastAPI 或重复执行迁移：

```bash
MANAGER_API_UPSTREAM='<JAVA_UPSTREAM>:8002' \
  docker compose up -d --no-deps --force-recreate manager-api-nginx
```

FastAPI 没有改变现有 schema，且 Redis 写入采用 Java 兼容格式，因此正常应用回滚不需要
数据反向迁移。若外部系统已接收不可撤销操作，按对应供应商的业务补偿流程处理，不能用
数据库回滚伪造外部成功或失败。

## 隔离验证

`scripts/isolated-env.sh` 只创建 `manager_java_test`、`manager_fastapi_test` 两个测试库和
端口 `16379` 上的独立 Redis；其中的测试密码仅用于本机隔离环境。标准流程是：

```bash
cd main/manager-api-fastapi
./scripts/isolated-env.sh start
./scripts/isolated-env.sh reset
./scripts/isolated-env.sh migrate
eval "$(./scripts/isolated-env.sh env)"
.venv/bin/pytest -m integration -q
./scripts/isolated-env.sh stop
```

实际执行结果、差分用例和不能使用真实凭证完成的联调项记录在
`docs/manager-api-fastapi-test-report.md`；逐接口状态记录在
`docs/manager-api-fastapi-compatibility.md`。
