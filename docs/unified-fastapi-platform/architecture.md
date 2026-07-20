# 目标架构

## 1. 架构决策

统一平台采用“模块化单体代码库、按职责运行”的结构：

```text
Public HTTP/WSS
       |
       v
Gateway / static web
  |          |                 |
  |          |                 +--> /mcp/vision/explain
  |          +--------------------> /xiaozhi/v1/  -> realtime
  +-------------------------------> /xiaozhi/*    -> api

api ----------- application services -------- database / redis / object files
realtime ------ application services -------- provider adapters
jobs ---------- application services -------- scheduled work
```

同一发布版本提供四个角色：

| 角色 | 职责 | 扩缩容方式 |
| --- | --- | --- |
| `gateway` | manager-web、TLS、静态缓存、HTTP/WS 路由 | 无状态横向扩展 |
| `api` | 管理 REST、OTA、文件和内部服务端 API | 多 worker/多副本 |
| `realtime` | 设备 WebSocket、音频会话、Vision、Provider 和工具 | 按连接与模型容量扩展 |
| `jobs` | 定时同步、清理和异步补偿 | Redis 租约保证单任务所有权 |

开发环境可以用一个命令启动全部角色；生产环境不得要求 realtime 与 API 共享 worker。

## 2. 建议代码边界

```text
main/manager-api-fastapi/
├── app/
│   ├── api/                 # HTTP 路由和请求适配
│   ├── application/         # 用例服务；HTTP、WS、jobs 共用
│   ├── domain/              # 稳定业务对象和接口
│   ├── realtime/            # ASGI WebSocket、会话和协议
│   ├── providers/           # VAD/ASR/LLM/VLLM/TTS/Memory/Intent/Tools
│   ├── infrastructure/      # MySQL、Redis、文件、外部客户端
│   └── jobs/
├── web/                     # manager-web 构建集成或其产物约定
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── protocol/
│   └── e2e/
└── deploy/
```

迁移期间允许现有目录继续存在；目录调整必须跟随可运行的纵向切片，不做只有移动文件的超大 PR。

## 3. 关键内部接口

### 3.1 应用服务

Realtime 不再通过 HTTP 调用同一平台。以下能力通过应用服务接口复用：

- 获取全局配置和设备专属 Agent 配置。
- 设备绑定、激活、在线状态和通讯录查找。
- 聊天记录、音频、摘要、标题和工具调用上报。
- OTA、文件和参数读取。

HTTP 只是这些服务的一个适配器。服务方法不接收 FastAPI `Request`，也不返回 HTTP Response。

### 3.2 实时会话

每个连接由一个 `DeviceSession` 拥有，至少包含：

- 握手元数据与设备鉴权。
- 有界输入/输出音频队列。
- 文本协议路由。
- VAD/ASR/LLM/TTS/工具调用任务。
- 取消、超时、断线保存和资源关闭。

使用 ASGI WebSocket 抽象，不让 Provider 依赖 Starlette 或 `websockets.ServerConnection`。

### 3.3 Provider

Provider 通过能力协议注册，配置标识保持现状。同步 SDK 必须通过受限线程池或专用执行器调用，
禁止在事件循环中直接进行阻塞网络或长时间 CPU 工作。

Provider 按以下能力族迁移：

1. VAD + ASR。
2. LLM + VLLM + Memory + Intent。
3. TTS。
4. Tools + MCP + IoT + 插件。

本地 Torch/FunASR/Sherpa 等能力作为可选依赖组和镜像 profile，基础 API 镜像不强制加载模型。

## 4. 配置与控制面

- 数据库是完整模式下的配置事实来源。
- Redis 保存有版本号的缓存，并通过 Pub/Sub 广播配置失效和控制事件。
- worker 原子替换共享配置；现有会话可完成当前轮次，新会话使用新版本。
- `server.secret`、SM2 密钥和其他必需系统参数由并发安全的 bootstrap 初始化。
- 进程重启交给容器编排或服务管理器，业务代码不自行 fork、spawn 或 `os._exit()`。
- 轻量模式使用文件配置适配器，但进入相同应用服务，不复制 OTA 或会话实现。

## 5. 路由与兼容策略

| 公共入口 | 所有者 | 迁移策略 |
| --- | --- | --- |
| `/` | manager-web | 构建产物由 gateway 托管，保留 PWA scope |
| `/xiaozhi/*` | api | 保留当前调用方契约 |
| `/xiaozhi/ota/` | api | 完整模式只保留数据库驱动实现 |
| `/xiaozhi/v1/` | realtime | 保持设备协议，gateway 支持 Upgrade |
| `/mcp/vision/explain` | realtime | 独立设备鉴权域，不继承管理用户鉴权 |

迁移期可以继续监听 8000/8002/8003 作为兼容别名；最终公网地址由 gateway 统一，OTA 返回值和
系统参数必须在切换前验证。

## 6. 部署档位

### Lite

- 单 worker。
- 文件或数据库配置。
- 可将 API、realtime 和 jobs 放在同一进程用于本地体验。
- 不作为生产容量结论的依据。

### Production

- gateway、API、realtime、jobs 独立进程或容器。
- 共享 MySQL、Redis 和明确的持久化卷。
- realtime 按模型内存和连接数单独扩容。
- 发布时先摘流，等待连接排空，再终止旧实例。

## 7. 架构完成门禁

- 公开契约清单有可执行测试。
- API 与 realtime 不通过环回 HTTP 互调。
- 多 realtime worker 的配置更新能够广播到全部实例。
- realtime 停止时不产生孤儿线程、遗留任务或自行启动的新进程。
- Lite 与 Production 使用相同业务实现。
- 旧 xiaozhi-server 入口只有在新实现通过全部自动门禁后才能删除。
