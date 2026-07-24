import { PageHeader, ProductPage } from "../components/ProductLayout";
import UploadConfirmPanel from "./upload/UploadConfirmPanel";
import UploadStepA from "./upload/UploadStepA";
import UploadStepB from "./upload/UploadStepB";
import { useUploadFlow } from "./upload/useUploadFlow";
import "./UploadPage.css";

export default function UploadPage() {
  const flow = useUploadFlow();
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

  const exitConfirmation = () => {
    handleReset();
    switchPath("a");
  };

  const rejectConfirmation = async () => {
    if (taskId) {
      try {
        await handleDeletePending(taskId);
      } catch {
        // 删除失败仍允许退出
      }
    }
    handleReset();
    switchPath("a");
  };

  return (
    <ProductPage className="upload-page upload77-page">
      <PageHeader
        eyebrow="内容资产化"
        title="上传与入库"
        description="选择资料来源，处理完成后核对内容建议并确认入库。"
      />

      <div className="upload77-source-switch" aria-label="资料来源">
        <button
          className={activePath === "b" ? "is-active" : ""}
          onClick={() => switchPath("b")}
          type="button"
        >
          本地上传
        </button>
        <button
          className={activePath === "a" ? "is-active" : ""}
          onClick={() => switchPath("a")}
          type="button"
        >
          企微微盘待确认
        </button>
      </div>

      {activePath === "a" && !confirmationOpen && <UploadStepA flow={flow} />}
      {activePath === "b" && !confirmationOpen && <UploadStepB flow={flow} />}
      {confirmationOpen && (
        <UploadConfirmPanel flow={flow} onExit={exitConfirmation} onReject={rejectConfirmation} />
      )}
    </ProductPage>
  );
}
