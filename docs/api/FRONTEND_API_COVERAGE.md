# 前端与后端接口对照

由 `npm run api:frontend:generate` 生成，契约来源 `docs/api/openapi.json`，人工复核来源 `frontend-api-review.json`。

共 247 个 HTTP 操作；静态调用已接入 198，已有替代流程 14，系统集成 32，传输基础设施 1，动态资源 2。

静态调用仅表示找到了封装及直接导入/转导出，不代表每个接口都有独立按钮，也不证明真实环境全流程通过。动态资源单列；请求/响应 DTO 仍由领域适配器和测试校验。

## 需要补充或评估的入口

以下保持现有功能与权限，不在重构时自动新增高影响操作。

| 接口 | 状态 | 缺口及建议位置 |
| --- | --- | --- |

## 全部接口

| 接口 | 状态 | 请求位置 → 直接调用方 | 说明 |
| --- | --- | --- | --- |
| `GET /admin/ops/auth-security` | 静态调用已接入 | `src/api/admin.ts#fetchAuthSecurityOverview` → `src/pages/AdminAuthSecurityPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/auth-security/unlock` | 静态调用已接入 | `src/api/admin.ts#unlockAuthLockout` → `src/pages/AdminAuthSecurityPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /admin/ops/indexing` | 静态调用已接入 | `src/api/admin.ts#fetchOpsIndexing` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/indexing/detect-interruptions` | 静态调用已接入 | `src/api/admin.ts#detectIndexSubmissionInterruptions` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/indexing/failures/{operation_target}/retry` | 静态调用已接入 | `src/api/admin.ts#triggerTargetedIndexingRetry` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /admin/ops/indexing/health` | 静态调用已接入 | `src/api/admin.ts#fetchIndexingHealth` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /admin/ops/indexing/jobs` | 静态调用已接入 | `src/api/admin.ts#fetchIndexingJobs` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/indexing/markdown-backfill` | 静态调用已接入 | `src/api/admin.ts#backfillMarkdown` → `src/components/operations/IngestTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/indexing/reparse` | 静态调用已接入 | `src/api/admin.ts#triggerIndexingReparse` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/indexing/retry` | 静态调用已接入 | `src/api/admin.ts#triggerIndexingRetry` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/ingest/processing-timeout-recovery` | 静态调用已接入 | `src/api/admin.ts#recoverProcessingTimeouts` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/ingest/processing-timeout-recovery/{task_id}` | 已有替代流程 | 见说明 | 入库管理使用批量超时恢复接口；未单独接入这一单条接口。 |
| `GET /admin/ops/llm-usage` | 静态调用已接入 | `src/api/admin.ts#fetchLLMUsage` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /admin/ops/sessions/users/{user_id}` | 静态调用已接入 | `src/api/admin.ts#fetchUserSessions` → `src/components/operations/SessionTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/sessions/users/{user_id}/revoke` | 静态调用已接入 | `src/api/admin.ts#revokeUserSessions` → `src/components/operations/SessionTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /admin/ops/summary` | 静态调用已接入 | `src/api/admin.ts#fetchOpsSummary` → `src/components/operations/ReadTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /admin/ops/wecom-identity/reconcile` | 静态调用已接入 | `src/api/admin.ts#reconcileWecomIdentity` → `src/components/operations/SessionTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/alerts/notifications` | 静态调用已接入 | `src/api/admin.ts#fetchAlertNotifications` → `src/components/operations/ReadTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/alerts/rules` | 静态调用已接入 | `src/api/admin.ts#fetchAlertRules` → `src/pages/AdminAlertSettingsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/admin/alerts/rules/{rule_id}` | 静态调用已接入 | `src/api/admin.ts#updateAlertRule` → `src/pages/AdminAlertSettingsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/audit` | 静态调用已接入 | `src/api/admin.ts#fetchAudit` → `src/pages/AdminAuditPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/audit/trace/{trace_id}` | 静态调用已接入 | `src/api/admin.ts#fetchAuditTrace` → `src/components/operations/ReadTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/audit/{event_id}/mark-processed` | 静态调用已接入 | `src/api/admin.ts#markAuditProcessed` → `src/pages/AdminAuditPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/directory-migration` | 静态调用已接入 | `src/api/naming.ts#fetchDirectoryMigration` → `src/pages/AdminNamingRulesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/directory-migration/confirm` | 静态调用已接入 | `src/api/naming.ts#confirmDirectoryMigration` → `src/pages/AdminNamingRulesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/generation/default-model` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `GET /api/v1/admin/generation/models` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `POST /api/v1/admin/generation/models` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `PUT /api/v1/admin/generation/models/{model_ref}` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `DELETE /api/v1/admin/generation/models/{model_ref}` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `POST /api/v1/admin/generation/models/{model_ref}/test` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `GET /api/v1/admin/ingest` | 静态调用已接入 | `src/api/ingest.ts#fetchAdminIngest` → `src/pages/controllers/AdminIngest/useAdminIngest.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/model-connections` | 静态调用已接入 | `src/api/modelConnections.ts#fetchModelConnections` → `src/components/UnifiedModelConnectionsSection.tsx`、`src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/model-connections` | 静态调用已接入 | `src/api/modelConnections.ts#createModelConnection` → `src/components/UnifiedModelConnectionsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/model-connections/items/{model_ref}` | 静态调用已接入 | `src/api/modelConnections.ts#updateModelConnection` → `src/components/UnifiedModelConnectionsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/admin/model-connections/items/{model_ref}` | 静态调用已接入 | `src/api/modelConnections.ts#deleteModelConnection` → `src/components/UnifiedModelConnectionsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/model-connections/items/{model_ref}/test` | 静态调用已接入 | `src/api/modelConnections.ts#testModelConnection` → `src/components/UnifiedModelConnectionsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/model-connections/usages/current` | 静态调用已接入 | `src/api/modelConnections.ts#fetchModelUsageAssignments` → `src/components/UnifiedModelConnectionsSection.tsx`、`src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/model-connections/usages/current` | 静态调用已接入 | `src/api/modelConnections.ts#updateModelUsageAssignments` → `src/components/UnifiedModelConnectionsSection.tsx`、`src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/model-registry` | 静态调用已接入 | `src/api/modelRegistry.ts#fetchRegistry` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/model-registry/catalog` | 静态调用已接入 | `src/api/modelRegistry.ts#fetchProviderCatalog` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/model-registry/connections` | 静态调用已接入 | `src/api/modelRegistry.ts#createProviderConnection` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/model-registry/connections/{connection_id}` | 静态调用已接入 | `src/api/modelRegistry.ts#updateProviderConnection` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/model-registry/models` | 静态调用已接入 | `src/api/modelRegistry.ts#createRegisteredModel` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/model-registry/models/{model_id}` | 静态调用已接入 | `src/api/modelRegistry.ts#updateRegisteredModel` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/model-registry/models/{model_id}/sync` | 静态调用已接入 | `src/api/modelRegistry.ts#syncRegisteredModel` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/model-registry/models/{model_id}/verify` | 静态调用已接入 | `src/api/modelRegistry.ts#verifyRegisteredModel` → `src/components/ModelOnboarding.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/naming-rules` | 静态调用已接入 | `src/api/naming.ts#fetchNamingRuleCenter` → `src/pages/AdminNamingRulesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/naming-rules/draft` | 静态调用已接入 | `src/api/naming.ts#saveNamingRuleDraft` → `src/pages/AdminNamingRulesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/naming-rules/publish` | 静态调用已接入 | `src/api/naming.ts#publishNamingRuleDraft` → `src/pages/AdminNamingRulesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/operation-options/projects` | 静态调用已接入 | `src/api/admin.ts#fetchOperationProjectOptions` → `src/components/operations/AgentRegistration.tsx`、`src/components/operations/IngestTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/operation-options/users` | 静态调用已接入 | `src/api/admin.ts#fetchOperationUserOptions` → `src/components/operations/AgentRegistration.tsx`、`src/components/operations/SessionTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/people` | 静态调用已接入 | `src/api/admin.ts#fetchPeople` → `src/components/CreateProjectModal.tsx`、`src/pages/controllers/AdminPeople/useAdminPeople.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/people/{user_id}` | 静态调用已接入 | `src/api/admin.ts#fetchPerson` → `src/pages/controllers/AdminPeople/useAdminPeople.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/people/{user_id}/company-roles` | 静态调用已接入 | `src/api/admin.ts#setCompanyRole` → `src/pages/AdminPeoplePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/people/{user_id}/password` | 静态调用已接入 | `src/api/admin.ts#setUserPassword` → `src/pages/AdminPeoplePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/people/{user_id}/project-memberships` | 已有替代流程 | 见说明 | 人员接口 PersonOut 已包含 project_memberships；人员页面使用该字段，并调用成员关系写接口。 |
| `POST /api/v1/admin/people/{user_id}/project-memberships` | 静态调用已接入 | `src/api/admin.ts#upsertProjectMembership` → `src/pages/AdminPeoplePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/admin/people/{user_id}/project-memberships/{membership_id}` | 静态调用已接入 | `src/api/admin.ts#patchProjectMembership` → `src/pages/AdminPeoplePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/admin/people/{user_id}/project-memberships/{membership_id}` | 静态调用已接入 | `src/api/admin.ts#removeProjectMembership` → `src/pages/AdminPeoplePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/people/{user_id}/status` | 静态调用已接入 | `src/api/admin.ts#setUserStatus` → `src/pages/AdminPeoplePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/permissions/agent-whitelist` | 静态调用已接入 | `src/api/admin.ts#fetchAgentRegistry` → `src/pages/AdminPermissionsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/permissions/agent-whitelist` | 静态调用已接入 | `src/api/admin.ts#registerAgent` → `src/components/operations/AgentRegistration.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/admin/permissions/agent-whitelist/{rule_id}` | 静态调用已接入 | `src/api/admin.ts#setAgentRegistryEnabled` → `src/pages/AdminPermissionsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/permissions/rules` | 静态调用已接入 | `src/api/admin.ts#fetchPermissionRules` → `src/pages/AdminPermissionsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/admin/permissions/rules/{rule_id}` | 静态调用已接入 | `src/api/admin.ts#updatePermissionRule` → `src/pages/AdminPermissionsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/release-notes` | 静态调用已接入 | `src/api/releaseNotes.ts#fetchReleaseNotes` → `src/pages/AdminReleaseNotesPage.tsx`、`src/pages/ReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/release-notes` | 静态调用已接入 | `src/api/releaseNotes.ts#saveReleaseNote` → `src/pages/AdminReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/release-notes/{note_id}` | 静态调用已接入 | `src/api/releaseNotes.ts#saveReleaseNote` → `src/pages/AdminReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/release-notes/{note_id}/publish` | 静态调用已接入 | `src/api/releaseNotes.ts#publishReleaseNote` → `src/pages/AdminReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/weknora/default-models` | 静态调用已接入 | `src/api/admin.ts#fetchWeknoraDefaultModels` → `src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/weknora/default-models` | 静态调用已接入 | `src/api/admin.ts#updateWeknoraDefaultModels` → `src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/weknora/kb-configs` | 静态调用已接入 | `src/api/admin.ts#fetchWeknoraKbConfigs` → `src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/weknora/kb-configs/{mapping_id}/initialization` | 静态调用已接入 | `src/api/admin.ts#updateWeknoraKbInit` → `src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/weknora/kb-configs/{mapping_id}/migrate` | 静态调用已接入 | `src/api/admin.ts#migrateWeknoraKb` → `src/components/KbMigrateDialog.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/weknora/models` | 静态调用已接入 | `src/api/admin.ts#fetchWeknoraModels` → `src/components/WeknoraModelsSection.tsx`、`src/pages/controllers/AdminWeKnoraModels/useAdminWeKnoraModels.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/weknora/models` | 静态调用已接入 | `src/api/admin.ts#createWeknoraModel` → `src/components/WeknoraModelsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/admin/weknora/models/check` | 静态调用已接入 | `src/api/admin.ts#checkWeknoraModel` → `src/components/WeknoraModelsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/admin/weknora/models/{model_ref}` | 静态调用已接入 | `src/api/admin.ts#updateWeknoraModel` → `src/components/WeknoraModelsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/admin/weknora/models/{model_ref}` | 静态调用已接入 | `src/api/admin.ts#deleteWeknoraModel` → `src/components/WeknoraModelsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/admin/weknora/providers` | 静态调用已接入 | `src/api/admin.ts#fetchWeknoraProviders` → `src/components/WeknoraModelsSection.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/agent-calls/{call_id}` | 静态调用已接入 | `src/api/agentCalls.ts#fetchAgentCall` → `src/components/operations/ReadTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/agent-calls/{call_id}/decision-items` | 静态调用已接入 | `src/api/agentCalls.ts#fetchAgentDecisions` → `src/components/operations/ReadTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/agent-gateway/knowledge` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/directories` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/personal` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/recent` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/tags` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/{asset_id}` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/{asset_id}/content` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/knowledge/{asset_id}/summary` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/operations/ingest/{task_id}` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/ingest/{task_id}/confirm` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/ingest/{task_id}/naming-preview` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/ingest/{task_id}/prepare-confirmation` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/operations/naming-options` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/operations/reviews/{review_id}` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/reviews/{review_id}/decision` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/operations/upload-destinations` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/uploads/init` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/operations/uploads/{session_id}` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/uploads/{session_id}/batches` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/operations/uploads/{session_id}/complete` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/original-access/requests` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/projects` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/projects/{project_id}/brief` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/projects/{project_id}/knowledge` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/reviews/pending` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `GET /api/v1/agent-gateway/todos` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/agent-gateway/tools/knowledge-search` | 系统集成 | 见说明 | Agent 网关使用独立凭证和权限边界；网页使用业务 API，不为网关操作添加重复按钮。 |
| `POST /api/v1/auth/active-company-role` | 静态调用已接入 | `src/api/auth.ts#switchActiveCompanyRole` → `src/components/IdentityMenu.tsx`、`src/pages/LoginPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/csrf` | 传输基础设施 | `src/api/http.ts#fetchCsrfToken` → 模块内部 / 暂无直接引用 | http.ts 内部通过 ensureCsrfToken 调用，不需要页面按钮。 |
| `POST /api/v1/auth/login` | 静态调用已接入 | `src/api/auth.ts#login` → `src/components/IdentityMenu.tsx`、`src/pages/LoginPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/auth/logout` | 静态调用已接入 | `src/api/auth.ts#logout` → `src/components/IdentityMenu.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/mcp-oauth/grants` | 静态调用已接入 | `src/api/mcpOAuth.ts#fetchMcpOAuthGrants` → `src/components/McpOAuthGrants.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/auth/mcp-oauth/grants/{grant_id}` | 静态调用已接入 | `src/api/mcpOAuth.ts#revokeMcpOAuthGrant` → `src/components/McpOAuthGrants.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/mcp-oauth/requests/{request_id}` | 静态调用已接入 | `src/api/mcpOAuth.ts#fetchMcpConsent` → `src/pages/McpAuthorizePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/auth/mcp-oauth/requests/{request_id}` | 静态调用已接入 | `src/api/mcpOAuth.ts#decideMcpConsent` → `src/pages/McpAuthorizePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/me` | 静态调用已接入 | `src/api/auth.ts#fetchAuthMe` → `src/auth/AuthContext.tsx`、`src/components/operations/IngestTools.tsx`、`src/components/operations/SessionTools.tsx`、`src/pages/AdminPermissionsPage.tsx`、`src/pages/controllers/MyKnowledge/useMyKnowledge.tsx`、`src/pages/upload/useIngestConfirmation.ts`<br>`src/api/auth.ts#switchActiveCompanyRole` → `src/components/IdentityMenu.tsx`、`src/pages/LoginPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/wecom/callback` | 系统集成 | 见说明 | 企业微信登录跳转回调，由授权流程调用。 |
| `GET /api/v1/auth/wecom/start` | 静态调用已接入 | `src/api/admin.ts#startWecomOAuth` → `src/components/IdentityMenu.tsx`、`src/pages/LoginPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/workbuddy-connectors` | 静态调用已接入 | `src/api/workbuddy.ts#fetchWorkbuddyConnectors` → `src/components/WorkbuddyAccessCard.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/auth/workbuddy-connectors/{platform}/{architecture}/download` | 动态资源 | 见说明 | WorkbuddySetupPage 经 downloadWorkbuddyConnector 读取后端返回的 downloadUrl。 |
| `GET /api/v1/auth/workbuddy-token` | 静态调用已接入 | `src/api/workbuddy.ts#fetchWorkbuddyToken` → `src/components/WorkbuddyAccessCard.tsx`、`src/components/WorkbuddyStatusPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/auth/workbuddy-token` | 静态调用已接入 | `src/api/workbuddy.ts#revokeWorkbuddyToken` → `src/components/WorkbuddyAccessCard.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/auth/workbuddy-token/regenerate` | 静态调用已接入 | `src/api/workbuddy.ts#regenerateWorkbuddyToken` → `src/components/WorkbuddyAccessCard.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/company-governance` | 静态调用已接入 | `src/api/governance.ts#fetchGovernance` → `src/pages/CompanyGovernancePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/company-governance/batch` | 静态调用已接入 | `src/api/governance.ts#applyGovernance` → `src/pages/CompanyGovernancePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/company/knowledge-base` | 静态调用已接入 | `src/api/admin.ts#fetchCompanyKnowledgeBase` → `src/pages/AdminCompanyKbPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/company/knowledge-base` | 静态调用已接入 | `src/api/admin.ts#createCompanyKnowledgeBase` → `src/pages/AdminCompanyKbPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/company/knowledge-base` | 静态调用已接入 | `src/api/admin.ts#deleteCompanyKnowledgeBase` → `src/pages/AdminCompanyKbPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/generation/model-options` | 已有替代流程 | 见说明 | 模型配置使用 model-connections（含 usages/current）、model-options 接口；后端 model_connections 服务复用 generation_models。保留兼容 API，不重复创建一套配置页。 |
| `POST /api/v1/ingest/bulk-confirm` | 静态调用已接入 | `src/api/ingest.ts#bulkConfirmIngest` → `src/pages/upload/useUploadFlow.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/bulk-naming-preview` | 静态调用已接入 | `src/api/naming.ts#previewBatchIngestNaming` → `src/pages/upload/pendingBatchCommands.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/ingest/my-uploads` | 静态调用已接入 | `src/api/ingest.ts#fetchMyUploads` → `src/components/MyUploadsPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/ingest/pending` | 静态调用已接入 | `src/api/ingest.ts#fetchPendingIngestTasks` → `src/pages/upload/usePendingIngest.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload` | 静态调用已接入 | `src/api/ingest.ts#createIngestUpload` → `src/pages/upload/useIngestConfirmation.ts`、`src/pages/upload/useUploadIntake.ts`<br>`src/api/knowledgeVersions.ts#uploadVersion` → `src/components/KnowledgeVersionPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/ingest/upload-sessions` | 静态调用已接入 | `src/api/ingest.ts#fetchUploadSessions` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions` | 静态调用已接入 | `src/api/ingest.ts#createUploadSession` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/init` | 静态调用已接入 | `src/api/ingest.ts#initializeUploadSession` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/ingest/upload-sessions/{session_id}` | 静态调用已接入 | `src/api/ingest.ts#fetchUploadSession` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/{session_id}/batches` | 静态调用已接入 | `src/api/ingest.ts#appendUploadSessionBatch` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/{session_id}/cancel` | 静态调用已接入 | `src/api/ingest.ts#cancelUploadSession` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/{session_id}/complete` | 静态调用已接入 | `src/api/ingest.ts#completeUploadSession` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/ingest/upload-sessions/{session_id}/failed-items` | 静态调用已接入 | `src/api/ingest.ts#removeFailedUploadSessionItems` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/ingest/upload-sessions/{session_id}/items/{item_id}` | 静态调用已接入 | `src/api/ingest.ts#removeUploadSessionItem` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/bytes` | 静态调用已接入 | `src/api/ingest.ts#replaceUploadSessionItemBytes` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/retry` | 静态调用已接入 | `src/api/ingest.ts#retryUploadSessionItem` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/upload-sessions/{session_id}/transport-failure` | 静态调用已接入 | `src/api/ingest.ts#recordUploadTransportFailure` → `src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/ingest/{task_id}` | 静态调用已接入 | `src/api/ingest.ts#deletePendingTask` → `src/pages/upload/useUploadFlow.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/ingest/{task_id}/ai-result` | 静态调用已接入 | `src/api/ingest.ts#fetchIngestAiResult` → `src/pages/upload/pendingBatchCommands.ts`、`src/pages/upload/useIngestConfirmation.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/{task_id}/confirm` | 静态调用已接入 | `src/api/ingest.ts#confirmIngest` → `src/pages/upload/useIngestConfirmation.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/{task_id}/duplicate-decision` | 静态调用已接入 | `src/api/ingest.ts#decideUploadDuplicate` → `src/pages/upload/pendingBatchCommands.ts`、`src/pages/upload/useIngestConfirmation.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/{task_id}/naming-preview` | 静态调用已接入 | `src/api/naming.ts#previewIngestNaming` → `src/pages/upload/pendingBatchCommands.ts`、`src/pages/upload/useIngestConfirmation.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/{task_id}/refresh-parse` | 静态调用已接入 | `src/api/ingest.ts#refreshIngestParse` → `src/components/operations/AssetTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/ingest/{task_id}/retry` | 静态调用已接入 | `src/api/ingest.ts#retryIngestTask` → `src/pages/upload/pendingBatchCommands.ts`、`src/pages/upload/useIngestConfirmation.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/ingest/{task_id}/status` | 静态调用已接入 | `src/api/ingest.ts#fetchIngestTaskStatus` → `src/pages/upload/useIngestConfirmation.ts`、`src/pages/upload/useUploadIntake.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge` | 静态调用已接入 | `src/api/knowledge.ts#fetchKnowledgePage` → `src/pages/ProjectKnowledgePage.tsx`、`src/pages/controllers/KnowledgeList/useKnowledgeList.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge-maintenance` | 静态调用已接入 | `src/api/knowledgeTrust.ts#fetchMaintenance` → `src/pages/KnowledgeMaintenancePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/bulk-delete` | 静态调用已接入 | `src/api/knowledge.ts#bulkDeleteKnowledgeAssets` → `src/pages/ProjectKnowledgePage.tsx`、`src/pages/controllers/MyKnowledge/useMyKnowledge.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/directories` | 静态调用已接入 | `src/api/knowledge.ts#fetchKnowledgeDirectories` → `src/components/CreateKnowledgeDirectoryButton.tsx`、`src/components/KnowledgeMetadataEditor.tsx`、`src/pages/controllers/KnowledgeList/useKnowledgeList.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/directories` | 静态调用已接入 | `src/api/knowledge.ts#createKnowledgeDirectory` → `src/components/CreateKnowledgeDirectoryButton.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/ops-insights` | 静态调用已接入 | `src/api/knowledge.ts#fetchKnowledgeOpsInsights` → `src/components/operations/ReadTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/projects` | 静态调用已接入 | `src/api/knowledge.ts#fetchKnowledgeLibraryProjects` → `src/pages/controllers/KnowledgeList/useKnowledgeList.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/search` | 静态调用已接入 | `src/api/knowledge.ts#searchKnowledge` → `src/pages/controllers/KnowledgeList/useKnowledgeList.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/{asset_id}` | 静态调用已接入 | `src/api/knowledge.ts#fetchKnowledgeDetail` → `src/components/KnowledgeMetadataEditor.tsx`、`src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx`、`src/pages/controllers/KnowledgeList/useKnowledgeList.tsx`、`src/routing/SafeNavigation.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/delete` | 静态调用已接入 | `src/api/knowledge.ts#deleteKnowledgeAsset` → `src/pages/MyKnowledgePage.tsx`、`src/pages/ProjectKnowledgePage.tsx`、`src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/lifecycle/archive-confirm` | 静态调用已接入 | `src/api/knowledge.ts#lifecycleArchiveConfirm` → `src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/lifecycle/archive-request` | 静态调用已接入 | `src/api/knowledge.ts#lifecycleArchiveRequest` → `src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/{asset_id}/lifecycle/events` | 静态调用已接入 | `src/api/knowledge.ts#fetchLifecycleEvents` → `src/pages/CompanyGovernancePage.tsx`、`src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/lifecycle/reenable-confirm` | 静态调用已接入 | `src/api/knowledge.ts#confirmAssetReenable` → `src/components/operations/AssetTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/lifecycle/reenable-request` | 静态调用已接入 | `src/api/knowledge.ts#requestAssetReenable` → `src/components/operations/AssetTools.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/knowledge/{asset_id}/metadata` | 静态调用已接入 | `src/api/knowledge.ts#updateKnowledgeMetadata` → `src/components/KnowledgeMetadataEditor.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/original-access/request` | 静态调用已接入 | `src/api/knowledge.ts#requestOriginalAccess` → `src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx`、`src/pages/controllers/KnowledgeList/useKnowledgeList.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/preview` | 静态调用已接入 | `src/api/knowledge.ts#issuePreview` → `src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/retry-index` | 静态调用已接入 | `src/api/knowledge.ts#retryKnowledgeIndex` → `src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/{asset_id}/trust` | 静态调用已接入 | `src/api/knowledgeTrust.ts#fetchTrust` → `src/components/KnowledgeTrustPanel.tsx`、`src/components/KnowledgeVersionPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/trust/corrections` | 静态调用已接入 | `src/api/knowledgeTrust.ts#reportCorrection` → `src/components/KnowledgeTrustPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/trust/corrections/{correction_id}` | 静态调用已接入 | `src/api/knowledgeTrust.ts#transitionCorrection` → `src/components/KnowledgeTrustPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/knowledge/{asset_id}/trust/policy` | 静态调用已接入 | `src/api/knowledgeTrust.ts#saveTrustPolicy` → `src/components/KnowledgeTrustPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/trust/replacement` | 静态调用已接入 | `src/api/knowledgeTrust.ts#replaceTrust` → `src/components/KnowledgeTrustPanel.tsx`、`src/components/KnowledgeVersionPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/{asset_id}/trust/replacements` | 静态调用已接入 | `src/api/knowledgeTrust.ts#fetchReplacementOptions` → `src/components/KnowledgeTrustPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/knowledge/{asset_id}/trust/review` | 静态调用已接入 | `src/api/knowledgeTrust.ts#reviewTrust` → `src/components/KnowledgeTrustPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/{asset_id}/versions` | 静态调用已接入 | `src/api/knowledgeVersions.ts#fetchVersionHistory` → `src/components/KnowledgeVersionPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/knowledge/{asset_id}/versions/compare` | 静态调用已接入 | `src/api/knowledgeVersions.ts#compareVersions` → `src/components/KnowledgeVersionPanel.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/my/knowledge` | 静态调用已接入 | `src/api/personal.ts#fetchMyKnowledge` → `src/pages/controllers/MyKnowledge/useMyKnowledge.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/my/knowledge-base` | 静态调用已接入 | `src/api/personal.ts#fetchMyKnowledgeBase` → `src/pages/controllers/MyKnowledge/useMyKnowledge.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/my/knowledge-base` | 静态调用已接入 | `src/api/personal.ts#createMyKnowledgeBase` → `src/pages/controllers/MyKnowledge/useMyKnowledge.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PUT /api/v1/my/knowledge-base` | 静态调用已接入 | `src/api/personal.ts#renameMyKnowledgeBase` → `src/pages/controllers/MyKnowledge/useMyKnowledge.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/my/knowledge/bulk-submit-to-project` | 已有替代流程 | `src/api/personal.ts#bulkSubmitPersonalKnowledge` → 模块内部 / 暂无直接引用 | 后端明确返回 422 publication_naming_required，要求逐条核对项目命名与目录。个人知识已有逐条命名预览/提交入口，不添加必然失败的批量按钮。见 backend/app/api/my_knowledge.py。 |
| `PATCH /api/v1/my/knowledge/{asset_id}` | 静态调用已接入 | `src/api/personal.ts#updatePersonalKnowledge` → `src/pages/MyKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/my/knowledge/{asset_id}/confirm-asset` | 静态调用已接入 | `src/api/personal.ts#confirmPersonalAsset` → `src/pages/MyKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/my/knowledge/{asset_id}/submit-to-project` | 静态调用已接入 | `src/api/personal.ts#submitPersonalKnowledge` → `src/pages/MyKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/my/knowledge/{asset_id}/submit-to-project-preview` | 静态调用已接入 | `src/api/personal.ts#previewPersonalKnowledgePublication` → `src/pages/MyKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/my/knowledge/{asset_id}/validation-evidence` | 静态调用已接入 | `src/api/personal.ts#registerPersonalKnowledgeEvidence` → `src/pages/MyKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/naming-options` | 静态调用已接入 | `src/api/naming.ts#fetchNamingOptions` → `src/components/PublicationNamingFields.tsx`、`src/pages/upload/pendingBatchCommands.ts`、`src/pages/upload/useIngestConfirmation.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/notifications` | 静态调用已接入 | `src/api/notifications.ts#fetchNotifications` → `src/components/NotificationBell.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/notifications/read-batch` | 静态调用已接入 | `src/api/notifications.ts#markNotificationsRead` → `src/components/NotificationBell.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/notifications/unread-count` | 已有替代流程 | `src/api/notifications.ts#fetchNotificationUnreadCount` → 模块内部 / 暂无直接引用 | 通知列表响应已有 unread_count，通知中心据此显示角标。 |
| `POST /api/v1/notifications/{notification_id}/read` | 静态调用已接入 | `src/api/notifications.ts#markNotificationRead` → `src/components/NotificationBell.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/original-access/grants` | 静态调用已接入 | `src/api/knowledge.ts#fetchOriginalAccessGrants` → `src/pages/OriginalAccessGrantsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/original-access/grants/{grant_id}/revoke` | 静态调用已接入 | `src/api/knowledge.ts#revokeOriginalAccessGrant` → `src/pages/OriginalAccessGrantsPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/original-access/requests` | 静态调用已接入 | `src/api/knowledge.ts#fetchOriginalAccessRequests` → `src/pages/OriginalAccessPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/original-access/requests/bulk-action` | 静态调用已接入 | `src/api/knowledge.ts#bulkOriginalAccessAction` → `src/pages/OriginalAccessPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/original-access/requests/{request_id}/approve` | 静态调用已接入 | `src/api/knowledge.ts#approveOriginalAccess` → `src/pages/OriginalAccessPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/original-access/requests/{request_id}/reject` | 静态调用已接入 | `src/api/knowledge.ts#rejectOriginalAccess` → `src/pages/OriginalAccessPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/preview/{credential_id}` | 静态调用已接入 | `src/api/knowledge.ts#fetchPreviewEntry` → `src/pages/controllers/KnowledgeDetail/useKnowledgeDetail.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/preview/{credential_id}/file` | 动态资源 | 见说明 | OnlyOfficePreview 经 preview.ts 读取后端签发的 file_url，或由浏览器预览组件加载。 |
| `GET /api/v1/projects` | 静态调用已接入 | `src/api/project.ts#fetchProjects` → `src/pages/ProjectOverviewPage.tsx`、`src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects` | 静态调用已接入 | `src/api/project.ts#createProject` → `src/components/CreateProjectModal.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/projects/{project_id}` | 静态调用已接入 | `src/api/project.ts#deleteProject` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/candidate-members` | 静态调用已接入 | `src/api/project.ts#fetchCandidateMembers` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/deletion-readiness` | 静态调用已接入 | `src/api/project.ts#fetchProjectDeletionReadiness` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/knowledge` | 静态调用已接入 | `src/api/knowledge.ts#fetchKnowledgePage` → `src/pages/ProjectKnowledgePage.tsx`、`src/pages/controllers/KnowledgeList/useKnowledgeList.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/knowledge/assetization-preflight` | 静态调用已接入 | `src/api/review.ts#preflightAssetization` → `src/pages/ProjectKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/knowledge/assetization-submit` | 静态调用已接入 | `src/api/review.ts#submitAssetization` → `src/pages/ProjectKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/knowledge/bulk-confirm-asset` | 已有替代流程 | `src/api/review.ts#bulkRequestAssetConfirmation` → 模块内部 / 暂无直接引用 | 项目资料选择栏已有批量资产化入口：assetization-preflight → 登记缺失证据 → assetization-submit，同样创建/复用资产化审核，并返回逐项证据和资格结果。保留更完整的后端预检流程，不增加重复按钮。 |
| `POST /api/v1/projects/{project_id}/knowledge/bulk-upgrade-company` | 已有替代流程 | `src/api/review.ts#bulkRequestCompanyUpgrade` → 模块内部 / 暂无直接引用 | 后端明确返回 422 publication_naming_required，要求逐条核对公司命名与目录。项目资料已有逐条公司发布向导，不绕过现有审批。见 backend/app/api/review.py。 |
| `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/confirm-asset` | 已有替代流程 | 见说明 | 项目资料使用资产化 preflight/submit 流程，保留证据校验和结果反馈，不另增绕过预检的确认按钮。 |
| `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/evidence` | 静态调用已接入 | `src/api/review.ts#registerAssetEvidence` → `src/pages/ProjectKnowledgePage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/upgrade-company` | 静态调用已接入 | `src/api/review.ts#requestCompanyUpgrade` → `src/components/ProjectCompanyPublicationDialog.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/upgrade-company-preview` | 静态调用已接入 | `src/api/review.ts#previewCompanyUpgrade` → `src/components/ProjectCompanyPublicationDialog.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/members` | 静态调用已接入 | `src/api/project.ts#fetchProjectMembers` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/members` | 静态调用已接入 | `src/api/project.ts#addProjectMember` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/projects/{project_id}/members/{member_id}` | 静态调用已接入 | `src/api/project.ts#patchProjectMember` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `DELETE /api/v1/projects/{project_id}/members/{member_id}` | 静态调用已接入 | `src/api/project.ts#removeProjectMember` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/overview` | 静态调用已接入 | `src/api/project.ts#fetchProjectOverview` → `src/pages/ProjectOverviewPage.tsx`、`src/routing/SafeNavigation.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/projects/{project_id}/qa` | 静态调用已接入 | `src/api/project.ts#projectQa` → `src/pages/ProjectOverviewPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/qa/model-options` | 静态调用已接入 | `src/api/project.ts#fetchProjectQaModelOptions` → `src/pages/ProjectOverviewPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/projects/{project_id}/settings` | 静态调用已接入 | `src/api/project.ts#fetchProjectSettings` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `PATCH /api/v1/projects/{project_id}/settings` | 静态调用已接入 | `src/api/project.ts#updateProjectSettings` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/release-notes` | 静态调用已接入 | `src/api/releaseNotes.ts#fetchReleaseNotes` → `src/pages/AdminReleaseNotesPage.tsx`、`src/pages/ReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/release-notes/read` | 静态调用已接入 | `src/api/releaseNotes.ts#readReleaseNotes` → `src/pages/ReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/release-notes/status` | 静态调用已接入 | `src/api/releaseNotes.ts#fetchReleaseStatus` → `src/components/ReleaseNotesLink.tsx`、`src/pages/ReleaseNotesPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/reviews` | 静态调用已接入 | `src/api/review.ts#fetchReviewPage` → `src/pages/ReviewCompletedPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/reviews/bulk-action` | 静态调用已接入 | `src/api/review.ts#bulkReviewAction` → `src/pages/controllers/Review/useReview.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/reviews/bulk-evidence` | 静态调用已接入 | `src/api/review.ts#bulkRegisterReviewEvidence` → `src/pages/ReviewPage.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/reviews/{review_id}` | 静态调用已接入 | `src/api/review.ts#fetchReview` → `src/pages/controllers/Review/useReview.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/reviews/{review_id}/approve` | 静态调用已接入 | `src/api/review.ts#approveReview` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx`、`src/pages/controllers/Review/useReview.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/reviews/{review_id}/reject` | 静态调用已接入 | `src/api/review.ts#rejectReview` → `src/pages/controllers/ProjectSettings/useProjectSettings.tsx`、`src/pages/controllers/Review/useReview.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `POST /api/v1/reviews/{review_id}/withdraw` | 静态调用已接入 | `src/api/review.ts#withdrawReviewConfirmation` → `src/pages/controllers/Review/useReview.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/weknora/model-options` | 静态调用已接入 | `src/api/weknoraModels.ts#fetchModelOptions` → `src/hooks/useModelSelection.ts` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /api/v1/workbench/overview` | 静态调用已接入 | `src/api/workbench.ts#fetchWorkbenchOverview` → `src/workbench/WorkbenchContext.tsx` | 已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。 |
| `GET /health` | 系统集成 | 见说明 | 健康与发布检查供运维和部署使用，不属于业务按钮。 |
| `GET /health/config` | 系统集成 | 见说明 | 健康与发布检查供运维和部署使用，不属于业务按钮。 |
| `GET /health/ready` | 系统集成 | 见说明 | 健康与发布检查供运维和部署使用，不属于业务按钮。 |
| `GET /health/release` | 系统集成 | 见说明 | 健康与发布检查供运维和部署使用，不属于业务按钮。 |
