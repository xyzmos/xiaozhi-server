# manager-api FastAPI 迁移测试报告

> 执行日期：2026-07-20（Asia/Shanghai）
>
> 工作目录：`/Users/mie/Desktop/Repo/xiaozhi-esp32-server`
>
> FastAPI 目标：`main/manager-api-fastapi`
> Java 基线：`main/manager-api`

本报告只记录实际执行并有输出或落盘证据的检查。结构路由闭合、154 条未认证/非法请求面
差分、154 条已认证安全业务/校验差分、领域测试和 49 条深度 Java/FastAPI 差分是不同强度
的证据，不互相替代。生产外部服务和真实硬件没有验证的部分，均不会写成通过。

## 1. 结果摘要

| 检查项 | 通过 | 失败/错误 | 跳过 | 结论 |
|---|---:|---:|---:|---|
| Java 基线测试 | 98 | 0 | 0 | 最终复跑 `BUILD SUCCESS`，15.602 秒 |
| FastAPI 全量 pytest（最终回归） | 139 | 0 | 0 | 12.75 秒；含上传卷 readiness 与证据脱敏回归 |
| 隔离 MySQL/Redis 集成测试复跑 | 7 | 0 | 0 | 事务、锁、TTL、job 单实例与 watchdog 全绿 |
| Java→FastAPI 未认证/非法请求面差分 | 154 | 0 | 0 | 每条 Java 路由各 1 个无成功写入的缺认证或非法请求，逐项比较 status/body/Content-Type |
| Java→FastAPI 已认证安全业务/校验差分 | 154 | 0 | 0 | 每条 Java 路由各 1 个带正确认证的安全业务或校验请求；runner 有意不执行成功写入 |
| Java→FastAPI 深度差分契约 | 49 | 0 | 0 | 成功、主要错误与数据库副作用；直接覆盖 21/154 条 Java 路由 |
| 简单性能测试 | 480 请求 | 0 请求错误 | 不适用 | 4 场景 × 2 服务 × 60 次计量请求 |
| Java 路由结构清单 | 154/154 | 0 | 0 | FastAPI 注册闭合；结构证据，不等同逐接口行为证据 |
| 三端消费者调用点 | 188/188 | 0 | 0 | Web 134、Mobile 46、xiaozhi-server 8 个调用点均可解析 |
| FastAPI Ruff | 通过 | 0 | 不适用 | `app tests scripts` |
| FastAPI mypy | 70 个源文件 | 0 | 不适用 | strict 配置下通过 |
| FastAPI compileall | 通过 | 0 | 不适用 | `app tests scripts` |
| 锁文件与依赖同步 | 通过 | 0 | 不适用 | locked 环境共 55 packages |
| Python sdist/wheel | 2 个产物 | 0 | 不适用 | 冷环境完整依赖安装后可导入，路由数 163 |
| manager-web | i18n、5 unit、13 snapshot、build 全过 | 0 | 0 | build 有 4 条既有 size/precache warning |
| manager-mobile | type、lint、14 snapshot、mp-weixin build 全过 | 0 | 0 | 使用仓库声明的 pnpm 10.10.0 |
| xiaozhi-server | compileall 通过 | 0 | 不适用 | 除性能脚本外没有自动单测；8 个调用由 consumer 契约检查 |
| 真实付费/生产外部服务 | 0 | 不适用 | 不适用 | 无真实凭证，不声称联调通过 |
| 容器迁移、API、jobs 与 Nginx | 通过 | 0 | 0 | Apple Container 1.0.0 实际 build/run；Compose 仅做静态验证，未伪装为 `docker compose up` |

最终可重复执行的全量测试、隔离差分、集成、构建和容器运行验证均为绿色。以下范围限制必须
与绿色测试分开陈述：

1. 全部 154 条 Java 路由均执行了两次差分：一次未认证/非法请求，一次已认证安全业务/校验
   请求。第二个 runner 为保护隔离 fixture，有意不执行成功写入；49 个深度 checks 直接命中
   21 条路由并覆盖代表性成功、错误和数据库副作用。因此两层全路由差分仍不等同于每条路由
   的完整成功写入生命周期和全部错误路径差分。
2. 没有真实凭证、生产网络或硬件的外部集成未被计入通过。

## 2. 验证环境

| 组件 | 实际版本/配置 |
|---|---|
| 主机 | macOS 27.0，arm64 |
| Java | Oracle JDK 21.0.11 LTS |
| Maven | 3.9.9，使用仓库 `.runtime/m2` |
| Python | 3.10.20，`main/manager-api-fastapi/.venv` |
| MySQL | Community Server 8.0.46；隔离端口 `13316` |
| Redis | 8.8.0；隔离端口 `16379` |
| Node.js | v24.18.0 |
| npm | 11.16.0 |
| manager-mobile pnpm | Corepack 解析的 10.10.0 |
| OCI runtime | Apple Container 1.0.0；本机没有可用 Docker/Podman daemon |
| 容器架构 | linux/arm64 |
| 时区 | Asia/Shanghai |

隔离测试只重置 `manager_java_test`、`manager_fastapi_test` 两个测试 schema 和端口
`16379` 上的专用 Redis；没有连接、修改或清空开发 MySQL/Redis。Java 差分使用 Redis DB 1，
FastAPI 使用 DB 2；Java 单元验证显式使用 DB 3。

## 3. 实际执行命令

### 3.1 Java 基线

```bash
cd main/manager-api && \
JAVA_HOME=../../.runtime/jdk \
PATH="../../.runtime/jdk/bin:../../.runtime/maven/bin:$PATH" \
../../.runtime/maven/bin/mvn -o \
  -Dmaven.repo.local=../../.runtime/m2 \
  -Dspring.datasource.druid.url='jdbc:mysql://127.0.0.1:13316/manager_java_test?useUnicode=true&characterEncoding=UTF-8&serverTimezone=Asia/Shanghai&nullCatalogMeansCurrent=true&allowMultiQueries=true' \
  -Dspring.datasource.druid.username=xiaozhi_test \
  -Dspring.datasource.druid.password=isolated-test-only \
  -Dspring.data.redis.host=127.0.0.1 \
  -Dspring.data.redis.port=16379 \
  -Dspring.data.redis.database=3 \
  -Dspring.data.redis.password= \
  -DskipTests=false test
```

最终复跑结果：98 tests，0 failures，0 errors，0 skipped，`BUILD SUCCESS`，15.602 秒。Surefire
XML 位于 `main/manager-api/target/surefire-reports/`，各 suite 的 tests 合计为 98。

### 3.2 FastAPI 全量测试

```bash
cd main/manager-api-fastapi && \
eval "$(./scripts/isolated-env.sh env)" && \
APP_DATABASE_URL="$TEST_FASTAPI_DATABASE_URL" \
APP_REDIS_URL="$TEST_FASTAPI_REDIS_URL" \
APP_ENVIRONMENT=test \
.venv/bin/pytest -q
```

最终结果：139 passed、0 failed、0 skipped，12.75 秒。

### 3.3 隔离集成、两层全路由差分、深度差分和性能测试

```bash
cd main/manager-api-fastapi && ./scripts/run-isolated-contract-tests.sh
```

最终执行结果为 exit 0。脚本实际完成以下阶段：

- 启动并重置隔离 MySQL `13316`、Redis `16379`；
- 对 Java 与 FastAPI 两个 schema 分别执行原 Liquibase 101 个 changeSets；
- 启动 Java 基线 `18082`、FastAPI `18083`、确定性外部 mock `18084`；
- 生成并镜像固定用户、DB Token、Long ID、设备、agent、模型、纠错词和 OTA fixture；
- 执行 7 条隔离集成测试；
- 对 154 条 Java 路由各执行一条未认证或非法的安全请求面差分，不产生成功写入；
- 对 154 条 Java 路由各执行一条带正确认证的安全业务或校验差分，仍不产生成功写入；
- 执行 49 条 Java/FastAPI 差分检查并写入 JSON；
- 执行 480 次计量性能请求并写入 JSON；
- 对 FastAPI/mock 日志执行 warning、traceback、error 门禁；
- 退出时关闭 Java、FastAPI 和 mock，最终 `18082`～`18084` 没有监听进程。

最终阶段摘要（两行 154 分别对应未认证/非法和已认证安全业务/校验）：

```text
7 passed
{"total": 154, "passed": 154, "failed": 0, "skipped": 0}
{"total": 154, "passed": 154, "failed": 0, "skipped": 0}
{"total": 49, "passed": 49, "failed": 0, "skipped": 0}
{"measurements": 8, "requests_measured": 480, "errors": 0}
Isolated integration, two 154-route surfaces, deep differential, and performance tests passed.
```

机器结果：

- `main/manager-api-fastapi/compatibility/route-surface-results.json`
  - 生成时间：`2026-07-20T07:12:28.099864+00:00`
  - 154 passed、0 failed、0 skipped
- `main/manager-api-fastapi/compatibility/authenticated-route-results.json`
  - 生成时间：`2026-07-20T07:12:30.818073+00:00`
  - 154 passed、0 failed、0 skipped
- `main/manager-api-fastapi/compatibility/contract-results.json`
  - 生成时间：`2026-07-20T07:12:31.520810+00:00`
  - 49 passed、0 failed、0 skipped
- `main/manager-api-fastapi/compatibility/performance-results.json`
  - 生成时间：`2026-07-20T07:12:33.158826+00:00`
  - 480 requests、0 errors

### 3.4 FastAPI 静态、依赖和构建验证

```bash
cd main/manager-api-fastapi
.venv/bin/ruff check app tests scripts
.venv/bin/mypy app
.venv/bin/python -m compileall -q app tests scripts
uv lock --check && uv sync --locked
uv build --no-cache
```

结果：

- Ruff 通过；
- mypy：70 个源文件无问题；
- compileall：exit 0；
- lock check 与 locked sync：exit 0，共 55 packages；
- 无缓存构建 sdist 与 wheel 均成功。

构建产物另在临时冷虚拟环境验证。首次执行 `uv pip install --python
<临时环境>/bin/python --no-deps <wheel>` 后直接 import，因刻意没有安装 FastAPI 等运行依赖而
失败；这暴露的是冷 wheel 检查命令不完整，不是把失败隐藏为通过。随后执行带依赖的安装：

```bash
uv pip install --python <临时环境>/bin/python <wheel>
```

共安装 39 个锁定依赖。从仓库外 `/tmp` 导入成功，输出
`xiaozhi-manager-api 163`，证明不是依赖当前工作目录导入源码。

### 3.5 manager-web

```bash
cd main/manager-web && \
npm run check:i18n && \
npm run test:unit && \
npm run test:snapshot && \
npm run build
```

结果：

- i18n：6 个 locale，每个 1527 keys，key 结构一致；
- unit：5/5；
- snapshot：13/13；
- Vue 生产构建 exit 0（hash `71b64d002eb434ee`，1069 ms）；
- 输出有 4 条既有 bundle size/precache warning，没有将 warning 写成失败，也没有删除或放宽
  测试来取得绿色结果；另有 `caniuse-lite` 数据过期 17 个月提示，未擅自更新依赖。

### 3.6 manager-mobile

```bash
cd main/manager-mobile && \
corepack pnpm type-check && \
corepack pnpm lint && \
corepack pnpm test:snapshot && \
corepack pnpm build:mp
```

结果：type-check exit 0、lint exit 0、snapshot 14/14、mp-weixin build exit 0。构建提示
`caniuse-lite` 数据过期 20 个月及 uni-app 有新版本；两项均不影响退出码，未擅自更新依赖。

一次较早的失败尝试直接调用普通 `pnpm`，环境解析到 v11，并因非 TTY 下依赖目录清理提示而
终止；没有把该次尝试写成通过。最终命令显式使用 Corepack，解析到仓库声明的 pnpm 10.10.0。

### 3.7 xiaozhi-server

```bash
cd main/xiaozhi-server && \
../manager-api-fastapi/.venv/bin/python --version && \
PYTHONPYCACHEPREFIX=/tmp/xiaozhi-server-pycache \
  ../manager-api-fastapi/.venv/bin/python -m compileall -q . && \
rg --files -g '*test*.py' -g '!performance_tester/**'
```

结果：Python 3.10.20，compileall exit 0。排除性能测试目录后没有自动单测文件，因此没有虚构
pytest 通过数量；`xiaozhi-server` 的 8 个 manager-api 调用点由 consumer manifest 和 FastAPI
兼容测试验证为可解析。

首次误用不存在的 `../../.runtime/python/bin/python3.10`，结果为 exit 127；改用上面实际存在的
FastAPI Python 3.10.20 后通过。

## 4. 两层全路由差分与深度差分覆盖

### 4.1 154 条未认证/非法安全请求面差分

`tests/compatibility/route_surface_runner.py` 从 Java route manifest 逐条构造不发生成功写入的请求：
133 条 DB Token 路由省略 Token，14 条匿名路由发送安全非法输入，7 条内部路由省略
server-secret。Java 与 FastAPI 精确比较 HTTP status、解析后的 body 和 Content-Type；最终
154 passed、0 failed、0 skipped。它证明每条 Java 路由至少有一个请求路径兼容，不代表每条
路由的成功、全部错误与数据库副作用均已逐项对照。

### 4.2 154 条已认证安全业务/校验差分

`tests/compatibility/authenticated_route_runner.py` 使用与 Java 基线语义一致的 DB Token、
server-secret 或匿名认证方式，对同一份 154 路由清单逐条发送安全业务/校验请求。runner 对
动态管理员密码和 OTA 下载 UUID 先独立验证格式再做最小归一化，并同步会影响响应的固定审计
时间；最终 154 passed、0 failed、0 skipped。为不污染 fixture 或产生不可逆副作用，该 runner
有意选择资源不存在、单一约束失败、幂等空操作等不会成功写入的路径。因此这里的“已认证”
证明请求已经越过认证层并进入业务/校验逻辑，不表示每条写接口都完成了一次成功写入。

### 4.3 49 项深度结果分布

| 类别 | 通过 | 失败 |
|---|---:|---:|
| configuration | 1 | 0 |
| authentication-i18n | 7 | 0 |
| authentication | 1 | 0 |
| authorization | 1 | 0 |
| serialization | 2 | 0 |
| agent | 1 | 0 |
| device | 1 | 0 |
| model | 1 | 0 |
| correct-word | 1 | 0 |
| binary-download | 6 | 0 |
| validation | 5 | 0 |
| server-secret | 3 | 0 |
| ota | 1 | 0 |
| ota-validation | 2 | 0 |
| ota-signing | 2 | 0 |
| activation | 3 | 0 |
| external-mock | 2 | 0 |
| crud | 3 | 0 |
| database-side-effect | 4 | 0 |
| upload | 1 | 0 |
| upload-validation | 1 | 0 |
| **合计** | **49** | **0** |

直接覆盖内容包括：

- 默认语言、`zh-CN`、`zh-TW`、`en-US`、`de-DE`、`vi-VN`、`pt-BR` 七种
  `Accept-Language` 情形；
- 未登录、DB Token 过期、普通用户访问管理员接口；
- Long ID 字符串、日期、Asia/Shanghai/UTC 兼容、null、别名和分页；
- 缺字段、数字格式、最小/最大边界和 Java UTF-16 长度语义；
- server-secret 缺失、错误和正确三条路径；
- OTA health、缺失/非法 `Device-Id`、激活、WS/MQTT credential；
- HMAC-SHA256、URL-safe Base64、MQTT Base64 密码的独立密码学验证；
- 纠错词创建、更新、下载、删除及数据库副作用；
- OTA multipart 上传、扩展名错误、元数据副作用、三次下载与第四次 404；
- 二进制 MIME、`Content-Disposition`、`Content-Length` 和字节摘要；
- MQTT mock 的请求 body 和按日期生成的 Authorization。

### 4.4 有意的动态值处理

- OTA timestamp、WebSocket token 和生成 UUID 先做最小范围归一化，再分别验证格式与 HMAC；
  不是把动态字段全部忽略。
- Hibernate Validator 使用无序 `ConstraintViolation Set`。模型 provider 空 body 用例要求
  Java/FastAPI 均返回 HTTP 200、错误码 10034，消息必须属于 Java DTO 声明的五个精确约束，
  不强行固定 Java 本身不稳定的首条消息。
- 报告落盘前递归脱敏 `private_key`、server secret、MQTT signature key、Token、password 和
  Authorization；比较与密码学验证仍使用未脱敏的内存值。

### 4.5 覆盖边界

Java 清单共有 154 条路由，FastAPI 结构注册为 154/154；另有 3 条消费者兼容路由。全部 154
条均有一次未认证/非法差分和一次已认证安全业务/校验差分；49 个深度 checks 直接命中
21/154 条 Java 路由，并对代表性成功、主要错误和数据库副作用做更完整的生命周期验证。
其余路由虽有两层逐路由差分及相关领域 service/repository/protocol 测试，仍不能宣称其全部
成功写入和错误路径均已逐项深度差分。逐行状态见
`docs/manager-api-fastapi-compatibility.md`。

## 5. 隔离数据库、Redis 和 job 测试

7 条集成测试均连接隔离 MySQL/Redis，而不是纯 mock：

1. MySQL 事务异常回滚；
2. `SELECT FOR UPDATE` 在并发写入下串行化；
3. Redis key TTL 到期且不删除无关 key；
4. Redis 分布式锁只允许一个并发 job 执行；
5. watchdog 在任务超过原始 lease 后续租，仍保持单实例；
6. 实际 knowledge job 函数在 Redis 锁下只执行一次；
7. Java hash 兼容写入的默认 TTL 为 86400 秒。

差分 CRUD 另检查 Java/FastAPI 各自隔离 schema 的行级副作用；没有实施双写，也没有操作开发
数据库。最终 FastAPI 与 external mock 日志没有 warning/error/traceback。两层全路由差分会
让 Java 基线按其既有全局异常处理记录 36 条预期 ERROR，严格门禁将其精确分为 8 类：缺 body
13 条、缺 `Device-Id` 5 条、对象/数组反序列化 8 条、缺 query 4 条、非 multipart 3 条、
`callerMac` 空值 1 条、空消息 1 条及 `null` 消息 1 条。未分类 Java ERROR 为 0；任一类别数量
变化或出现未分类日志都会使脚本失败。

## 6. 性能对比

参数：每个服务每场景先顺序 warmup 10 次，再以并发 6 计量 60 次；4 个场景、2 个服务共
480 次计量请求。结果来自最终 `performance-results.json`：

| 场景 | 服务 | p50 ms | p95 ms | 吞吐 req/s | 错误 |
|---|---|---:|---:|---:|---:|
| representative-read | Java | 7.662 | 16.239 | 601.128 | 0 |
| representative-read | FastAPI | 6.749 | 12.552 | 751.538 | 0 |
| representative-crud-update | Java | 9.331 | 15.302 | 543.013 | 0 |
| representative-crud-update | FastAPI | 11.252 | 20.599 | 476.870 | 0 |
| runtime-configuration | Java | 8.746 | 16.127 | 568.863 | 0 |
| runtime-configuration | FastAPI | 6.488 | 13.722 | 765.126 | 0 |
| ota-check-and-signing | Java | 11.301 | 19.854 | 454.655 | 0 |
| ota-check-and-signing | FastAPI | 16.208 | 20.344 | 354.807 | 0 |

FastAPI/Java 比率：读取 p50 `0.881`、p95 `0.773`、吞吐 `1.250`；CRUD p50 `1.206`、
p95 `1.346`、吞吐 `0.878`；配置 p50 `0.742`、p95 `0.851`、吞吐 `1.345`；OTA p50
`1.434`、p95 `1.025`、吞吐 `0.780`。因此不能笼统声称所有 FastAPI 接口都更快：本轮读取和
配置场景更快，CRUD p50/p95 分别较慢约 20.6%/34.6%，OTA p50 较慢约 43.4%、p95 接近、
吞吐低约 22.0%。

这是同机、短时、固定 fixture 的简单对比，用于发现数量级回退，不是容量、长稳、生产网络或
多 worker 极限测试。

## 7. 三端兼容验证

- `manager-web`：134 个调用点、130 条唯一结构路由；i18n、unit、snapshot 与 production build
  均通过，现有调用无需修改 URL。
- `manager-mobile`：46 个调用点、40 条唯一结构路由；type-check、lint、snapshot 与微信小程序
  build 均通过。
- `xiaozhi-server`：8 个调用点、8 条唯一结构路由；compileall 通过，consumer manifest 确认
  全部能解析到 FastAPI。该模块没有可执行的一般单测，不能把 compileall 写成运行时集成通过。

三端合计 188 个调用点、140 条唯一结构路由。此结论证明 path/method 解析闭合；全部 Java
路由另有未认证/非法和已认证安全业务/校验两层差分，参与 49 项深度差分或领域测试的调用拥有
更完整的成功、错误或副作用证据。

## 8. 迁移验证过程中发现并修正的问题

测试没有通过删除、跳过或放宽失败用例获得绿色。差分在实现过程中实际暴露并促成修复的兼容
问题包括：分页 `total` 类型、运行时配置字段查询、设备日期时区、认证与 OTA MIME、缺失
`Device-Id` envelope、provider 校验语义、非法分页消息、运行时配置 key 命名。修复后才生成
当前 49/49 深度报告。

154 路由请求面 runner 首次执行只有 149/154 通过，准确暴露 5 条“整个 JSON body 缺失”差异：
`POST /ota/`、`POST /user/login`、`POST /user/register`、
`POST /user/retrieve-password`、`POST /user/smsVerification`。Java 对整个 body 缺失返回
HTTP 200、`code=500` 的通用 envelope，FastAPI 当时返回 `code=10034`。全局校验兼容层随后
只对定位恰为 body 根节点的 missing 错误映射 `code=500`，字段级 missing 仍保持 `10034`；
新增回归用例并完整重跑后才得到 154/154。

已认证安全业务/校验 runner 首次执行为 111/154，通过实际差分先后修正了根 body 类型、必填
query/multipart 的 Java envelope、knowledge/device/agent/voice resource 的检查顺序、权限与资源
不存在语义，以及 DTO 单约束消息等差异；后续结果依次为 149/154、152/154，最终才达到
154/154。对 Hibernate Validator 无序约束的请求，runner 改用只触发一个约束的定向 payload，
没有跳过路由、忽略响应字段或放宽比较。该 runner 始终保持“已认证但不成功写入”的安全边界。

另有测试基础设施、运行时和构建问题被明确记录：

- Pydantic 2.13 与 FastAPI 0.116 的 TypeAdapter alias 路径产生
  `UnsupportedFieldAttributeWarning`；依赖锁定到 Pydantic 2.11.7/core 2.33.2 后，实际 OTA
  body alias 验证与最终日志门禁均无 warning。
- 第一版日志门禁把 Logback 初始化文本 `ERROR_FILE` 误判为运行时 ERROR，虽然 7、49、480
  阶段均绿，脚本仍按门禁返回 1。正则收紧为带完整日期的 Java 应用 ERROR 后，重新从头执行
  完整流程并获得 exit 0；没有直接忽略门禁失败。
- fixture 的 MySQL `VALUES()` upsert 产生 8.0 弃用 warning；改为 row alias 语法并重新执行后
  无该 warning。
- 已认证差分报告最初虽未含真实凭证，但 `paramCode=server.secret` / `paramValue` 结构仍写入了
  隔离 fixture 值；递归脱敏器补充键值对识别及回归测试后，再次完整执行差分。最终四份 JSON
  对 `contract-server-secret`、测试 Token 和测试数据库密码的扫描均为 0 命中。
- Python 3.10 下 fixed-delay jobs 等待超时抛出 `asyncio.TimeoutError`；原捕获路径导致 worker
  首轮后退出。worker 改为捕获该异常并增加 Python 3.10 回归测试；实际 jobs 容器随后观察到
  knowledge job 跨 30 秒重复运行，snapshot redaction 多轮执行，SIGTERM 后干净退出。
- API 镜像构建初期遇到 uv/pip registry 传输失败；Dockerfile 固定 uv 版本并增加 timeout、retry
  与缓存后完成构建。迁移镜像的 Maven Central 并发下载两次卡住，改为串行 resolver、超时与
  retry 后成功。Nginx 初版配置在镜像 build 期校验失败，改用 template + `envsubst` 并在 build
  内执行 `nginx -t` 后通过。
- Apple Container 自定义网络没有提供本次验证所需的容器名 DNS，host publish 和单文件挂载也
  与 Docker 行为不同；验证改用容器 IP、显式 TCP bridge、named volume 和运行时 upstream 模板。它们
  是测试 runtime 限制，不被记作应用通过或失败，也没有据此声称 Docker Compose 已实际启动。

## 9. 外部服务与真实联调状态

所有自动化外部调用只访问本地确定性 mock/fixture，不访问真实付费服务。

| 外部能力 | 自动化证据 | 真实联调状态 |
|---|---|---|
| RAGFlow dataset/document/chunk/retrieval/upload | 请求 JSON/query/header、30 秒 timeout、强 DTO、Long/null、错误映射与补偿路径测试 | 无真实 RAGFlow 凭证/实例，未联调 |
| 阿里云短信 | 配置、错误 envelope 与业务路径测试 | 无真实 AccessKey，不发送短信，未联调 |
| 火山语音克隆/音频 | multipart/JSON、状态及错误映射 mock | 无真实付费凭证，未联调 |
| 声纹 HTTP | Java multipart 形状与错误映射 mock | 无真实声纹服务，未联调 |
| OpenAI-compatible LLM | 请求格式、thinking policy、摘要/标题相关 mock | 无真实模型 key，不访问付费模型，未联调 |
| MQTT gateway HTTP | 差分验证 body、按日期 Authorization 和 401 retry 语义 | 无真实 MQTT broker/gateway，未联调 |
| MCP/管理 WebSocket | token、URL、path/scheme/form 兼容测试 | 无真实远端 MCP/WS，未联调 |
| OTA/WS/MQTT credential | 本地 HMAC/Base64/时间戳和下载行为实测 | 无 ESP32 真机和生产 broker，不属于硬件联调 |

因此，本报告只证明 mock 下已覆盖的请求格式、超时、错误映射、重试和本地密码学行为；不能把
任何一项写成供应商或生产环境端到端通过。

## 10. 已知行为/部署差异

- Java 的 Hibernate Validator 首条约束消息顺序不稳定；FastAPI 保持相同 envelope、错误码和
  声明消息集合，而不是伪造固定顺序。
- Java 在 Spring 进程内运行定时任务；FastAPI 把 jobs 分离为独立进程，并用 Redis 锁和
  watchdog 防止多 worker 重复执行。集成测试验证单实例和续租语义，但部署拓扑有意不同。
- FastAPI 增加 3 条消费者兼容路由和 live/ready health endpoints；它们没有 Java Controller
  基线，属于明确的加法差异。
- 49 项已执行深度差分中没有观测到响应、所选 header 或数据库副作用差异；这句话只适用于
  报告中的 49 项，不外推为全部 154 条路由均完成了成功写入和全部错误路径生命周期验证。

## 11. 实际容器与 Nginx 验证

### 11.1 Runtime、镜像与 Compose 口径

本机没有可用的 Docker/Podman daemon，实际 OCI build/run 使用 Apple Container 1.0.0 的
linux/arm64 VM，并显式使用隔离 app/log/install root：

```bash
CLI=/Users/mie/.cache/xiaozhi-migration-tools/container-1.0.0-prefix/bin/container
ROOT=/Users/mie/.cache/xiaozhi-migration-tools/container-1.0.0-prefix
"$CLI" system start \
  --app-root "$ROOT/runtime-data" \
  --install-root "$ROOT" \
  --log-root "$ROOT/runtime-logs" \
  --disable-kernel-install
"$CLI" builder start
"$CLI" build --tag xiaozhi/manager-api-fastapi:0.1.0 \
  --file main/manager-api-fastapi/Dockerfile .
"$CLI" build --tag xiaozhi/manager-api-migrate:fastapi-0.1.0 \
  --file main/manager-api-fastapi/Dockerfile.migrations .
"$CLI" build --tag xiaozhi/manager-api-nginx:fastapi-0.1.0 \
  --file main/manager-api-fastapi/Dockerfile.nginx .
```

三张镜像均实际构建并运行。迁移镜像 OCI index 为
`sha256:613faace4314b03392e65b64d9b4a9ba7a694cdd751c1a45009824d55f0647f7`，其 arm64
manifest 为 `sha256:6a10850841370d033a3b521fbb1100cb64b5cc6837fac35d00c4257343c0f2f9`；
Nginx 镜像 OCI index 为
`sha256:2e6a188ad6d38b62fa4e77329a629ada00c4e773da9ded73c5f3289e40da477a`，其 arm64
manifest 为 `sha256:ff653bc2d11d4a3b1640747626055d6551fb33324500fb2e65b9333142da8526`。
API 镜像在上传目录 readiness 最后一处源码变更后重新 build；最终 OCI index 为
`sha256:04ae1a98307b7369368b9665c6caf9f0911c8b2a967f5a91f23c6dde7c7baa16`，其 arm64
manifest 为 `sha256:c3267d307c9898975372539121f118549bfe51012c6c9bfdc3e84f99f3e56214`，
config 为 `sha256:7c0b13757da041c0d118d14342e92c5310e4fb2140f029e385e97de9fe21d8cc`，
manifest size 为 84,551,252 bytes，镜像配置创建时间为 `2026-07-20T07:04:45Z`。

`docker-compose.yml` 已由 `tests/test_deployment_artifacts.py` 静态验证 migration dependency、
read-only root、tmpfs、upload volume、healthcheck、graceful timeout 与可切换 upstream；Nginx
镜像 build 内也实际执行 `nginx -t`。由于本机没有 Docker Compose runtime，本报告明确只把
Compose 记为静态通过，不声称执行过 `docker compose up`。

### 11.2 Liquibase migration

迁移镜像以 UID 10001 一次性运行，只读取原 Java resources 内的 Liquibase 历史。目标为隔离
schema `manager_container_test`；最终容器回归中再次运行并报告 101 个 changeSets 均
up-to-date。随后实查 `DATABASECHANGELOG` 为 101 条、业务及 Liquibase 表合计 30 张，
`DATABASECHANGELOGLOCK.LOCKED=0`，证明历史完整且锁已释放。没有连接、修改或清空开发数据库。

### 11.3 API、jobs、health、卷与优雅关闭

Apple Container VM 访问 host-only MySQL/Redis 时使用仓库内 TCP bridge，而不是暴露开发服务：

```bash
cd main/manager-api-fastapi
.venv/bin/python -m tests.compatibility.tcp_proxy \
  --listen-port 13317 --target-host 127.0.0.1 --target-port 13316
.venv/bin/python -m tests.compatibility.tcp_proxy \
  --listen-port 16380 --target-host 127.0.0.1 --target-port 16379
```

API 容器使用 `APP_WORKERS=2`、隔离 schema、Redis DB 4、read-only root、`/tmp` tmpfs 和
named upload volume 启动。实测结果：

- 容器内 UID 为 10001，最终层没有 `/bin/uv` 和 `/usr/bin/gcc`，应用路由数为 163；
- 日志确认 2 个 Uvicorn worker（容器内 PID 3、4）；`/xiaozhi/health/live` 为 HTTP 200；
- `Accept-Language: en-US` 的未认证业务请求保持 HTTP 200、英文 `{code:401,...}`；
  `POST /xiaozhi/user/login` 整个 JSON body 缺失保持 Java 的 HTTP 200、`code=500`；
- read-only root 生效。Apple Container 新建空 named volume 首次以其默认 root ownership 挂载，
  新增 readiness 检查准确返回 HTTP 503、`database=true`、`redis=true`、`uploads=false`，没有让
  无法上传的实例接流量；该失败没有伪装为通过。随后用一次性 root 容器仅对卷执行 `chown`
  ownership 初始化，ready 变为 HTTP 200 且 `uploads=true`，UID 10001 的 API 成功写入，重启后
  文件 SHA256 `1ad4cb4f879aa1ddf43a14e1a84cc5dbf8f65e91295165e126b8b08be3cd9a50` 保持不变；
- 发送 SIGTERM 后 worker 完成 lifespan shutdown 并以 exit 0 退出，无 traceback/error。

同一 API 镜像另以 `python -m app.jobs.worker`、read-only root 和 `/tmp` tmpfs 启动。实际等待
超过 31 秒后，knowledge fixed-delay job 执行两次且相隔 30 秒，snapshot redaction 多次执行；
这验证 Python 3.10 timeout 修复与真实调度循环。SIGTERM 后 jobs 也干净退出。API 多 worker
本身不加载 jobs，独立 worker 再由 Redis lock/watchdog 保证单实例。

上述 ownership 初始化是 Apple Container 空 named volume 的实测处理；本机没有 Docker
Compose runtime，因此 Docker Compose 的 named-volume copy-up 行为没有实际验证，不能用
Apple Container 的结果代替。

### 11.4 Nginx 切流与 Java 回滚

Nginx 镜像以 read-only root 和 `/var/cache/nginx`、`/var/run`、`/tmp` 三个 tmpfs 运行；其
entrypoint 将 `MANAGER_API_UPSTREAM` 注入模板后 `exec nginx`。Apple Container 自定义网络在
本次环境没有容器名 DNS，因此实测使用 runtime 分配的 API/Java 容器 IP，语义与生产 hostname
upstream 相同。FastAPI upstream 下实际验证：

- `/xiaozhi/health/ready` 为 HTTP 200；
- `/xiaozhi` 精确返回 308 到 `/xiaozhi/`；
- `Accept-Language: en-US` 的未认证 envelope 由 Nginx 转发后与直连 FastAPI 一致，整个 JSON
  body 缺失也保持 HTTP 200、`code=500`；
- Nginx、API 均在 SIGTERM 下以 exit 0 干净退出。

随后仅替换 `MANAGER_API_UPSTREAM` 指向保留的 Java 容器并重建 Nginx 运行实例；`/xiaozhi/ota/`
回滚探针的 response body 与直连 Java 按字节完全一致。此步骤证明回滚不需要删除 Java 服务、
改数据库或双写，只需切换 upstream。Nginx 基础镜像未声明非 root USER，因此这里不虚构其
non-root 属性；实际硬化证据是 read-only root、最小 tmpfs 和无持久写入。应用与迁移镜像则
均以 UID 10001 运行。

## 12. 证据文件

- 逐接口矩阵：`docs/manager-api-fastapi-compatibility.md`
- 迁移、切流与回滚说明：`docs/manager-api-fastapi-migration.md`
- Java 路由清单：`main/manager-api-fastapi/compatibility/java-routes.json`
- 三端调用清单：`main/manager-api-fastapi/compatibility/consumer-routes.json`
- 154 路由未认证/非法请求面机器报告：
  `main/manager-api-fastapi/compatibility/route-surface-results.json`
- 154 路由已认证安全业务/校验机器报告：
  `main/manager-api-fastapi/compatibility/authenticated-route-results.json`
- 深度差分机器报告：`main/manager-api-fastapi/compatibility/contract-results.json`
- 性能机器报告：`main/manager-api-fastapi/compatibility/performance-results.json`
- 一键隔离脚本：`main/manager-api-fastapi/scripts/run-isolated-contract-tests.sh`
- 未认证/非法请求面 runner：
  `main/manager-api-fastapi/tests/compatibility/route_surface_runner.py`
- 已认证安全业务/校验 runner：
  `main/manager-api-fastapi/tests/compatibility/authenticated_route_runner.py`
- 深度差分 runner：`main/manager-api-fastapi/tests/compatibility/differential_runner.py`
- 外部 mock：`main/manager-api-fastapi/tests/compatibility/external_mock.py`
- 集成测试：`main/manager-api-fastapi/tests/integration/test_isolated_runtime.py`
- 容器静态断言：`main/manager-api-fastapi/tests/test_deployment_artifacts.py`
- 容器网络 bridge：`main/manager-api-fastapi/tests/compatibility/tcp_proxy.py`
- API/migration/Nginx 构建定义：`main/manager-api-fastapi/Dockerfile`、
  `main/manager-api-fastapi/Dockerfile.migrations`、`main/manager-api-fastapi/Dockerfile.nginx`
- Nginx runtime 配置：`main/manager-api-fastapi/deploy/nginx.conf`、
  `main/manager-api-fastapi/deploy/nginx-entrypoint.sh`
- Java Surefire：`main/manager-api/target/surefire-reports/`

## 13. 当前结论

Java 98、FastAPI 全量 139、隔离集成 7、未认证/非法请求面 154/154、已认证安全业务/校验
154/154、深度差分 49/49、性能 480/0，以及 Web/Mobile 构建、xiaozhi-server compileall 和
实际容器/Nginx 验证均按上述命令完成；各测试集合均为 0 failed、0 errors、0 skipped。原 Java
服务和 Liquibase 历史均未删除。

本地可安全执行的兼容、集成、构建、消费者和容器验证已经通过。每条 Java 路由虽已有两次
全覆盖差分，但已认证 runner 有意不执行成功写入，所以不能将其表述为 154 条全部成功、错误
和副作用生命周期均已深度验证；真实 RAGFlow、短信、语音克隆、声纹、模型、MQTT/MCP/WS
及 ESP32 硬件因没有真实凭证或设备而未联调，也没有在本报告中描述为已通过。
