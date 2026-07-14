# Frontend Route Takeover Matrix

## Scope and evidence

This matrix is generated from the production ownership chain rooted at `src/main.tsx` and
`src/App.tsx`. Route ownership, guards, page modules, API imports, and tests were checked from
actual imports and call sites. The machine-enforced counterpart is
`src/test/frontendTakeoverGate.test.ts`.

The audit covers 18 formal routes. The wildcard `*` route is an application fallback and is
listed separately. A frontend guard improves the experience; backend authorization remains the
authority.

## Route ownership

| Route                    | Guard                | Production page                                             | API modules and key operations                                                                                    | Key user actions                                                            | States and test evidence                                                           | Decision                                          |
| ------------------------ | -------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------- |
| `/`                      | Public               | `HomeDashboardPage`                                         | `auth.fetchAuthMe`; knowledge insights/access requests; review queue; pending ingest; projects                    | Open work queues and projects                                               | Loading and empty states; route gate only, no page behavior test                   | Keep; real API closed loop                        |
| `/knowledge`             | `viewKnowledge`      | `KnowledgeListPage`                                         | `auth`; knowledge list/search/delete/insights; project create and scan owner options through `CreateProjectModal` | Filter, search, open detail, delete, create project                         | Loading/error/result states; layout/copy tests, no behavior test                   | Keep; real API closed loop                        |
| `/knowledge/:id`         | `viewKnowledge`      | `KnowledgeDetailPage`                                       | knowledge detail, lifecycle events/archive, retry/delete, access request, controlled preview                      | View metadata, preview original, request access, archive, retry, delete     | Loading/error/preview failure and timeout; 7 direct tests                          | Keep; PBC-58 owns preview behavior                |
| `/my/knowledge`          | `viewMyKnowledge`    | `MyKnowledgePage`                                           | `auth`, `personal`, model options, WorkBuddy token operations                                                     | Create/rename KB, confirm/submit asset, register evidence, manage WorkBuddy | Loading/error/empty/permission states; hook/component tests, no page behavior test | Keep; real API closed loop                        |
| `/upload`                | `viewUpload`         | `UploadPage` + `useUploadFlow`                              | `auth`, `ingest`, model options                                                                                   | Select source/file, poll extraction, correct metadata, confirm ingest       | Explicit idle/processing/confirm/error flow; hook tests cover API payloads         | Keep; real API closed loop                        |
| `/admin/ingest`          | `viewIngestAdmin`    | `AdminIngestPage`                                           | ingest list; indexing summary/jobs/retry/reparse                                                                  | Inspect ingest/indexing and trigger recovery                                | Loading/error/empty/action states; structural tests only                           | Keep; real API closed loop                        |
| `/admin/wecom-scan`      | `viewWecomScan`      | `AdminWecomScanPage` + `wecomScan/*`                        | scan configs/records, directory lookup, create/update/trigger                                                     | Configure directories and trigger scans                                     | Loading/error/empty/busy; structural/copy tests only                               | Keep; real API closed loop                        |
| `/admin/weknora-models`  | `viewModels`         | `AdminWeKnoraModelsPage` + `UnifiedModelConnectionsSection` | KB initialization; unified connections/test/update; usage assignments                                             | Manage connections, test connectivity, assign usage, update KB init         | Loading/error/empty/busy; direct page and component tests                          | Keep; real API closed loop                        |
| `/admin/audit`           | `viewAudit`          | `AdminAuditPage`                                            | audit query/filter and mark processed                                                                             | Filter logs, inspect safe metadata, mark processed                          | Loading/error/empty; structural tests only                                         | Keep; real API closed loop                        |
| `/admin/auth-security`   | `viewAuthSecurity`   | `AdminAuthSecurityPage`                                     | security overview and lockout unlock                                                                              | Inspect safe security signals and unlock                                    | Loading/error/empty/action states; route gate only                                 | Keep; real API closed loop                        |
| `/admin/alert-settings`  | `viewAlerts`         | `AdminAlertSettingsPage`                                    | alert rules/notifications and rule update                                                                         | Inspect notifications and change rules                                      | Loading/error/empty/update states; route gate only                                 | Keep; real API closed loop                        |
| `/admin/people`          | `viewPeople`         | `AdminPeoplePage`                                           | people list/detail, roles, password/status, memberships, session revoke, identity reconciliation                  | Search people and administer identity/roles                                 | Loading/error/empty/busy/permission states; copy/layout tests only                 | Keep; real API closed loop                        |
| `/admin/permissions`     | `viewPermissions`    | `AdminPermissionsPage`                                      | `auth`; permission rules and agent registry read/update                                                           | Inspect/update rules and agent enablement                                   | Loading/error/read-only states; route gate only                                    | Keep; real API closed loop                        |
| `/review`                | `viewReview`         | `ReviewPage`                                                | `auth`; review list/approve/reject                                                                                | Filter and decide review items                                              | Shared loading/error/empty/action feedback; shared hook/component tests            | Keep; real API closed loop                        |
| `/original-access`       | `viewOriginalAccess` | `OriginalAccessPage`                                        | original access inbox/mine, approve/reject                                                                        | Switch queue and decide requests                                            | Loading/error/empty/busy/permission states; route gate only                        | Keep; real API closed loop                        |
| `/project/:id/knowledge` | `viewProject`        | `ProjectKnowledgePage`                                      | `auth`; knowledge list; project QA                                                                                | Browse project assets and ask a question                                    | Error/empty/pending states; no direct page behavior test                           | Keep; add explicit initial loading coverage later |
| `/project/:id/settings`  | `viewProject`        | `ProjectSettingsPage`                                       | `auth`; settings and members read/update                                                                          | Edit settings and member roles                                              | Loading/error/empty/saving/permission states; route gate only                      | Keep; real API closed loop                        |
| `/help`                  | Public               | `HelpPage`                                                  | None by design; static product help                                                                               | Navigate help sections                                                      | Static content; copy hygiene verifies unique anchors                               | Keep; explicit non-API exception                  |

`NotFoundPage` owns the `*` fallback. It is intentionally not a formal product route and has a
direct rendering test.

## Decommission audit

The production import graph contains all 18 route pages. No duplicate or unreachable production
page was found.

### Removed code

| Source                                         | Unreachable/unreferenced evidence                                                                                                                 | Result                                                                                   |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `src/api/admin.ts`                             | No imports or symbol references for `fetchUserSessions`, provider lookup, legacy model create/update/delete/check, or dedicated audit trace fetch | Removed 7 dead wrappers; current people, unified connection, and audit list flows remain |
| `src/api/knowledge.ts`                         | No imports or symbol references for `previewEntryHref`, lifecycle re-enable request/confirm, or grant revoke                                      | Removed 4 dead wrappers; controlled preview fetch and active detail/access flows remain  |
| `src/types/sessionOps.ts`                      | Session list DTOs were referenced only by the removed list wrapper                                                                                | Removed the two unused list DTOs; revoke response retained                               |
| `src/types/weknoraAdmin.ts`                    | Provider/legacy mutate/check DTOs were referenced only by removed wrappers                                                                        | Removed unused legacy DTOs; unified connection DTOs retained                             |
| `src/types/audit.ts`, `src/types/lifecycle.ts` | Dedicated trace and re-enable response DTOs had no remaining consumers                                                                            | Removed those unused DTOs                                                                |

No file was deleted: each affected module still owns active production contracts. Full-repository
symbol search was repeated after removal, and TypeScript build is the final import/type check.

### Retained and registered exceptions

| Candidate                                                  | Evidence and reason retained                                                                                                                                                                                       | Follow-up                                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `src/hooks/usePagination.ts`                               | Not reachable from `main.tsx`, but imported by `usePagination.test.ts`; therefore it fails the task's safe-delete rule                                                                                             | Decide whether to adopt it in a list page or remove hook and test together in a focused task     |
| `src/vite-env.d.ts`                                        | Ambient Vite declaration, consumed by TypeScript rather than a runtime import                                                                                                                                      | Permanent tooling exception                                                                      |
| `src/layouts/AppLayout.css` legacy-looking selector groups | The stylesheet is production-imported. Lexical audit found many candidates, including old `pp-*`, `mk-*`, `perm-*`, `ws-*`, preview, and lifecycle groups, but dynamic class composition prevents proof of non-use | Split styles by page first, then delete selectors with per-page visual regression evidence       |
| Lifecycle re-enable and original grant revoke operations   | Backend contracts may exist, but no current route exposes these user actions; dead frontend wrappers were not a valid implementation                                                                               | Product/authorization decision and a separate end-to-end page task if these actions are required |

No production module imports mock/demo/fixture modules. Timer use is prohibited by the gate unless
registered. The only registered route-owner timer is the PBC-58 OnlyOffice readiness timeout in
`KnowledgeDetailPage`; upload polling uses the real ingest API and is outside the formal page owner
timer exception.

## Coverage gaps and next tasks

- Add behavior tests for the dashboard, knowledge list, project pages, and administration pages;
  the current gate proves ownership and API wiring, not every UI transition.
- Add an explicit initial-loading state/test to `ProjectKnowledgePage` in a separate behavior task.
- Decide whether lifecycle re-enable and original-access grant revocation belong in current product
  surfaces before reintroducing any frontend client methods.
- Decompose the global stylesheet before attempting broad selector cleanup.

## Browser smoke contract

Authenticated browser smoke must cover the dashboard, knowledge list, knowledge detail, upload,
model configuration, and ingest confirmation. For each route, record only the request method,
route category, and status class; never store payloads, credentials, asset text, internal IDs, or
deployment addresses. A route passes only when its expected real network requests occur without an
unexpected 4xx/5xx response. Environment limitations must be reported rather than replaced with
mock success.

### Audit smoke result (2026-07-14)

The production frontend build was served locally and returned HTTP 200. Browser navigation covered
the dashboard, knowledge list, knowledge detail shell, upload, model configuration, and ingest
administration. The dashboard shell rendered; each protected route reached the existing safe
identity-load-failure state without a blank page or browser console error.

The local backend liveness and readiness endpoints were unavailable, so authentication and real
business requests could not be completed or checked for 4xx/5xx responses. This is an environment
blocker, not a passed API smoke. Repeat the same six-route smoke in an authenticated environment
before release.
