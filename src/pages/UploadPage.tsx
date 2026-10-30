import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import MyUploadsPanel from "../components/MyUploadsPanel";
import UploadConfirmPanel from "./upload/UploadConfirmPanel";
import UploadStepA from "./upload/UploadStepA";
import UploadStepB from "./upload/UploadStepB";
import { useUploadFlow } from "./upload/useUploadFlow";
import "./UploadPage.css";

export default function UploadPage() {
  const flow = useUploadFlow();
  const [searchParams, setSearchParams] = useSearchParams();
  const [rejectError, setRejectError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const {
    activePath,
    switchPath,
    confirmReady,
    confirmSubmitted,
    handleDeletePending,
    taskId,
    handleReset,
    localPendingTasks,
    handleSelectPendingTask,
    targetLocked,
    targetLibrary,
    setTargetLibrary,
    setTargetProjectId,
  } = flow;
  const confirmationOpen = confirmReady || confirmSubmitted;
  const resumedTask = useRef<string | null>(null);
  useEffect(() => {
    const requested = searchParams.get("task_id");
    const task = (localPendingTasks ?? []).find((item) => item.id === requested);
    if (activePath === "b" && task && resumedTask.current !== requested) {
      resumedTask.current = requested;
      void handleSelectPendingTask(task);
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.delete("task_id");
          return next;
        },
        { replace: true },
      );
    }
  }, [activePath, searchParams, localPendingTasks, handleSelectPendingTask, setSearchParams]);

  useEffect(() => {
    const requested = searchParams.get("source");
    if (requested === "wecom" && activePath !== "a") switchPath("a");
    if (requested === "local" && activePath !== "b") switchPath("b");
  }, [activePath, searchParams, switchPath]);

  const projectPrefill = useRef<string | null>(null);
  const sourceProject = (flow.projects ?? []).find(
    (project) => project.projectId === searchParams.get("project_id"),
  );
  useEffect(() => {
    if (
      !sourceProject ||
      activePath !== "b" ||
      !confirmReady ||
      !taskId ||
      targetLocked ||
      projectPrefill.current === taskId
    )
      return;
    projectPrefill.current = taskId;
    if (!targetLibrary) {
      setTargetLibrary("project");
      setTargetProjectId(sourceProject.projectId);
    }
  }, [
    sourceProject,
    activePath,
    confirmReady,
    taskId,
    targetLocked,
    targetLibrary,
    setTargetLibrary,
    setTargetProjectId,
  ]);

  const selectSource = (path: "a" | "b") => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set("source", path === "a" ? "wecom" : "local");
        return next;
      },
      { replace: true },
    );
    switchPath(path);
  };

  const exitConfirmation = () => {
    setRejectError(null);
    handleReset();
    // Preserve the source context: local upload returns to local, WeCom to WeCom.
    switchPath(activePath);
  };

  const rejectConfirmation = async () => {
    if (!taskId) return;
    setRejectError(null);
    try {
      // A rejection is permanent only after the server confirms deletion.  Do
      // not discard the editable form or source context on a failed delete.
      await handleDeletePending(taskId);
    } catch {
      setRejectError("拒绝入库失败，资料尚未删除。请重试或返回后继续处理。");
      return;
    }
  };

  return (
    <ProductPage className="upload-page upload77-page">
      <PageHeader
        eyebrow="内容资产化"
        title="上传文件"
        description="选择资料来源，上传后核对内容建议并确认入库。"
        status={
          <StatusBadge
            tone={confirmationOpen ? "warning" : taskId ? "info" : "neutral"}
            label={confirmationOpen ? "待确认入库信息" : taskId ? "资料处理中" : "尚未开始"}
          />
        }
      />

      <nav className="upload-workspace-tabs" aria-label="上传工作区">
        <button
          type="button"
          aria-current={!historyOpen ? "page" : undefined}
          onClick={() => setHistoryOpen(false)}
        >
          上传
        </button>
        <button
          type="button"
          aria-current={historyOpen ? "page" : undefined}
          onClick={() => setHistoryOpen(true)}
        >
          上传记录
        </button>
      </nav>
      {sourceProject && !historyOpen && (
        <p className="upload-project-context">
          当前项目：{sourceProject.projectName}。确认入库时仍可核对目标。
        </p>
      )}
      {!historyOpen && !confirmationOpen && (
        <div className="upload77-source-toolbar">
          <span className="upload77-source-label">资料来源</span>
          <div className="upload77-source-switch" role="group" aria-label="资料来源">
            <button
              className={activePath === "b" ? "is-active" : ""}
              aria-pressed={activePath === "b"}
              onClick={() => selectSource("b")}
              type="button"
            >
              本地上传
            </button>
            <button
              className={activePath === "a" ? "is-active" : ""}
              aria-pressed={activePath === "a"}
              onClick={() => selectSource("a")}
              type="button"
            >
              企微微盘待确认
            </button>
          </div>
        </div>
      )}

      {historyOpen && (
        <MyUploadsPanel onClose={() => setHistoryOpen(false)} onReupload={handleReset} />
      )}

      {!historyOpen && activePath === "a" && !confirmationOpen && <UploadStepA flow={flow} />}
      {!historyOpen && activePath === "b" && !confirmationOpen && <UploadStepB flow={flow} />}
      {!historyOpen && confirmationOpen && (
        <>
          {rejectError && (
            <div className="upload77-confirm-error" role="alert">
              {rejectError}
            </div>
          )}
          {flow.updateContext && (
            <p>
              本次为「{flow.updateContext.source_title}」的关联新版，旧版仍保持有效。完成入库后，
              <Link to={`/knowledge/${flow.updateContext.source_asset_id}`}>
                回原资料核查并确认替代
              </Link>
              。
            </p>
          )}
          <UploadConfirmPanel flow={flow} onExit={exitConfirmation} onReject={rejectConfirmation} />
        </>
      )}
    </ProductPage>
  );
}
