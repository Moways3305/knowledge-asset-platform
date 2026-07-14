# 公司治理 Bootstrap

首位 Boss 只能由服务器上的一次性管理命令建立。该命令不提供 HTTP 路由，也不接受密码、邮件或 token；目标必须是数据库中已存在的活动用户。

## 执行前

1. 备份数据库，并确认当前确实没有有效 Boss。
2. 在受控终端中取得目标活动用户的内部标识，不要写入工单、聊天或部署日志。
3. 使用与应用相同的运行环境和数据库配置执行命令。

Linux 容器示例（静默读取，避免进入 shell history）：

```bash
read -rs KAP_BOOTSTRAP_BOSS_TARGET_USER_ID
export KAP_BOOTSTRAP_BOSS_TARGET_USER_ID
python -m app.commands.bootstrap_boss
unset KAP_BOOTSTRAP_BOSS_TARGET_USER_ID
```

命令只输出以下固定状态之一，不回显身份信息：

- `boss_bootstrap_created`：首位 Boss 已建立。
- `boss_bootstrap_already_configured`：已有有效 Boss，未执行任何授予。
- `boss_bootstrap_target_unavailable`：目标不是可用的活动用户，未执行授予。
- `boss_bootstrap_invalid_target`：输入格式无效，未访问业务数据。

成功操作会写入 `governance.boss_bootstrapped` 系统审计，事件不包含操作者、目标身份或底座配置。

## 交接与回滚

日常交接必须由现有 Boss 先授予另一位活动用户 Boss，再停用旧 Boss。服务端会拒绝停用最后一个有效 Boss，也会拒绝停用最后一个有效 admin。

Bootstrap 不能覆盖、降级或移除既有 Boss，因此不能作为普通管理后门。若目标授予错误，应先由该 Boss 完成受控交接，再停用错误角色；不要直接修改数据库。数据库恢复仅用于灾难恢复，并按既有备份恢复流程执行。
