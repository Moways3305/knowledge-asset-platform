import ModuleFrame from "../components/ModuleFrame";
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
  const historyOpen = searchParams.get("view") === "history";
  const setHistoryOpen = (open: boolean) =>
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      if (open) next.set("view", "history");
      else next.delete("view");
      return next;
    });
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
    <ModuleFrame
      label="上传工作区导航"
      className="upload-module-frame"
      navigation={
        <>
          <nav className="module-navigation upload-module-navigation" aria-label="上传工作区">
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

          <aside className="upload-process-guide" aria-label="资料入库流程">
            <h2>资料入库流程</h2>
            <ol>
              <li aria-current={!confirmationOpen ? "step" : undefined}>
                <strong>选择资料</strong>
                <p>从本地文件或企微微盘开始。</p>
              </li>
              <li aria-current={confirmReady && !confirmSubmitted ? "step" : undefined}>
                <strong>核对信息</strong>
                <p>确认目录、名称与访问范围。</p>
              </li>
              <li aria-current={confirmSubmitted ? "step" : undefined}>
                <strong>确认入库</strong>
                <p>按现有规则完成确认或审批。</p>
              </li>
            </ol>
            <p className="upload-guide-note">处理进度与需要你确认的事项，会显示在当前工作区。</p>
          </aside>
        </>
      }
    >
      <ProductPage className="upload-page upload77-page">
        <PageHeader
          title={historyOpen ? "上传记录" : confirmationOpen ? "核对入库信息" : "上传资料"}
          description={
            historyOpen
              ? "查看本人上传资料的处理结果，按范围、状态或日期筛选。"
              : "选择资料来源，上传后核对内容建议并确认入库。"
          }
          actions={
            <Link className="product-button is-secondary is-small" to="/knowledge">
              返回知识库
            </Link>
          }
          status={
            !historyOpen && (
              <StatusBadge
                tone={confirmationOpen ? "warning" : taskId ? "info" : "neutral"}
                label={confirmationOpen ? "待确认入库信息" : taskId ? "资料处理中" : "尚未开始"}
              />
            )
          }
        />

        <div className={`upload-content-layout${historyOpen ? " is-history" : ""}`}>
          <div className="upload-content-main">
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
                    本次为「{flow.updateContext.source_title}
                    」的关联新版，旧版仍保持有效。完成入库后，
                    <Link
                      to={`/knowledge/${flow.updateContext.source_asset_id}`}
                      state={{ backTo: "/upload", backLabel: "返回上传资料", source: "upload" }}
                    >
                      回原资料核查并确认替代
                    </Link>
                    。
                  </p>
                )}
                <UploadConfirmPanel
                  flow={flow}
                  onExit={exitConfirmation}
                  onReject={rejectConfirmation}
                />
              </>
            )}
          </div>
        </div>
      </ProductPage>
    </ModuleFrame>
  );
}
