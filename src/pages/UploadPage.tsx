import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
  } = flow;
  const confirmationOpen = confirmReady || confirmSubmitted;

  useEffect(() => {
    const requested = searchParams.get("source");
    if (requested === "wecom" && activePath !== "a") switchPath("a");
    if (requested === "local" && activePath !== "b") switchPath("b");
  }, [activePath, searchParams, switchPath]);

  const selectSource = (path: "a" | "b") => {
    setSearchParams({ source: path === "a" ? "wecom" : "local" }, { replace: true });
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

      <div className="upload77-source-switch" aria-label="资料来源">
        <button
          className={activePath === "b" ? "is-active" : ""}
          onClick={() => selectSource("b")}
          type="button"
        >
          本地上传
        </button>
        <button
          className={activePath === "a" ? "is-active" : ""}
          onClick={() => selectSource("a")}
          type="button"
        >
          企微微盘待确认
        </button>
        <button type="button" onClick={() => setHistoryOpen(true)}>
          我上传的资料
        </button>
      </div>

      {historyOpen && <MyUploadsPanel onClose={() => setHistoryOpen(false)} />}

      {!historyOpen && activePath === "a" && !confirmationOpen && <UploadStepA flow={flow} />}
      {!historyOpen && activePath === "b" && !confirmationOpen && <UploadStepB flow={flow} />}
      {!historyOpen && confirmationOpen && (
        <>
          {rejectError && (
            <div className="upload77-confirm-error" role="alert">
              {rejectError}
            </div>
          )}
          <UploadConfirmPanel flow={flow} onExit={exitConfirmation} onReject={rejectConfirmation} />
        </>
      )}
    </ProductPage>
  );
}
