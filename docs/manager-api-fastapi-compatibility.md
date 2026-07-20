# manager-api FastAPI 兼容性矩阵

> 生成依据：`main/manager-api-fastapi/compatibility/java-routes.json`、
> `main/manager-api-fastapi/compatibility/consumer-routes.json`、`route-surface-results.json`、
> `authenticated-route-results.json`、`contract-results.json` 和当前 Java 源码。接口路径均省略
> 共同前缀 `/xiaozhi`。

## 结论与状态口径

Java 基线共有 **154** 条 Spring MVC 路由；FastAPI 已注册 **154/154（100%）**，并由
`tests/test_java_route_manifest.py` 对源码清单 freshness、数量和 method/path 注册闭合进行检查。
此外实现 3 条仅由仓库消费者使用、Java Controller 中不存在的兼容路由，因此这 3 条不计入
154 条 Java 覆盖率。三端 188 个调用点均能解析到 FastAPI 路由。

矩阵状态必须按下列含义阅读：

- `结构✓`：method/path 已注册且清单闭合；它不等于业务行为逐接口实测。
- `请求面差分✓1`：本行已向隔离 Java/FastAPI 各发送一次缺少鉴权或安全非法输入，精确比较
  HTTP status、body 与 Content-Type；最终为 **154/154 通过、0 失败、0 跳过**，且不发送成功写请求。
- `认证业务面差分✓1`：本行已使用有效 DB Token、server-secret 或匿名身份，再向隔离
  Java/FastAPI 各发送一次安全业务/校验请求，精确比较 HTTP status、body 与 Content-Type；
  最终为 **154/154 通过、0 失败、0 跳过**，且不主动发送成功写请求。该状态不等于每条路由的
  完整成功生命周期均已差分，完整副作用证据仍以 `差分✓N` 为准。
- `领域✓(x，域级)`：该领域有 service/repository/协议自动测试，但不保证本行每条成功与错误路径
  都被直接请求。`领域—` 表示除结构测试外没有可归属的域级直接测试证据。
- `差分✓N`：本行除安全请求面外，还参与了成功、主要错误、协议或数据库副作用的深度对照；
  括号说明覆盖面。深度结果为 **49/49 checks 通过、0 失败、0 跳过**，覆盖 **21/154** 条路由。
  `差分间接✓` 表示 J125 作为下载链路的 URL 生成步骤被间接覆盖；`差分—` 表示没有深度对照，
  不能把 154/154 请求面差分误读成 154 条全部成功路径与副作用都已逐接口对照。
- 所有 `Result<T>` 均表示 `{code,msg,data}` envelope；原 Java 为 HTTP 200 的认证、权限、业务和
  参数错误由全局兼容层维持 HTTP 200。二进制/OTA 裸响应在“响应类型”列单独标明。

## 三端消费者闭合

| 消费者 | 调用点 | 唯一结构路由 | 方法分布 |
|---|---:|---:|---|
| `manager-web` | 134 | 130 | DELETE 12、GET 59、POST 40、PUT 23 |
| `manager-mobile` | 46 | 40 | DELETE 3、GET 26、POST 12、PUT 5 |
| `xiaozhi-server` | 8 | 8 | GET 2、POST 6 |
| **合计** | **188** | **140** | — |

### 3 条消费者孤儿兼容路由

| Method/path | 来源 | FastAPI 语义 | 鉴权 | 状态 |
|---|---|---|---|---|
| `GET /api/ping` | manager-mobile 环境设置探活 | `{code:0,msg:"success",data:"pong"}` | 匿名 | 实现✓；consumer resolve✓ |
| `PUT /user/configDevice/{device_id}` | manager-web 遗留设备配置调用 | 按现有设备更新契约处理 body | DB Token | 实现✓；consumer resolve✓ |
| `GET /device/address-book/lookup` | xiaozhi-server 管理客户端 | `callerMac/nickname/answer` 地址簿查询/呼叫兼容别名 | server-secret | 实现✓；consumer resolve✓；device 域测试✓ |

`GET /admin/dict/data/type/FIRMWARE_TYPE` 是动态 Java 路由
`GET /admin/dict/data/type/{dictType}` 的一个字面调用，不是第四条孤儿路由。

## Java 基线静态盘点

- Controller：24 个、154 条映射。按 Controller 的路由数为：`AdminController`(5)、`AgentChatHistoryController`(4)、`AgentController`(21)、`AgentMcpAccessPointController`(2)、`AgentSnapshotController`(4)、`AgentTemplateController`(6)、`AgentVoicePrintController`(4)、`ConfigController`(3)、`CorrectWordController`(7)、`DeviceController`(13)、`KnowledgeBaseController`(7)、`KnowledgeFilesController`(8)、`LoginController`(8)、`ModelController`(11)、`ModelProviderController`(5)、`OTAController`(3)、`OTAMagController`(9)、`ServerSideManageController`(2)、`SysDictDataController`(6)、`SysDictTypeController`(5)、`SysParamsController`(5)、`TimbreController`(4)、`VoiceCloneController`(6)、`VoiceResourceController`(6)。
- 数据分层：`entity/` 29 个 Java 文件（28 个 `*Entity.java` 加 `BaseEntity`）、`dto/` 58 个、
  `vo/` 14 个、`dao/` 29 个、`service/` 树 78 个文件（其中
  `service/impl/` 38 个）。FastAPI 对应落在 `schemas/`、`repositories/`、
  `services/`、`routers/`、`integrations/` 与 `jobs/`，没有把跨表事务放进路由。
- MyBatis XML：20 个，分别是 `mapper/agent/AgentCorrectWordMappingDao.xml`、`mapper/agent/AgentDao.xml`、`mapper/agent/AgentPluginMappingMapper.xml`、`mapper/agent/AgentSnapshotDao.xml`、`mapper/agent/AgentTagDao.xml`、`mapper/agent/AgentTagRelationDao.xml`、`mapper/agent/AgentTemplateMapper.xml`、`mapper/agent/AiAgentChatHistoryDao.xml`、`mapper/correctword/CorrectWordItemDao.xml`、`mapper/device/DeviceAddressBookDao.xml`、`mapper/device/DeviceDao.xml`、`mapper/knowledge/KnowledgeBaseDao.xml`、`mapper/model/ModelConfigDao.xml`、`mapper/model/ModelProviderDao.xml`、`mapper/security/SysUserTokenDao.xml`、`mapper/sys/SysDictDataDao.xml`、`mapper/sys/SysDictTypeDao.xml`、`mapper/sys/SysParamsDao.xml`、`mapper/sys/SysUserDao.xml`、`mapper/voiceclone/VoiceCloneDao.xml`。
- Liquibase：`db.changelog-master.yaml` 含 101 个 `changeSet` 引用，目录中恰有
  101 个 SQL；Python 部署继续执行这 101 个原始 SQL，不改写历史。
- 定时工作：`DocumentStatusSyncTask` 每次完成后延迟 30 秒，扫描 RAGFlow RUNNING 文档并
  回写 SUCCESS/FAIL/CANCEL 与统计；当前 Java 源码另有 `AgentSnapshotRedactionRunner`，启动时
  执行一次并在滚动部署期每 15 秒补偿脱敏旧快照。FastAPI 将工作移到独立 jobs 进程，并以
  Redis 分布式锁/watchdog 防止多 worker 重复执行。
- 外部集成：RAGFlow dataset/document/chunk/retrieval/upload；阿里云短信；火山语音克隆训练与
  音频；声纹 HTTP；OpenAI-compatible LLM 摘要/标题；MQTT gateway HTTP；MCP/管理动作
  WebSocket；OTA/WS/MQTT 的 HMAC、Base64、时间戳与下载文件存储。自动测试只访问可重复 mock，
  未使用真实付费凭证。

## 154 条 Java→FastAPI 逐接口矩阵

副作用缩写：`DB-R/W`=数据库读/写，`Redis-R/W/DEL`=缓存读/写/失效，`文件-R/W`=文件
读取/写入；外部调用均在 service/integration 层。权限为空时表示只需对应鉴权身份。

| # | Method/path | Java Controller.handler | 请求面 | 响应类型 | 鉴权 / 权限 | DB/Redis/文件/外部副作用 | 实现与测试状态 |
|---:|---|---|---|---|---|---|---|
| J001 | `GET /admin/device/all` | `AdminController.pageDevice` | Query:params:Map<String, Object> | envelope <PageData<UserShowDeviceListVO>> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J002 | `POST /admin/dict/data/delete` | `SysDictDataController.delete` | Body:Long[] | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J003 | `GET /admin/dict/data/page` | `SysDictDataController.page` | Query:params:Map<String, Object> | envelope <PageData<SysDictDataVO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J004 | `POST /admin/dict/data/save` | `SysDictDataController.save` | Body:SysDictDataDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J005 | `GET /admin/dict/data/type/{dictType}` | `SysDictDataController.getDictDataByType` | Path:dictType | envelope <List<SysDictDataItem>> | DB Token / `sys:role:normal` | DB-R; Redis-R/W(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J006 | `PUT /admin/dict/data/update` | `SysDictDataController.update` | Body:SysDictDataDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J007 | `GET /admin/dict/data/{id}` | `SysDictDataController.get` | Path:id | envelope <SysDictDataVO> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J008 | `POST /admin/dict/type/delete` | `SysDictTypeController.delete` | Body:Long[] | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J009 | `GET /admin/dict/type/page` | `SysDictTypeController.page` | Query:params:Map<String, Object> | envelope <PageData<SysDictTypeVO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J010 | `POST /admin/dict/type/save` | `SysDictTypeController.save` | Body:SysDictTypeDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J011 | `PUT /admin/dict/type/update` | `SysDictTypeController.update` | Body:SysDictTypeDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J012 | `GET /admin/dict/type/{id}` | `SysDictTypeController.get` | Path:id | envelope <SysDictTypeVO> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(dict cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J013 | `POST /admin/params` | `SysParamsController.save` | Body:SysParamsDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-W/DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J014 | `PUT /admin/params` | `SysParamsController.update` | Body:SysParamsDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-W; 外部-配置端点探测(按 paramCode) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J015 | `POST /admin/params/delete` | `SysParamsController.delete` | Body:String[] | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-W/DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J016 | `GET /admin/params/page` | `SysParamsController.page` | Query:params:Map<String, Object> | envelope <PageData<SysParamsDTO>> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J017 | `GET /admin/params/{id}` | `SysParamsController.get` | Path:id | envelope <SysParamsDTO> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J018 | `POST /admin/server/emit-action` | `ServerSideManageController.emitServerAction` | Body:EmitSeverActionDTO | envelope <Boolean> | DB Token / `sys:role:superAdmin` | DB/Redis-R(secret/WS); Redis-W(one-shot); 外部-WebSocket | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J019 | `GET /admin/server/server-list` | `ServerSideManageController.getWsServerList` | — | envelope <List<String>> | DB Token / `sys:role:superAdmin` | DB/Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J020 | `GET /admin/users` | `AdminController.pageUser` | Query:params:Map<String, Object> | envelope <PageData<AdminPageUserVO>> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分✓3（权限/序列化/非法分页） |
| J021 | `PUT /admin/users/changeStatus/{status}` | `AdminController.changeStatus` | Path:status; Body:String[] | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W(user/password/status/token) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J022 | `DELETE /admin/users/{id}` | `AdminController.delete` | Path:id | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W(用户/token/device/agent 级联) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J023 | `PUT /admin/users/{id}` | `AdminController.update` | Path:id | envelope <String> | DB Token / `sys:role:superAdmin` | DB-W(user/password/status/token) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(sys，域级)；差分— |
| J024 | `POST /agent` | `AgentController.save` | Body:AgentCreateDTO | envelope <String> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J025 | `GET /agent/all` | `AgentController.adminAgentList` | Query:params:Map<String, Object> | envelope <PageData<AgentEntity>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J026 | `POST /agent/audio/{audioId}` | `AgentController.getAudioId` | Path:audioId | envelope <String> | DB Token / `sys:role:normal` | DB-R(audio); Redis-W(one-shot URL) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J027 | `GET /agent/chat-history/download/{uuid}/current` | `AgentChatHistoryController.downloadCurrentSession` | Path:uuid | 流式/二进制 + 原下载 headers | 匿名 / — | DB/Redis-R(one-shot); 文件-R/流式 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J028 | `GET /agent/chat-history/download/{uuid}/previous` | `AgentChatHistoryController.downloadCurrentSessionWithPrevious` | Path:uuid | 流式/二进制 + 原下载 headers | 匿名 / — | DB/Redis-R(one-shot); 文件-R/流式 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J029 | `POST /agent/chat-history/getDownloadUrl/{agentId}/{sessionId}` | `AgentChatHistoryController.getDownloadUrl` | Path:agentId,sessionId | envelope <String> | DB Token / — | DB-R(chat/session); Redis-W(download token TTL) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J030 | `POST /agent/chat-history/report` | `AgentChatHistoryController.uploadFile` | Body:AgentChatHistoryReportDTO | envelope <Boolean> | server-secret / — | DB-W(chat/session); server-secret | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J031 | `POST /agent/chat-summary/{sessionId}/save` | `AgentController.generateAndSaveChatSummary` | Path:sessionId | envelope <Void> | server-secret / — | DB-R/W(chat); 外部-OpenAI-compatible LLM | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J032 | `POST /agent/chat-title/{sessionId}/generate` | `AgentController.generateAndSaveChatTitle` | Path:sessionId | envelope <Void> | server-secret / — | DB-R/W(chat); 外部-OpenAI-compatible LLM | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J033 | `GET /agent/list` | `AgentController.getUserAgents` | Query:keyword:String,searchType:String | envelope <List<AgentDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分✓1 |
| J034 | `GET /agent/mcp/address/{agentId}` | `AgentMcpAccessPointController.getAgentMcpAccessAddress` | Path:agentId | envelope <String> | DB Token / `sys:role:normal` | DB/Redis-R; AES token 生成 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J035 | `GET /agent/mcp/tools/{agentId}` | `AgentMcpAccessPointController.getAgentMcpToolsList` | Path:agentId | envelope <List<String>> | DB Token / `sys:role:normal` | DB/Redis-R; 外部-WebSocket MCP | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J036 | `GET /agent/play/{uuid}` | `AgentController.playAudio` | Path:uuid | 流式/二进制 + 原下载 headers | 匿名 / — | DB/Redis-R(one-shot); 文件-R/流式 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J037 | `PUT /agent/saveMemory/{macAddress}` | `AgentController.updateByDeviceId` | Path:macAddress; Body:AgentMemoryDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J038 | `POST /agent/tag` | `AgentController.createTag` | Body:Map<String, String> | envelope <AgentTagEntity> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J039 | `GET /agent/tag/list` | `AgentController.getAllTags` | — | envelope <List<AgentTagDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J040 | `DELETE /agent/tag/{id}` | `AgentController.deleteTag` | Path:id | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J041 | `GET /agent/template` | `AgentController.templateList` | — | envelope <List<AgentTemplateEntity>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J042 | `POST /agent/template` | `AgentTemplateController.createAgentTemplate` | Body:AgentTemplateEntity | envelope <AgentTemplateEntity> | DB Token / `sys:role:superAdmin` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J043 | `PUT /agent/template` | `AgentTemplateController.updateAgentTemplate` | Body:AgentTemplateEntity | envelope <AgentTemplateEntity> | DB Token / `sys:role:superAdmin` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J044 | `POST /agent/template/batch-remove` | `AgentTemplateController.batchRemoveAgentTemplates` | Body:List<String> | envelope <String> | DB Token / `sys:role:superAdmin` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J045 | `GET /agent/template/page` | `AgentTemplateController.getAgentTemplatesPage` | Query:params:Map<String, Object> | envelope <PageData<AgentTemplateVO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J046 | `DELETE /agent/template/{id}` | `AgentTemplateController.deleteAgentTemplate` | Path:id | envelope <String> | DB Token / `sys:role:superAdmin` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J047 | `GET /agent/template/{id}` | `AgentTemplateController.getAgentTemplateById` | Path:id | envelope <AgentTemplateVO> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J048 | `POST /agent/voice-print` | `AgentVoicePrintController.save` | Body:AgentVoicePrintSaveDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W; 外部-voiceprint HTTP | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J049 | `PUT /agent/voice-print` | `AgentVoicePrintController.update` | Body:AgentVoicePrintUpdateDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W; 外部-voiceprint HTTP | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J050 | `GET /agent/voice-print/list/{id}` | `AgentVoicePrintController.list` | Path:id | envelope <List<AgentVoicePrintVO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J051 | `DELETE /agent/voice-print/{id}` | `AgentVoicePrintController.delete` | Path:id | envelope <Void> | DB Token / `sys:role:normal` | DB-W; 外部-voiceprint HTTP | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J052 | `GET /agent/{agentId}/snapshots` | `AgentSnapshotController.page` | Path:agentId; Query:params:AgentSnapshotPageDTO | envelope <PageData<AgentSnapshotVO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J053 | `DELETE /agent/{agentId}/snapshots/{snapshotId}` | `AgentSnapshotController.deleteSnapshot` | Path:agentId,snapshotId | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J054 | `GET /agent/{agentId}/snapshots/{snapshotId}` | `AgentSnapshotController.getSnapshot` | Path:agentId,snapshotId | envelope <AgentSnapshotVO> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J055 | `POST /agent/{agentId}/snapshots/{snapshotId}/restore` | `AgentSnapshotController.restore` | Path:agentId,snapshotId; Body:AgentSnapshotRestoreDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J056 | `DELETE /agent/{id}` | `AgentController.delete` | Path:id | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J057 | `GET /agent/{id}` | `AgentController.getAgentById` | Path:id | envelope <AgentInfoVO> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J058 | `PUT /agent/{id}` | `AgentController.update` | Path:id; Body:AgentUpdateDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J059 | `GET /agent/{id}/chat-history/audio` | `AgentController.getContentByAudioId` | Path:id | envelope <String> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J060 | `GET /agent/{id}/chat-history/user` | `AgentController.getRecentlyFiftyByAgentId` | Path:id | envelope <List<AgentChatHistoryUserVO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J061 | `GET /agent/{id}/chat-history/{sessionId}` | `AgentController.getAgentChatHistory` | Path:id,sessionId | envelope <List<AgentChatHistoryDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J062 | `GET /agent/{id}/sessions` | `AgentController.getAgentSessions` | Path:id; Query:params:Map<String, Object> | envelope <PageData<AgentChatSessionDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J063 | `GET /agent/{id}/tags` | `AgentController.getAgentTags` | Path:id | envelope <List<AgentTagDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J064 | `PUT /agent/{id}/tags` | `AgentController.saveAgentTags` | Path:id; Body:Map<String, Object> | envelope <Void> | DB Token / `sys:role:normal` | DB-W(含快照/映射/标签事务); Redis-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(agent，域级)；差分— |
| J065 | `POST /config/agent-models` | `ConfigController.getAgentModels` | Body:AgentModelsDTO | envelope <Object> | server-secret / — | DB-R; Redis-R/W(runtime/model/timbre cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(config，域级)；差分— |
| J066 | `POST /config/correct-words` | `ConfigController.getCorrectWords` | Body:CorrectWordsDTO | envelope <Object> | server-secret / — | DB-R; Redis-R/W(runtime/model/timbre cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(config，域级)；差分— |
| J067 | `POST /config/server-base` | `ConfigController.getConfig` | — | envelope <Object> | server-secret / — | DB-R; Redis-R/W(runtime/model/timbre cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(config，域级)；差分✓3（缺失/错误/正确 secret） |
| J068 | `POST /correct-word/file` | `CorrectWordController.createFile` | Body:CorrectWordFileCreateDTO | envelope <CorrectWordFileVO> | DB Token / `sys:role:normal` | DB-W(file/items/mapping 事务) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分✓2（响应/DB） |
| J069 | `POST /correct-word/file/batch-delete` | `CorrectWordController.batchDeleteFiles` | Body:List<String> | envelope <Void> | DB Token / `sys:role:normal` | DB-W(file/items/mapping 事务) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分— |
| J070 | `GET /correct-word/file/download/{fileId}` | `CorrectWordController.downloadFile` | Path:fileId | 流式/二进制 + 原下载 headers | DB Token / `sys:role:normal` | DB-R(content); 二进制 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分✓2（二进制/更新后下载） |
| J071 | `GET /correct-word/file/list` | `CorrectWordController.listFiles` | Query:params:Map<String, Object> | envelope <PageData<CorrectWordFileVO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分✓1 |
| J072 | `GET /correct-word/file/select` | `CorrectWordController.listAllFiles` | — | envelope <List<CorrectWordFileVO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分— |
| J073 | `DELETE /correct-word/file/{fileId}` | `CorrectWordController.deleteFile` | Path:fileId | envelope <Void> | DB Token / `sys:role:normal` | DB-W(file/items/mapping 事务) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分✓1（级联副作用） |
| J074 | `PUT /correct-word/file/{fileId}` | `CorrectWordController.updateFile` | Path:fileId; Body:CorrectWordFileCreateDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(file/items/mapping 事务) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(correctword，域级)；差分✓2（响应/DB） |
| J075 | `GET /datasets` | `KnowledgeBaseController.getPageList` | Query:name:String,page:Integer,page_size:Integer | envelope <PageData<KnowledgeBaseDTO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J076 | `POST /datasets` | `KnowledgeBaseController.save` | Body:KnowledgeBaseDTO | envelope <KnowledgeBaseDTO> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J077 | `DELETE /datasets/batch` | `KnowledgeBaseController.deleteBatch` | Query:ids:String | envelope <Void> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J078 | `GET /datasets/rag-models` | `KnowledgeBaseController.getRAGModels` | — | envelope <List<ModelConfigEntity>> | DB Token / `sys:role:normal` | DB-R(model config) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J079 | `DELETE /datasets/{dataset_id}` | `KnowledgeBaseController.delete` | Path:dataset_id | envelope <Void> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J080 | `GET /datasets/{dataset_id}` | `KnowledgeBaseController.getByDatasetId` | Path:dataset_id | envelope <KnowledgeBaseDTO> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J081 | `PUT /datasets/{dataset_id}` | `KnowledgeBaseController.update` | Path:dataset_id; Body:KnowledgeBaseDTO | envelope <KnowledgeBaseDTO> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J082 | `POST /datasets/{dataset_id}/chunks` | `KnowledgeFilesController.parseDocuments` | Path:dataset_id; Body:Map<String, List<String>> | envelope <Void> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J083 | `DELETE /datasets/{dataset_id}/documents` | `KnowledgeFilesController.delete` | Path:dataset_id; Body:DocumentDTO.BatchIdReq | envelope <Void> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J084 | `GET /datasets/{dataset_id}/documents` | `KnowledgeFilesController.getPageList` | Path:dataset_id; Query:name:String,status:String,page:Integer,page_size:Integer | envelope <PageData<KnowledgeFilesDTO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J085 | `POST /datasets/{dataset_id}/documents` | `KnowledgeFilesController.uploadDocument` | Path:dataset_id; Query:name:String,chunkMethod:String,metaFields:String,parserConfig:String; Multipart:file | envelope <KnowledgeFilesDTO> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J086 | `GET /datasets/{dataset_id}/documents/status/{status}` | `KnowledgeFilesController.getPageListByStatus` | Path:dataset_id,status; Query:page:Integer,page_size:Integer | envelope <PageData<KnowledgeFilesDTO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J087 | `DELETE /datasets/{dataset_id}/documents/{document_id}` | `KnowledgeFilesController.deleteSingle` | Path:dataset_id,document_id | envelope <Void> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J088 | `GET /datasets/{dataset_id}/documents/{document_id}/chunks` | `KnowledgeFilesController.listChunks` | Path:dataset_id,document_id; Query:page:Integer,pageSize:Integer,keywords:String,id:String | envelope <ChunkDTO.ListVO> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J089 | `POST /datasets/{dataset_id}/retrieval-test` | `KnowledgeFilesController.retrievalTest` | Path:dataset_id; Body:RetrievalDTO.TestReq | envelope <RetrievalDTO.ResultVO> | DB Token / `sys:role:normal` | DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(knowledge，域级)；差分— |
| J090 | `PUT /device/address-book/alias` | `DeviceController.updateAlias` | Body:DeviceAddressBookAliasDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J091 | `GET /device/address-book/call` | `DeviceController.callByNickname` | Query:callerMac:String,nickname:String,answer:boolean | envelope <Map<String, Object>> | server-secret / — | DB-R; 外部-MQTT gateway HTTP; server-secret | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J092 | `PUT /device/address-book/permission` | `DeviceController.updatePermission` | Body:DeviceAddressBookPermissionDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J093 | `GET /device/address-book/{macAddress}` | `DeviceController.getAddressBook` | Path:macAddress | envelope <Object> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J094 | `GET /device/bind/{agentId}` | `DeviceController.getUserDevices` | Path:agentId | envelope <List<UserShowDeviceListVO>> | DB Token / `sys:role:normal` | DB-R; Redis-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓1 |
| J095 | `POST /device/bind/{agentId}` | `DeviceController.forwardToMqttGateway` | Path:agentId; Body:String | envelope <String> | DB Token / `sys:role:normal` | DB/Redis-R; 外部-MQTT gateway HTTP + daily auth | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J096 | `POST /device/bind/{agentId}/{deviceCode}` | `DeviceController.bindDevice` | Path:agentId,deviceCode | envelope <Void> | DB Token / `sys:role:normal` | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J097 | `POST /device/manual-add` | `DeviceController.manualAddDevice` | Body:DeviceManualAddDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J098 | `POST /device/register` | `DeviceController.registerDevice` | Body:DeviceRegisterDTO | envelope <String> | DB Token / — | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J099 | `POST /device/tools/call/{deviceId}` | `DeviceController.callDeviceTool` | Path:deviceId; Body:DeviceToolsCallReqDTO | envelope <Object> | DB Token / `sys:role:normal` | DB/Redis-R; 外部-MQTT gateway HTTP + daily auth | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J100 | `POST /device/tools/list/{deviceId}` | `DeviceController.getDeviceTools` | Path:deviceId | envelope <Object> | DB Token / `sys:role:normal` | DB/Redis-R; 外部-MQTT gateway HTTP + daily auth | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓2（响应/外呼格式） |
| J101 | `POST /device/unbind` | `DeviceController.unbindDevice` | Body:DeviceUnBindDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J102 | `PUT /device/update/{id}` | `DeviceController.updateDeviceInfo` | Path:id; Body:DeviceUpdateDTO | envelope <Void> | DB Token / `sys:role:normal` | DB-W(device/bind/address-book); Redis-R/W | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓3（上下界/UTF-16 长度） |
| J103 | `PUT /models/default/{id}` | `ModelController.setDefaultModel` | Path:id | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J104 | `PUT /models/enable/{id}/{status}` | `ModelController.enableModelConfig` | Path:id,status | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J105 | `GET /models/list` | `ModelController.getModelConfigList` | Query:modelType:String,modelName:String,page:String,limit:String | envelope <PageData<ModelConfigDTO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J106 | `GET /models/llm/names` | `ModelController.getLlmModelCodeList` | Query:modelName:String | envelope <List<LlmModelBasicInfoDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J107 | `GET /models/names` | `ModelController.getModelNames` | Query:modelType:String,modelName:String | envelope <List<ModelBasicInfoDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J108 | `GET /models/provider` | `ModelProviderController.getListPage` | Query:modelProviderDTO:ModelProviderDTO,page:String,limit:String | envelope <PageData<ModelProviderDTO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分✓1 |
| J109 | `POST /models/provider` | `ModelProviderController.add` | Body:ModelProviderDTO | envelope <ModelProviderDTO> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分✓1（约束集合） |
| J110 | `PUT /models/provider` | `ModelProviderController.edit` | Body:ModelProviderDTO | envelope <ModelProviderDTO> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J111 | `POST /models/provider/delete` | `ModelProviderController.delete` | Body:List<String> | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J112 | `GET /models/provider/plugin/names` | `ModelProviderController.getPluginNameList` | — | envelope <List<ModelProviderDTO>> | DB Token / — | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J113 | `DELETE /models/{id}` | `ModelController.deleteModelConfig` | Path:id | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J114 | `GET /models/{id}` | `ModelController.getModelConfig` | Path:id | envelope <ModelConfigDTO> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J115 | `GET /models/{modelId}/voices` | `ModelController.getVoiceList` | Path:modelId; Query:voiceName:String | envelope <List<VoiceDTO>> | DB Token / `sys:role:normal` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J116 | `GET /models/{modelType}/provideTypes` | `ModelController.getModelProviderList` | Path:modelType | envelope <List<ModelProviderDTO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(model cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J117 | `POST /models/{modelType}/{provideCode}` | `ModelController.addModelConfig` | Path:modelType,provideCode; Body:ModelConfigBodyDTO | envelope <ModelConfigDTO> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J118 | `PUT /models/{modelType}/{provideCode}/{id}` | `ModelController.editModelConfig` | Path:modelType,provideCode,id; Body:ModelConfigBodyDTO | envelope <ModelConfigDTO> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(model/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(model，域级)；差分— |
| J119 | `GET /ota/` | `OTAController.getOTA` | — | 裸 text/plain | 匿名 / — | — | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓1（MIME/body） |
| J120 | `POST /ota/` | `OTAController.checkOTAVersion` | Header:Device-Id,Client-Id; Body:DeviceReportReqDTO | 裸 application/json | 匿名 / — | DB/Redis-R(设备/固件/配置); HMAC/Base64/时间戳凭证 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓4（必填/格式/凭证/密码学） |
| J121 | `POST /ota/activate` | `OTAController.activateDevice` | Header:Device-Id,Client-Id | 裸 application/json | 匿名 / — | DB-R/W(device activation); Redis-R/W(TTL) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓3 |
| J122 | `GET /otaMag` | `OTAMagController.page` | Query:params:Map<String, Object> | envelope <PageData<OtaEntity>> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J123 | `POST /otaMag` | `OTAMagController.save` | Body:OtaEntity | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W(OTA metadata) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓2（响应/DB） |
| J124 | `GET /otaMag/download/{uuid}` | `OTAMagController.downloadFirmware` | Path:uuid | 流式/二进制 + 原下载 headers | 匿名 / — | Redis-R/W(一次性/次数); 文件-R/流式 | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓4（次数限制及二进制） |
| J125 | `GET /otaMag/getDownloadUrl/{id}` | `OTAMagController.getDownloadUrl` | Path:id | envelope <String> | DB Token / `sys:role:superAdmin` | DB-R; Redis-W(download token TTL) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分间接✓(供下载链路) |
| J126 | `POST /otaMag/upload` | `OTAMagController.uploadFirmware` | Multipart:file | envelope <String> | DB Token / `sys:role:superAdmin` | 文件-W(MD5/扩展名/大小) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分✓2（上传/扩展名错误） |
| J127 | `POST /otaMag/uploadAssetsBin` | `OTAMagController.uploadAssetsBin` | Multipart:file | envelope <String> | DB Token / `sys:role:normal` | 文件-W(MD5/扩展名/大小) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J128 | `DELETE /otaMag/{id}` | `OTAMagController.delete` | Path:id | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W(OTA metadata); 文件-DEL | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J129 | `GET /otaMag/{id}` | `OTAMagController.get` | Path:id | envelope <OtaEntity> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J130 | `PUT /otaMag/{id}` | `OTAMagController.update` | Path:id; Body:OtaEntity | envelope <?> | DB Token / `sys:role:superAdmin` | DB-W(OTA metadata) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(device，域级)；差分— |
| J131 | `GET /ttsVoice` | `TimbreController.page` | Query:params:Map<String, Object> | envelope <PageData<TimbreDetailsVO>> | DB Token / `sys:role:superAdmin` | DB-R; Redis-R/W(timbre cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(timbre，域级)；差分— |
| J132 | `POST /ttsVoice` | `TimbreController.save` | Body:TimbreDataDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(timbre/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(timbre，域级)；差分— |
| J133 | `POST /ttsVoice/delete` | `TimbreController.delete` | Body:String[] | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(timbre/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(timbre，域级)；差分— |
| J134 | `PUT /ttsVoice/{id}` | `TimbreController.update` | Path:id; Body:TimbreDataDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W; Redis-DEL(timbre/config cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(timbre，域级)；差分— |
| J135 | `GET /user/captcha` | `LoginController.captcha` | Query:uuid:String | image/gif 二进制 | 匿名 / — | Redis-W(captcha TTL); GIF | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分— |
| J136 | `PUT /user/change-password` | `LoginController.changePassword` | Body:PasswordDTO | envelope <?> | DB Token / — | DB-W(user/token); Redis-R/DEL(SMS) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分— |
| J137 | `GET /user/info` | `LoginController.info` | — | envelope <UserDetail> | DB Token / — | DB-R; Redis-R/W(cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分✓9（七语言/过期 Token/Long） |
| J138 | `POST /user/login` | `LoginController.login` | Body:LoginDTO | envelope <TokenDTO> | 匿名 / — | DB-R/W(token); Redis-R/DEL(captcha) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分— |
| J139 | `GET /user/pub-config` | `LoginController.pubConfig` | — | envelope <Map<String, Object>> | 匿名 / — | DB-R; Redis-R/W(cache) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分✓1 |
| J140 | `POST /user/register` | `LoginController.register` | Body:LoginDTO | envelope <Void> | 匿名 / — | DB-W(user/token); Redis-R/DEL(SMS) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分— |
| J141 | `PUT /user/retrieve-password` | `LoginController.retrievePassword` | Body:RetrievePasswordDTO | envelope <?> | 匿名 / — | DB-W(user/token); Redis-R/DEL(SMS) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分— |
| J142 | `POST /user/smsVerification` | `LoginController.smsVerification` | Body:SmsVerificationDTO | envelope <Void> | 匿名 / — | Redis-R/W(TTL/频控); 外部-Aliyun SMS | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(security，域级)；差分— |
| J143 | `GET /voiceClone` | `VoiceCloneController.page` | Query:params:Map<String, Object> | envelope <PageData<VoiceCloneResponseDTO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J144 | `POST /voiceClone/audio/{id}` | `VoiceCloneController.getAudioId` | Path:id | envelope <String> | DB Token / `sys:role:normal` | DB-R; Redis-W(one-shot URL) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J145 | `POST /voiceClone/cloneAudio` | `VoiceCloneController.cloneAudio` | Body:Map<String, String> | envelope <String> | DB Token / `sys:role:normal` | DB-R/W(train state); 文件-W; 外部-火山语音克隆 HTTP | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J146 | `GET /voiceClone/play/{uuid}` | `VoiceCloneController.playVoice` | Path:uuid | 流式/二进制 + 原下载 headers | 匿名 / — | Redis-R/DEL(one-shot); 文件/外部音频-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J147 | `POST /voiceClone/updateName` | `VoiceCloneController.updateName` | Body:Map<String, String> | envelope <String> | DB Token / `sys:role:normal` | DB-W(train record name) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J148 | `POST /voiceClone/upload` | `VoiceCloneController.uploadVoice` | Query:id:String; Multipart:voiceFile | envelope <String> | DB Token / `sys:role:normal` | DB-R/W(train state); 文件-W; 外部-火山语音克隆 HTTP | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J149 | `GET /voiceResource` | `VoiceResourceController.page` | Query:params:Map<String, Object> | envelope <PageData<VoiceCloneResponseDTO>> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J150 | `POST /voiceResource` | `VoiceResourceController.save` | Body:VoiceCloneDTO | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W(voice resource) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J151 | `GET /voiceResource/ttsPlatforms` | `VoiceResourceController.getTtsPlatformList` | — | envelope <List<Map<String, Object>>> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J152 | `GET /voiceResource/user/{userId}` | `VoiceResourceController.getByUserId` | Path:userId | envelope <List<VoiceCloneResponseDTO>> | DB Token / `sys:role:normal` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J153 | `DELETE /voiceResource/{id}` | `VoiceResourceController.delete` | Path:id | envelope <Void> | DB Token / `sys:role:superAdmin` | DB-W(voice resource) | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |
| J154 | `GET /voiceResource/{id}` | `VoiceResourceController.get` | Path:id | envelope <VoiceCloneResponseDTO> | DB Token / `sys:role:superAdmin` | DB-R | 结构✓；请求面差分✓1；认证业务面差分✓1；领域✓(voiceclone，域级)；差分— |

## 已观测差异与未覆盖面

- 154 条安全请求面差分最终全部一致。首轮曾发现 5 个空 Body 映射差异；修复 FastAPI 对
  Spring `HttpMessageNotReadableException` 的 code-500 语义后，重新从零执行才得到 154/154。
- 154 条认证业务面差分最终全部一致；该轮使用有效鉴权与安全业务/校验输入，在不主动成功
  写入的前提下逐路由对照。证据是 `authenticated-route-results.json`，渲染器会在结果不是
  154/154、存在失败或跳过时硬失败。
- 2026-07-20 的隔离差分报告未在 49 个 checks 中观测到响应/所选 headers/数据库副作用
  不一致；证据是 `main/manager-api-fastapi/compatibility/contract-results.json`，不是人工推断。
- Hibernate Validator 的 `ConstraintViolation Set` 首条消息无稳定顺序；模型 provider 必填
  用例比较“消息属于 Java 声明约束集合”与相同错误码，而不伪造一个固定顺序。
- OTA 时间戳/token 是动态值，差分先比较归一化结构，再分别校验两端 HMAC/Base64 密码学
  有效性；这属于有意的测试归一化，不是声称字节恒等。
- 深度差分未直接命中的 133 条中，J125 是下载链路间接覆盖，另 132 条标为 `差分—`；
  它们有请求面、认证业务面与所属领域测试，但尚无逐路由成功+主要错误+副作用深度对照，不能据此宣称
  每一种业务状态均已逐接口行为等价。
- FastAPI 额外提供上述 3 条消费者兼容路由与 live/ready 健康检查；它们没有 Java
  Controller 基线，属于明确、可回退的加法差异。
- Java 把定时任务放在 Spring 进程；FastAPI 使用独立 jobs 进程和 Redis 分布式锁。这是
  部署拓扑差异，业务状态和幂等目标保持一致。
- RAGFlow、阿里云短信、火山语音克隆、真实声纹、真实 LLM、真实 MQTT/MCP/WS 均未用
  生产凭证联调；自动化只证明 mock 请求格式、超时/错误映射/重试中的已覆盖场景。

## 可复现检查

```bash
cd main/manager-api-fastapi
.venv/bin/python scripts/extract_java_routes.py --output compatibility/java-routes.json
.venv/bin/python scripts/extract_consumer_routes.py > /tmp/consumer-routes.json
.venv/bin/pytest -q tests/test_java_route_manifest.py tests/test_consumer_route_manifest.py tests/test_compatibility_document.py
```

逐接口差分的启动、隔离库、mock 与执行命令见 `docs/manager-api-fastapi-test-report.md`；
本文件只陈述已落盘的结果，不把缺少真实密钥的外部联调列为通过。
