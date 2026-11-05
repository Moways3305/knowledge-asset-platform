# 本轮生产发布准备

用户已要求结束隔离 UI 验收并进入生产部署。本轮生产源码基线为 `ae8be0a2b425dbc8be645e6444bcfba54b0f691b`，WeKnora 仍为 v0.7.1；应用与 PostgreSQL 使用不同的 Compose 工作目录。不得将演练空库或旧演练快照替代当前生产数据。

`scripts/prepare_production_release.py --revision <完整提交> --build-stage /data/weknora/upgrade-rehearsals/run-eDkLxh7B/keyword-build-5320ceda3e --version 1.0.0` 完成切换前准备，公开输出明确标记 `production_switched=false`。

1. 请求本轮 UI 会话结束并等待演练锁释放。清理继承 `com.docker.compose.project=kap` 的演练容器前，联合检查明确的演练容器名称、演练目录标签和挂载；生产同名容器、生产卷、无法确认的容器均拒绝清理。保存容器描述和尾部日志，不使用 `docker rm -v`，保留全部测试数据卷和宿主验收记录。
2. 在已知可写、磁盘空间充足的演练主目录下建立 `production-preparations/<时间和随机编号>`，以 0700/0600 权限保存生产容器描述、配置、解析后的 Compose、回滚镜像标签、数据库角色和每个非模板数据库的在线备份。验证 `pg_restore --list` 成功。数据库在线备份不等同于停写后的数据库/文件一致性备份；后者须在正式切换阶段取得。
3. 创建独立的固定提交工作树，生产仓库不 checkout、不 reset。复制环境文件只用于 Compose 配置，前后端 Docker 构建上下文均排除环境文件。复核候选 WeKnora 补丁镜像及对应已通过离线记录。
4. 按现有 `deploy_release.py` 生成版本清单，逐个构建六个唯一候选镜像，不覆盖生产镜像标签；校验各镜像内的发布身份和迁移 head。重新比较生产容器指纹。

只有上述全部完成才写 `PREPARED` 和 `prepare-report.json` 的 `passed=true`。这不是部署成功标记，不执行生产迁移、不切换镜像、不更改模型、不发布更新公告。异常只输出受控摘要，私密日志不得回传。

后续正式切换必须使用本次准备目录记录的不可变镜像，先停写并备份当前生产数据库与文件，保留旧数据卷；按已演练的顺序升级 WeKnora PostgreSQL 扩展与 schema，然后迁移并部署 KAP、修正已指定的模型地址及共享凭据，核对健康与发布身份。生产恢复不能仅把旧 ParadeDB 镜像接回已升级的数据卷；版本登记仍通过 `deploy_release.py --sync-only --apply` 完成，公告保持待审核。
