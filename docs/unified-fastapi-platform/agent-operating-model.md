# 多岗位 Agent 协作模型

## 1. 岗位与责任

| 岗位 | 主要责任 | 不负责 |
| --- | --- | --- |
| PM / 集成负责人 | 范围、优先级、依赖、PR 队列、风险、最终门禁 | 代替专项 Agent 编写所有业务实现 |
| 架构负责人 | 接口边界、ADR、跨模块依赖、并发和状态模型 | 未经测试直接大规模搬迁代码 |
| Realtime 工程 Agent | ASGI WebSocket、DeviceSession、音频队列和生命周期 | 修改管理业务规则 |
| Backend 工程 Agent | 应用服务、配置、数据库、Redis、bootstrap | 修改设备协议 |
| Provider 工程 Agent | 按能力族适配已有 Provider | 改变供应商可见配置语义 |
| Frontend/交付 Agent | manager-web 构建、静态托管和路由 | 重做页面产品设计 |
| Platform/SRE Agent | CI、镜像、Compose、健康、指标、升级回滚 | 在缺少证据时批准上线 |
| QA Agent | 特征测试、差分、虚拟设备、E2E、性能和故障注入 | 为使测试变绿而放宽契约 |
| 独立 Reviewer | 安全、兼容、并发、资源和证据审阅 | 与实现者共享同一结论来源 |

## 2. 工作包准入

分配给 Agent 前，工作包必须明确：

- 目标和不在范围内的事项。
- 允许修改的目录和禁止修改的公共接口。
- 上游依赖及其版本/提交。
- 必须新增或保持的测试。
- 完成命令和预期证据。
- 需要升级给 PM 的决策点。

工作包模板：

```text
目标：
用户可见结果：
允许修改：
禁止修改：
输入契约：
输出契约：
必须运行：
完成条件：
已知风险：
```

## 3. 资源控制

1. 默认使用一个实现 Agent；只有文件所有权互斥且确有关键路径收益时才并行。
2. 同时活动的实现 Agent 不超过三个，另保留一个集成/审阅角色。
3. 不为单个 Provider 启动一个 Agent；按能力族分组，出现特有失败时再拆分。
4. 不让两个 Agent 重复做全仓审计。审阅 Agent 只读取 PR diff、契约和相关文件。
5. 大型上下文按目录和接口裁剪；交接必须写入文档或 PR，不依赖聊天记忆。
6. 长耗时集成、容器、性能测试只在相关代码变化、里程碑收口或夜间任务运行。
7. 发现范围外缺陷时记录后移，不顺手扩张当前 PR。

## 4. 文件所有权与冲突避免

活动 PR 必须声明临时所有权：

| 范围 | 默认岗位 |
| --- | --- |
| `app/realtime/**`、协议测试 | Realtime |
| `app/application/**`、`app/domain/**` | Architecture/Backend |
| `app/providers/**` | 对应 Provider 能力族 |
| `app/api/**`、现有 routers/services | Backend |
| `main/manager-web/**`、gateway 静态配置 | Frontend/交付 |
| Docker、Compose、CI | Platform/SRE |
| `tests/e2e/**`、虚拟设备、差分工具 | QA |
| 本目录路线图、风险和交接文档 | PM/集成 |

需要跨所有权修改时，先由当前所有者提供最小接口，再继续实现；禁止在合并阶段才发现公共接口冲突。

## 5. 分支与 PR 规则

- 长期集成分支：`refactor/unified-fastapi-platform`；纯 Agent 阶段的开发 PR 均以它为目标。
- 工作分支命名：`platform/<milestone>-<short-topic>`。
- 分支名、Commit 和 PR 标题遵守仓库禁用词要求。
- Commit 使用结果导向格式，例如 `test: add device protocol characterization`。
- 一个 PR 只交付一个计划工作包或一个可独立回滚的纵向切片。
- PR 描述必须列出阶段、依赖、契约影响、验证命令、风险和回滚方法。
- 实现者不得作为唯一 Reviewer；高风险协议、鉴权、迁移和并发 PR 必须有专项审阅。
- 合并前同步最新目标分支并重新运行必需门禁。
- 不允许未解释的 skip、仅本机通过、手工修改测试数据或把 Mock 结果描述成真实联调。
- 未经项目所有者明确批准，不创建以 `main` 为目标的 PR。

可选 PR 模板位于 `.github/PULL_REQUEST_TEMPLATE/unified-platform.md`。

## 6. PR 生命周期

```text
Ready work package
  -> implementation + local tests
  -> draft PR + evidence
  -> independent review
  -> required CI gates
  -> PM dependency/risk check
  -> merge
  -> roadmap evidence link
```

发生以下任一情况必须暂停并升级：

- 需要改变设备公开协议或现有数据语义。
- 需要真实凭证、真实设备或目标环境才能判断实现方向。
- 同一测试在旧实现上也失败，且无法确定基线行为。
- 依赖冲突要求删除现有 Provider。
- PR 需要跨越两个以上尚未完成的里程碑。

## 7. Agent 交接格式

```text
完成内容：
变更文件：
契约变化：无 / 具体说明
执行过的命令与结果：
未执行项目及原因：
遗留风险：
下一工作包可依赖的接口：
建议 Reviewer 重点：
```

没有上述交接或可重复证据的工作不进入集成分支。
