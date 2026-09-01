# 正式目录 UI QA 与生产验收记录

日期：2026-09-01

结论：UI/前端代码验收通过；严格生产验收未完成，当前不应标记为生产可发布。

## UI 与前端验证

- 目录治理页覆盖公司与项目范围、名称、说明、命名短码、默认密级、排序、启停、发布以及历史迁移队列；4/4 场景通过。
- 项目知识发布覆盖正式目录、主题、资料日期、版本、适用范围、密级与 canonical 预览；52/52 断言通过。
- 个人知识升级到项目覆盖同一套正式目录元数据；40/40 断言通过。
- 上传入库仅保留正式目录，不再请求目录类别或资产类型分类；64/64 断言通过。
- 四组脚本均覆盖 1440、1024、768、390 像素视口，并检查内容裁切、横向溢出和操作可达性。
- 前端单元测试：76 个文件、563 项测试通过。
- `npm run lint` 与 `npm run build` 通过。
- 旧脚本 `naming-rules-scoped.ui-qa.mjs` 已由 `directory-governance.ui-qa.mjs` 取代；本目录中的截图是本次验收的权威截图，旧任务截图不作为本次结论依据。

截图目录：

- `directory-governance/`
- `company-upload/`
- `project-publication/`
- `personal-project-publication/`

## 后端与 OCR 回归

- `python -m pytest backend/tests/test_ocr_queue_recovery.py backend/tests/test_ingest_task_status.py -q`：29 项通过。
- `python -m pytest backend/tests/test_naming_rules.py -q`：10 项通过。
- Windows 后端全量测试共收集 1378 项：1367 项通过、2 项跳过、9 项失败。9 个失败均位于 `test_production_guards.py`，直接原因是 Windows 环境找不到测试调用的 `sh`。

## Linux/Compose 静态验证

- 使用 `.env.example` 与仅存在于当前进程的安全占位密码执行基础 Compose + production override 的 `config --quiet`，配置可渲染。
- 渲染结果包含 `backend`、`frontend`、`migrate`、`postgres`、`redis`、`worker`、`ocr_worker`、`beat`。
- 普通 worker 使用 `--queues=default --prefetch-multiplier=1`。
- OCR worker 使用独立 `ocr` 队列、并发 1、prefetch 1、`max-tasks-per-child=4`、`max-memory-per-child=700000`，容器限制为 2 GiB / 2 CPU，重启策略为 `unless-stopped`。
- 在 WSL Ubuntu 中直接运行 OnlyOffice 来源校验脚本：合法来源通过；包含注入内容的非法来源被拒绝，非法输入未进入输出。

## 严格生产验收阻塞项

以下项目未完成，因此本记录不构成严格生产验收通过：

1. 仓库当前真实 `.env` 缺少 `POSTGRES_PASSWORD`，`docker compose --env-file .env ... config --quiet` 无法通过。未改写用户环境或用占位密码启动现有数据卷。
2. 未使用真实生产密钥完成完整服务启动、健康检查与运行态 worker 参数观察。
3. 未在生产等价容器中执行单 PDF OCR、内存背压和孤儿任务恢复演练。
4. 当前 WSL Ubuntu 没有 pytest，未完成 Linux 环境的后端全量测试；Windows 的 shell 测试失败不能替代 Linux 全量结果。

解除以上条件后，应在隔离或获准的生产等价环境中补跑并追加证据，再更新严格验收结论。
