# 模型接入一期：多供应商共享连接

本期在模型管理中增加“供应商连接 → 模型草稿 → 能力验证 → 用途接入”的完整流程。前后端同时实现，既有模型继续沿用原有配置；不自动导入旧密钥、不修改默认模型、不迁移知识库。

## 支持范围

| 连接模板 | 本期能力 | 协议 |
| --- | --- | --- |
| 阿里云百炼 | 对话、嵌入、重排 | OpenAI 兼容；重排使用 DashScope 原生协议 |
| DeepSeek | 对话 | OpenAI 兼容 |
| 硅基流动 | 对话、嵌入、重排 | OpenAI 兼容；通用 rerank |
| OpenAI | 对话、嵌入 | Chat Completions / Embeddings |
| Moonshot / Kimi | 对话 | OpenAI 兼容 |
| 智谱 | 对话、嵌入 | OpenAI 兼容 |
| 火山方舟 | 对话 | OpenAI 兼容，模型名称填写推理接入点或服务商允许的模型标识 |
| 自定义兼容服务 | 对话、嵌入、重排 | 分能力指定接口和受支持协议 |

模板代表协议适配范围，不保证账号授权、地域支持或某个模型具备全部能力。本期未实现 Anthropic Messages、Gemini 原生协议、Responses API、多模态、语音的新增接入适配。已有相关模型记录保留原入口。

百炼连接支持地域和业务空间 ID，分别生成对话/嵌入 Base URL 和重排完整 URL。其他供应商使用各自模板；高级配置可按能力覆盖接口。对话与嵌入拒绝把完整调用路径误当 Base URL。重排不能套用对话地址。

供应商接口参考（核对于 2026-11-05）：[百炼地域与接口](https://help.aliyun.com/zh/model-studio/regions)、[百炼重排](https://help.aliyun.com/zh/model-studio/rerank)、[DeepSeek 接入](https://api-docs.deepseek.com/quick_start/agent_integrations/)、[硅基流动重排](https://docs.siliconflow.cn/docs/api/rerank-post)、[方舟 OpenAI 兼容](https://docs.volcengine.com/docs/ark/compatible-with-openai-sdk?lang=zh)、[OpenAI Embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)。

## 使用与状态

1. 创建供应商连接，录入名称、供应商和 API Key；按需填业务空间或自定义接口。地址和密钥加密落库，读取接口不返回原值，编辑留空保留。
2. 添加模型并引用连接，选择能力和用途。嵌入模型需填写预期维度。多个模型可以共用同一连接和凭据。
3. “保存草稿”只保存配置；“验证并接入”先验证保存版本，再接入所选用途。验证使用虚构内容，实际供应商请求可能产生少量费用。
4. 对话检查有效响应；嵌入检查向量结构、数值及实际维度；重排检查索引和评分结构。账户欠费、空间拒绝访问、认证、限流、接口错误分别显示安全诊断，不返回上游原始消息。
5. 用途分为内容生成与项目问答、知识库检索与解析。知识库接入还需凭据写入回读和底座检查。完成后才进入可选列表；默认模型仍需在“模型设置”选择。
6. 修改共享连接显示受影响模型；版本变化使所有关联模型的旧验证失效。各模型重新验证并接入前，已成功接入的旧版本继续使用。同步过程可能分步写入远端，失败会标为待处理，不承诺远端原子回滚。

已接入模型的模型标识、能力、嵌入维度不能直接替换；新增模型后通过用途设置或知识库迁移切换。当前阶段提供新增、草稿编辑、验证、接入和重试；共享连接/受管模型删除与解除用途依赖尚未提供。

## 后端边界与恢复

- 新接口位于 `/api/v1/admin/model-registry`，沿用模型治理权限；审计只记录安全引用和动作。
- 迁移 `0083_model_registry` 增加连接、模型登记表及旧外部模型的配置/测试版本列。需先迁移再启动新后端。旧密钥不迁移；加密配置依赖既有加密密钥配置。
- 验证绑定模型、连接配置、凭据版本；操作租约与版本比较阻止迟到结果覆盖新配置。旧外部模型测试也采用条件更新，修改连接后旧健康状态失效。
- 创建请求携带幂等 UUID；每个用途保存独立同步状态。成功用途在重试时保留，不重复创建。
- WeKnora 创建前持久化意图，创建后立即保存远端 ID；响应丢失时通过唯一描述标记查找已创建记录。无法确认结果时返回 `creation_unconfirmed`，不盲目重新创建。管理员应核对远端标记后再处理，不能直接清除意图重复执行。
- 操作进程异常退出时，租约最多保留十分钟；恢复后仍需版本检查及创建结果核对。
- 受管运行记录的旧修改/删除 API 被拒绝，避免绕过共享配置版本。未完成接入的知识模型及未关联本地记录的登记标记不会进入用途选项。
- 探测公网接口要求 HTTPS，校验解析 IP，直连时固定连接目标，保留 TLS 主机校验，禁用环境代理和重定向，限制响应大小。私有模型服务必须由部署管理员在 `MODEL_REGISTRY_PRIVATE_HOSTS` 显式配置主机名；默认空。本地替身验收仅允许 `127.0.0.1`。
- 如部署要求经 CONNECT 网关出站，可显式设置 `MODEL_REGISTRY_PROXY_URL`（默认空），不从环境代理变量自动继承。网关模式仍先检查目标 DNS/IP，CONNECT 使用原始域名以供网关精确白名单匹配；部署网关必须独立验证解析结果并阻止私网目标。配合容器 internal 网络阻断直连，TLS 仍由客户端校验。
- 此网络校验覆盖登记验证请求；实际生成与 WeKnora 调用继续受各自运行环境网络策略约束，不能替代部署层出站隔离。

## 本轮隔离验收

日期：2026-11-05。独立工作树，空的隔离 PostgreSQL 数据库 `kap_registry_fixture`，迁移至 0083；真实 KAP 前后端配合本地供应商和 WeKnora 协议替身，全部账号、内容与密钥均为虚构。生产服务、生产配置与生产密钥未修改。

自动化覆盖多供应商模板、共享密钥与版本失效、维度/重排响应校验、部分成功重试、创建响应丢失恢复、旧结果防覆盖、权限与秘密不回传、未接入模型不可选、网络探测限制，以及前端草稿/验证/接入流程。执行命令：

```powershell
# 在 backend 目录执行，保证解析子进程可导入 app
python -m pytest tests/test_model_registry.py tests/test_model_probe_transport.py tests/test_model_connections.py tests/test_generation_models.py tests/test_weknora_model_config.py tests/test_weknora_default_models_api.py tests/test_weknora_model_selection.py tests/test_weknora_model_options_api.py
# 在仓库根目录执行
npx vitest run src/components/ModelOnboarding.test.tsx src/pages/AdminWeKnoraModelsPage.test.tsx src/components/UnifiedModelConnectionsSection.test.tsx
npm run build
npm run api:frontend:check
```

结果：后端 134 项、前端 30 项通过；生产构建、接口契约 4 项、修改文件的 lint 与格式检查通过。

浏览器已覆盖硅基流动模板下嵌入/重排共用连接、DeepSeek 模板下对话双用途接入、共享虚构凭据更新后的关联状态失效与重新接入。重新接入后模型数量不增加；新增对话模型进入默认用途选项，原默认选中值保持不变。窄屏（390×844）和桌面均使用同一实际前后端链路。

本轮是隔离协议与 UI 验收，不是各厂商真实账号逐一联网验收，也没有重新验证 PDF/OCR 或升级无关能力。已有服务器联网演练记录不等同于本期新登记模块的真实厂商验收；上线前仍需按实际启用的厂商、模型、地域和运行网络验证。

## 真实模型隔离续验命令入口

`scripts/weknora_live_rehearsal.py --build-stage <已通过离线验收的构建目录> --aliyun-workspace-id <北京业务空间ID> --fixture-rerank-use-embedding-key --kap-model-registry` 使用固定提交的源码和既有通过镜像，新建随机隔离容器与空库；该模式与三角色/上传复验互斥。

凭据只在服务器受限文件和隔离进程中使用。嵌入与重排引用同一条百炼连接，DeepSeek 使用另一条连接。先验证直接外联被阻断、非白名单域名被拒绝，再经真实 KAP HTTPS 登录和 CSRF 调用登记接口：草稿幂等、真实能力探测、1024 维向量检查、用途端验证、重复接入无重复记录、DeepSeek 业务调用、默认用途不变。不会重跑上传/OCR，也不会设为生产默认模型。

公开结果写入新阶段的 `live-report.json`；原始日志、凭据文件保持私密。只有探针、生产指纹核对和测试容器停止都成功，才写 `PASS-KAP-MODEL-REGISTRY` 和 `exit-code=0`；不会写表示文件生命周期通过的 `PASS-LIVE`。本节记录执行入口，不代表服务器真实模型验收已经通过。
