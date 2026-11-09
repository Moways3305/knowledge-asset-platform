#!/usr/bin/env bash
# Run the authorized cutover independently of the SSH terminal; show sanitized progress only.
set -Eeuo pipefail
umask 077
stage=${1:?preparation directory required}
if [[ "$stage" != /data/weknora/upgrade-rehearsals/run-eDkLxh7B/production-preparations/* ]] || [[ ! -f "$stage/PREPARED" ]]; then
  echo '准备目录或完成标记不匹配，未开始切换。'
  exit 1
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
launch_dir=$(mktemp -d "$stage/cutover-launch-XXXXXX")
nohup bash -c '
  set +e
  python3 -u "$1/execute_production_cutover.py" --stage "$2" --execute
  result=$?
  printf "\n部署任务退出码：%s\n" "$result"
  printf "%s\n" "$result" > "$3/exit-code"
  exit "$result"
' cutover "$script_dir" "$stage" "$launch_dir" \
  >"$launch_dir/progress.log" 2>"$launch_dir/launcher-private.log" </dev/null &
worker_pid=$!
printf '后台 PID：%s\n脱敏进度日志：%s\n' "$worker_pid" "$launch_dir/progress.log"
printf '终端断开后任务继续运行；查看同一进度日志，不要重复启动。\n'
tail --pid="$worker_pid" -n +1 -f "$launch_dir/progress.log"
set +e
wait "$worker_pid"
result=$?
set -e
exit "$result"
