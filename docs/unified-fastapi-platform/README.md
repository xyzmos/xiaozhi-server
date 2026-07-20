# 统一 FastAPI 平台开发计划

状态：规划基线

更新时间：2026-07-20

## 1. 项目目标

把 `manager-api-fastapi`、`manager-web` 和 `xiaozhi-server` 组织成同一套可版本化、可测试、
可部署和可回滚的平台，同时保持当前用户可见功能、设备协议和已存数据可用。

这里的“统一”指同一代码库、同一发布版本和同一公网入口，不要求所有职责运行在同一个
Uvicorn worker。生产环境保留 API、实时连接和定时任务的独立进程边界，轻量环境可以使用
单 worker 的 `all` 运行模式。

## 2. 完成定义

进入真实环境验收前，仓库必须同时满足：

1. 管理端页面及其现有操作均由统一发行物提供。
2. 管理 REST API、设备 OTA、WebSocket、Vision、MCP、IoT 和 MQTT 桥接协议均有自动化契约测试。
3. 虚拟设备可以完成连接、绑定、对话、中断、工具调用、断线和重连的端到端流程。
4. 所有 Provider 均完成接口适配和 Fake/契约验证；无需真实凭证的路径全部自动通过。
5. MySQL、Redis、文件、配置热更新、jobs、升级和回滚均经过隔离集成测试。
6. 统一 Docker/Compose 发行物可启动，健康检查、日志、指标和优雅停机可验证。
7. 所有尚未验证的风险只依赖真实设备、真实外部服务或目标生产环境，并已列入交接清单。

达到以上条件后，项目状态为 `RC / 等待真实环境验收`，不能提前表述为生产验收完成。

## 3. 范围

包含：

- `manager-api-fastapi` 已有管理 API、数据库、Redis、文件和 jobs 能力。
- `manager-web` 的构建、静态交付、PWA 和浏览器业务流程。
- `xiaozhi-server` 的设备 WebSocket、音频会话、Provider、Vision、MCP、IoT、插件和网关桥接能力。
- 本地轻量配置模式与数据库控制台模式，但共享一套实现，不保留重复路由。
- CI、镜像、部署、可观测性、迁移、回滚和真实测试交接。

不包含：

- 改变现有业务规则或重新设计管理端产品体验。
- 在没有凭证时声称云 Provider 已真实联调。
- 把外部 MQTT/UDP gateway、RAGFlow 或云模型服务复制进本仓库。
- 在没有真实 ESP32 和目标环境时批准生产上线。

## 4. 不可破坏的兼容边界

- 设备 OTA URL、请求头、响应字段及激活行为。
- `/xiaozhi/v1/` 的 WebSocket 握手、文本消息、Opus 帧和 MQTT 桥接帧。
- Device-ID、Client-ID、服务密钥和 HMAC Token 语义。
- 已有数据库数据、用户权限、智能体配置、模型标识及文件资产。
- 当前 Web、Mobile 和设备仍在使用的公开 API；内部自调用不属于兼容边界。
- 已启用 Provider 的配置字段和可观察结果。

## 5. 工作原则

1. 先记录现状，再替换实现：没有特征测试的行为不得直接重写。
2. 以可工作的纵向切片提交 PR，避免一次性迁移整个实时服务。
3. 共享代码，隔离运行职责：API、realtime、jobs 可以使用同一镜像但独立启动。
4. 新旧实现可并行对照且可回滚，删除旧入口必须是最后阶段。
5. Provider 按能力族批量适配，默认不为每个供应商启动独立 Agent。
6. 每个 PR 只有一个明确负责人和一个独立审阅角色。
7. 自动化可以判断的事项不等待人工；真实环境不可替代的事项不得用 Mock 冒充通过。

## 6. 文档导航

- [目标架构](architecture.md)
- [阶段路线图与 PR 队列](roadmap.md)
- [多岗位 Agent 协作模型](agent-operating-model.md)
- [质量门禁](quality-gates.md)
- [架构与交付决策](decisions.md)
- [风险登记册](risk-register.md)
- [真实环境测试交接](real-environment-handoff.md)

## 7. 当前基线

- FastAPI 管理 API 已形成 154 条 Java 路由兼容基线和现有测试报告，但逐路由直接深度差分
  目前只覆盖 21/154；其余成功路径和副作用证据必须在 M5 前补齐。
- manager-web 的 i18n、unit、snapshot 和生产构建已有绿色记录。
- xiaozhi-server 可通过 Python 语法编译，但缺少正式自动化单测和设备协议回归套件。
- FastAPI、部署文档和脚本已作为集成分支基线提交；后续重构只通过目标为该分支的 PR 进入。
- 真实 RAGFlow、短信、语音、MQTT/MCP 和 ESP32 尚未验收。

项目状态以 [roadmap.md](roadmap.md) 的阶段门禁为唯一进度来源。

开发期间以 `refactor/unified-fastapi-platform` 为长期集成分支。所有规划和实现 PR 均合入该分支，
不会在纯 Agent 阶段向 `main` 创建 PR。
