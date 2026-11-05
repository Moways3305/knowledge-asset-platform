# 本轮生产发布准备

用户已要求结束隔离 UI 验收并进入生产部署。本轮生产源码基线为 `ae8be0a2b425dbc8be645e6444bcfba54b0f691b`，WeKnora 仍为 v0.7.1；应用与 PostgreSQL 使用不同的 Compose 工作目录。不得将演练空库或旧演练快照替代当前生产数据。

`scripts/prepare_production_release.py --revision <完整提交> --build-stage /data/weknora/upgrade-rehearsals/run-eDkLxh7B/keyword-build-5320ceda3e --version 1.0.0` 完成切换前准备，公开输出明确标记 `production_switched=false`。

1. 请求本轮 UI 会话结束并等待演练锁释放。清理继承 `com.docker.compose.project=kap` 的演练容器前，联合检查明确的演练容器名称、演练目录标签和挂载；生产同名容器、生产卷、无法确认的容器均拒绝清理。保存容器描述和尾部日志，不使用 `docker rm -v`，保留全部测试数据卷和宿主验收记录。
2. 在已知可写、磁盘空间充足的演练主目录下建立 `production-preparations/<时间和随机编号>`，以 0700/0600 权限保存生产容器描述、配置、解析后的 Compose、回滚镜像标签、数据库角色和每个非模板数据库的在线备份。验证 `pg_restore --list` 成功。数据库在线备份不等同于停写后的数据库/文件一致性备份；后者须在正式切换阶段取得。
3. 创建独立的固定提交工作树，生产仓库不 checkout、不 reset。复制环境文件只用于 Compose 配置，前后端 Docker 构建上下文均排除环境文件。复核候选 WeKnora 补丁镜像及对应已通过离线记录。
4. 按现有 `deploy_release.py` 生成版本清单，逐个构建六个唯一候选镜像，不覆盖生产镜像标签；校验各镜像内的发布身份和迁移 head。重新比较生产容器指纹。

只有上述全部完成才写 `PREPARED` 和 `prepare-report.json` 的 `passed=true`。这不是部署成功标记，不执行生产迁移、不切换镜像、不更改模型、不发布更新公告。异常只输出受控摘要，私密日志不得回传。

后续正式切换必须使用本次准备目录记录的不可变镜像，先停写并备份当前生产数据库与文件，保留旧数据卷；按已演练的顺序升级 WeKnora PostgreSQL 扩展与 schema，然后迁移并部署 KAP、修正已指定的模型地址及共享凭据，核对健康与发布身份。生产恢复不能仅把旧 ParadeDB 镜像接回已升级的数据卷；版本登记仍通过 `deploy_release.py --sync-only --apply` 完成，公告保持待审核。


历史一次性迁移容器的镜像缺失时，可显式传入 `--allow-missing-completed-migrate-image`。
该例外只适用于名称、Compose 项目/服务均匹配的 `kap-migrate-1`，且其状态为 exited、退出码为 0、没有自动重启策略。
其他容器缺失镜像、Docker 检查错误或镜像身份不一致仍然停止准备。不会删除、重建或启动历史迁移容器，也不会用已漂移的原标签冒充旧镜像。
`rollback-images.json` 将该历史任务标记为 `completed_job_image_missing`、`tag=null`、`recreate_on_rollback=false`；这不表示原镜像已恢复。
所有运行服务仍须保留并核验原镜像标签。后续回滚只恢复服务与一致性备份，不应重新运行已完成的历史迁移容器；新版本迁移使用本次构建并核验的候选迁移镜像。


构建超时后的同目录续建：`resume_production_build.py --stage <原准备目录> --revision <原候选完整提交>`。
工具与同版本 `prepare_production_release.py` 放在单独的启动目录中，不修改原候选源码工作树。
只接受本轮已经保留运行服务回滚镜像、验证在线数据库备份但未写 PREPARED 的失败准备记录。
续建前后核对生产容器指纹和运行状态、原回滚镜像、生产/候选环境文件、备份文件大小、候选源码提交与工作区状态、候选标签及已通过离线的 WeKnora 镜像。
只以构建参数使用腾讯云 HTTPS Debian 主仓库及安全仓库，保留基础镜像中的发行版套件和签名配置；不改宿主源、不重启 Docker、不启用容器、不跑迁移、不写生产模型配置。
原备份仍只是在线备份，不能替代切换前的停写一致性备份。构建单服务上限为 1800 秒，超时终止本次启动的构建客户端进程组；脱敏进度只输出固定步骤标签。
全部镜像版本身份、迁移 head 和生产未变核验通过后才更新准备报告并写 PREPARED。失败写 resume-report.json，原失败准备报告与备份保留。
镜像源依据：https://cloud.tencent.com/document/product/213/8623 。
