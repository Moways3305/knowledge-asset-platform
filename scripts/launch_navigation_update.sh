#!/usr/bin/env bash
# Run the pinned PR #244 delivery helper outside the production checkout.
set -euo pipefail
umask 077

KAP_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KAP_SCRIPT="$KAP_SCRIPT_DIR/deploy_navigation_update.py"
test -f "$KAP_SCRIPT"
test "$(id -un)" = ubuntu
sudo -v

# The pinned helper commit contains this merged business revision as an ancestor.
git -C /data/kap/repo cat-file -e f9d4cdbf220e65255b88513bb16fffd9f8d36c1f^{commit}
KAP_LAUNCH="$(mktemp -d "$HOME/kap-navigation-launch-XXXXXX")"
KAP_INVENTORY="$(sudo -n mktemp -d /data/kap/release-preparations/inventory-navigation-XXXXXXXXXX)"
KAP_RUN="$(sudo -n mktemp -d /data/kap/release-preparations/release-XXXXXXXXXX)"
KAP_LOG="$KAP_LAUNCH/progress.log"
: > "$KAP_LOG"
printf '%s\n' "$KAP_INVENTORY" | sudo -n tee "$KAP_RUN/inventory-path.txt" >/dev/null
sudo -n chmod 600 "$KAP_RUN/inventory-path.txt"
printf '%s\n' "$KAP_SCRIPT" > "$KAP_LAUNCH/helper-path.txt"
printf '%s\n' "$KAP_RUN" > "$KAP_LAUNCH/record-path.txt"

nohup bash -c '
    set +e
    sudo -n flock -n -E 75 /data/kap/repo/.git/kap-deploy.lock \
        env GIT_OPTIONAL_LOCKS=0 python3 -B -u "$1" \
        --inventory "$2" --output "$3"
    result=$?
    printf "\n部署任务退出码：%s\n" "$result"
    printf "%s\n" "$result" > "$4/exit-code"
    exit "$result"
' _ "$KAP_SCRIPT" "$KAP_INVENTORY" "$KAP_RUN" "$KAP_LAUNCH" > "$KAP_LOG" 2>&1 </dev/null &
KAP_PID=$!

printf '后台 PID：%s\n' "$KAP_PID"
printf '盘点记录目录：%s\n' "$KAP_INVENTORY"
printf '部署记录目录：%s\n' "$KAP_RUN"
printf '脱敏进度日志：%s\n' "$KAP_LOG"
printf '查看进度：tail --pid=%s -n +1 -f %q\n' "$KAP_PID" "$KAP_LOG"
printf '后台任务已提交，断开终端不影响执行，请勿重复启动。\n'
tail -n 40 "$KAP_LOG"
