import { useState } from "react";
import { ListTodo } from "lucide-react";
import { useWorkbench } from "../workbench/WorkbenchContext";
import TaskCenterDrawer from "./TaskCenterDrawer";

export default function GlobalTaskStatus() {
  const { overview, state, refresh } = useWorkbench();
  const [open, setOpen] = useState(false);
  const center = overview?.task_center;
  const count = center?.summary.needs_action ?? 0;
  const groups = {
    my_tasks: center?.my_tasks ?? [],
    running_jobs: center?.running_jobs ?? [],
    attention_items: center?.attention_items ?? [],
    recent_completed: center?.recent_completed ?? [],
  };
  return (
    <>
      <button
        type="button"
        className="global-task-status"
        aria-label={state === "error" ? "任务状态暂不可用" : `打开任务中心，${count} 项待处理`}
        onClick={() => {
          setOpen(true);
          void refresh();
        }}
      >
        <ListTodo size={18} aria-hidden="true" />
        {count > 0 && <span>{count > 99 ? "99+" : count}</span>}
      </button>
      <TaskCenterDrawer open={open} groups={groups} onClose={() => setOpen(false)} />
    </>
  );
}
