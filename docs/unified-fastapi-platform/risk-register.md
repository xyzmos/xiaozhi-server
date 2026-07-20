# 风险登记册

| ID | 风险 | 概率/影响 | 缓解措施 | 触发升级条件 | Owner |
| --- | --- | --- | --- | --- | --- |
| R01 | xiaozhi-server 缺少正式协议测试，重构造成隐性漂移 | 高/高 | M1 先建立黄金报文、虚拟设备和旧/新差分 | 无法从旧代码和调用方确定行为 | QA + Realtime |
| R02 | REST API worker 与实时模型共享进程导致内存和延迟失控 | 高/高 | 同代码库、独立运行角色；Lite 仅单 worker | 生产方案要求单进程多 worker | Architecture |
| R03 | `websockets`、PyYAML 及重模型依赖冲突 | 高/高 | 统一锁文件、Provider extras、镜像 profile | 必须删除现有 Provider 才能解析 | Platform + Provider |
| R04 | `server.secret`/SM2 首次初始化或轮换不一致 | 高/高 | 并发安全 bootstrap、单一事实来源、广播测试 | 任一 worker 使用不同密钥 | Backend + Security |
| R05 | 配置热更新只到达部分 realtime worker | 中/高 | Redis 版本事件、ack/指标、全 worker 集成测试 | 版本长时间不一致 | Backend + SRE |
| R06 | 线程、任务或 SDK 阻塞事件循环 | 高/高 | DeviceSession 所有权、有界执行器、soak/lag 指标 | 负载下 API/WS 延迟无界增长 | Realtime + QA |
| R07 | manager-web Service Worker 缓存旧 API/资源 | 中/中 | 保留 scope、版本化资源、升级 E2E | 新旧前端混用造成不可恢复错误 | Frontend |
| R08 | OTA 双实现或公网 URL/端口切换破坏旧固件 | 中/高 | 完整/轻量 profile、兼容别名、OTA 差分 | 需要升级固件才能连接 | Architecture + QA |
| R09 | 本地模型文件、FFmpeg、libopus 和写目录未正确打包 | 高/中 | 显式卷、非 root 权限、profile 构建测试 | 干净容器无法启动选定能力 | Platform |
| R10 | Mock 掩盖真实供应商流式和错误行为 | 高/高 | Fake 只证明契约；M8 真实矩阵单独验收 | 需要凭证才能决定公共设计 | QA + External QA |
| R11 | MQTT/UDP gateway、RAGFlow 等外部项目版本漂移 | 中/高 | 固定支持版本、录制契约、真实交接清单 | 外部接口文档与实际不一致 | Integration |
| R12 | 上游 `main` 持续变化导致长分支难以合并 | 高/中 | 小 PR、每次合并后变基、每阶段重跑调用方清单 | 冲突改变公共契约 | PM/集成 |
| R13 | PR 并行过多造成重复实现和冲突 | 中/中 | 最多三个实现工作包、文件所有权、唯一负责人 | 两个 PR 修改同一协议核心 | PM/集成 |
| R14 | 现有未跟踪 FastAPI 基线没有进入远端 | 高/高 | P00 优先提交并建立 PR | 后续 Agent 无稳定基线 | PM/集成 |

## 风险处理规则

- P0：立即停止受影响工作包，PM 和架构负责人决策。
- P1：不得合并相关 PR，必须有修复或明确的外部阻塞证据。
- P2：可以带风险进入后续阶段，但必须有 Owner、验证计划和截止阶段。
- 外部阻塞：只有满足 [真实环境测试交接](real-environment-handoff.md) 的定义才能标记，不能把内部未完成项转嫁给真实测试。

每个里程碑收口时重新评估概率、影响和 Owner；关闭风险必须附测试、PR 或决策记录链接。
