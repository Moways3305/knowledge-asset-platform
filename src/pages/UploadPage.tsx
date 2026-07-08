import { useUploadFlow } from "./upload/useUploadFlow";
import UploadNamingCard from "./upload/UploadNamingCard";
import UploadStepA from "./upload/UploadStepA";
import UploadStepB from "./upload/UploadStepB";
import UploadConfirmPanel from "./upload/UploadConfirmPanel";

// 资产化确认工作台。页面本体只做步骤路由与顶层 state 传递：全部状态/逻辑在
// useUploadFlow，展示拆到 UploadNamingCard / UploadStepA / UploadStepB / UploadConfirmPanel。
export default function UploadPage() {
  const flow = useUploadFlow();
  const { activePath, switchPath, confirmReady, confirmSubmitted, flowState } = flow;

  return (
    <div className="upload-page">
      {/* Unified header */}
      <div className="up-header">
        <div className="up-header-text">
          <h2>资产化确认工作台</h2>
          <p>上传文件后，平台会提取内容并生成入库建议，你确认后再进入知识库。</p>
        </div>
      </div>

      {/* Path branch selector */}
      <div className="up-path-branches">
        <button
          className={`up-path-card ${activePath === "a" ? "active" : ""}`}
          onClick={() => switchPath("a")}
        >
          <div className="up-path-card-title">企业微信待确认</div>
          <div className="up-path-card-desc">
            查看企业微信微盘产生的待确认文件，校正建议后提交入库
          </div>
        </button>
        <button
          className={`up-path-card ${activePath === "b" ? "active" : ""}`}
          onClick={() => switchPath("b")}
        >
          <div className="up-path-card-title">本地上传</div>
          <div className="up-path-card-desc">选择本地文件，生成内容建议，确认后进入知识库</div>
        </button>
      </div>
      <p className="up-path-shared-note">两种来源共享相同的内容提取、人工校正和入库确认流程</p>

      {/* 命名规范与保密分级 */}
      <UploadNamingCard naming={flow.naming} confirmConfidence={flow.confirmConfidence} />

      {/* 企业微信待确认任务 */}
      {activePath === "a" && <UploadStepA flow={flow} />}

      {/* 本地上传流程 */}
      {activePath === "b" && <UploadStepB flow={flow} />}

      {/* 共享确认区 */}
      {(confirmReady || confirmSubmitted) && <UploadConfirmPanel flow={flow} />}

      {/* 本地上传占位 */}
      {activePath === "b" && !confirmReady && !confirmSubmitted && (
        <section className="upload-section">
          <h3>AI 生成预览</h3>
          <div className="up-preview-placeholder">
            <div className="up-preview-placeholder-title">
              {flowState === "processing" ? "AI 正在提取中…" : "待生成"}
            </div>
            <p>
              {flowState === "processing"
                ? "文件已上传至平台受控存储，正在抽取文本并生成结构化建议，请稍候…"
                : "选择文件并启动资产化后，平台将生成标题、摘要、标签等结构化建议，供你在提交前校正。"}
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
