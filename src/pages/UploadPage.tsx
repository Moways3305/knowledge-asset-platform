import { useUploadFlow } from "./upload/useUploadFlow";
import UploadNamingCard from "./upload/UploadNamingCard";
import UploadStepA from "./upload/UploadStepA";
import UploadStepB from "./upload/UploadStepB";
import UploadConfirmPanel from "./upload/UploadConfirmPanel";
import { PageHeader, ProductPage } from "../components/ProductLayout";

// 资产化确认工作台。页面本体只做步骤路由与顶层 state 传递：全部状态/逻辑在
// useUploadFlow，展示拆到 UploadNamingCard / UploadStepA / UploadStepB / UploadConfirmPanel。
export default function UploadPage() {
  const flow = useUploadFlow();
  const {
    activePath,
    switchPath,
    confirmReady,
    confirmSubmitted,
    awaitingProjectReview,
    flowState,
  } = flow;

  const progress = [
    { label: "上传", done: flowState !== "idle" || confirmReady || confirmSubmitted },
    { label: "提取", active: flowState === "processing", done: confirmReady || confirmSubmitted },
    { label: "确认", active: confirmReady && !confirmSubmitted, done: confirmSubmitted },
    {
      label: "进入知识库",
      displayLabel: awaitingProjectReview ? "项目审批" : undefined,
      active: awaitingProjectReview,
      done: confirmSubmitted && !awaitingProjectReview,
    },
  ];

  return (
    <ProductPage className="upload-page">
      <PageHeader
        eyebrow="内容资产化"
        title="上传与入库"
        description="选择内容来源，完成提取与确认后进入知识库。"
      />

      <ol className="product-flow-steps" aria-label="资产化进度">
        {progress.map((step, index) => (
          <li
            className={`${step.active ? "is-active" : ""} ${step.done ? "is-done" : ""}`.trim()}
            key={step.label}
          >
            <span>{index + 1}</span>
            {step.displayLabel ?? step.label}
          </li>
        ))}
      </ol>

      {/* Path branch selector */}
      <div className="product-segmented" aria-label="内容来源">
        <button
          className={activePath === "a" ? "is-active" : ""}
          onClick={() => switchPath("a")}
          type="button"
        >
          企业微信待确认
        </button>
        <button
          className={activePath === "b" ? "is-active" : ""}
          onClick={() => switchPath("b")}
          type="button"
        >
          本地上传
        </button>
      </div>
      <p className="up-path-shared-note">
        {activePath === "a"
          ? "查看企业微信微盘产生的待确认文件，校正建议后提交入库。"
          : "选择本地文件，生成内容建议，确认后进入知识库。"}
      </p>

      {/* 企业微信待确认任务 */}
      {activePath === "a" && <UploadStepA flow={flow} />}

      {/* 本地上传流程 */}
      {activePath === "b" && <UploadStepB flow={flow} />}

      {/* 仅在内容处理完成并返回解析结果后展示 */}
      {flow.naming && (
        <UploadNamingCard naming={flow.naming} confirmConfidence={flow.confirmConfidence} />
      )}

      {/* 共享确认区 */}
      {(confirmReady || confirmSubmitted) && <UploadConfirmPanel flow={flow} />}

      {/* 本地上传占位 */}
      {activePath === "b" && flowState === "processing" && (
        <section className="upload-section">
          <h3>正在生成内容建议</h3>
          <div className="up-preview-placeholder">
            <div className="up-preview-placeholder-title">内容正在提取中…</div>
            <p>正在生成标题、摘要和标签建议，请稍候。</p>
          </div>
        </section>
      )}
    </ProductPage>
  );
}
