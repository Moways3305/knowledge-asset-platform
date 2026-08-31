import { useEffect, useState } from "react";
import { ArrowRight, Cable, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchWorkbuddyToken, type WorkbuddyTokenStatusVM } from "../api/workbuddy";
import { formatBeijingTime } from "../utils/time";

type StatusState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; value: WorkbuddyTokenStatusVM };

export default function WorkbuddyStatusPanel() {
  const [state, setState] = useState<StatusState>({ status: "loading" });
  const load = () => {
    setState({ status: "loading" });
    void fetchWorkbuddyToken()
      .then((value) => setState({ status: "ready", value }))
      .catch(() => setState({ status: "error" }));
  };

  useEffect(load, []);

  let label = "正在确认连接状态…";
  let tone = "is-loading";
  if (state.status === "error") {
    label = "连接状态暂时无法加载";
    tone = "is-error";
  } else if (state.status === "ready") {
    if (!state.value.enabled) {
      label = "尚未启用";
      tone = "is-disabled";
    } else if (!state.value.lastConnectedAt) {
      label = "已启用，等待首次成功连接";
      tone = "is-waiting";
    } else {
      label = `已连接 · 最近成功连接 ${formatBeijingTime(state.value.lastConnectedAt)}`;
      tone = "is-connected";
    }
  }

  return (
    <section className="workbench-workbuddy" aria-labelledby="workbench-workbuddy-title">
      <div className="workbench-context-heading">
        <div>
          <Cable size={17} aria-hidden="true" />
          <h2 id="workbench-workbuddy-title">WorkBuddy 接入</h2>
        </div>
      </div>
      <p className={`workbench-workbuddy-status ${tone}`} aria-live="polite">
        {label}
      </p>
      {state.status === "error" ? (
        <button type="button" className="workbench-inline-action" onClick={load}>
          <RefreshCw size={14} aria-hidden="true" />
          重新加载
        </button>
      ) : (
        <Link className="workbench-inline-action" to="/my/workbuddy">
          前往设置
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      )}
    </section>
  );
}
