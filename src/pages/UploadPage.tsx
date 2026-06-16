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
          <p>
            路径 A 企微微盘待确认任务与路径 B 本地上传，在此统一进行 AI
            预览、人工校正、目标库确认和提交入库
          </p>
        </div>
      </div>

      {/* Path branch selector */}
      <div className="up-path-branches">
        <button
          className={`up-path-card ${activePath === "a" ? "active" : ""}`}
          onClick={() => switchPath("a")}
        >
          <div className="up-path-card-title">路径A：企微微盘自动检测</div>
          <div className="up-path-card-desc">
            企微微盘扫描项目目录，检测新增文件并落入待确认队列，在此完成人工校正与确认入库
          </div>
        </button>
        <button
          className={`up-path-card ${activePath === "b" ? "active" : ""}`}
          onClick={() => switchPath("b")}
        >
          <div className="up-path-card-title">路径B：本地上传资产化</div>
          <div className="up-path-card-desc">
            手动选择本地文件，上传至平台受控存储后由 worker 异步抽取 + 外部 LLM
            生成建议，人工校正后提交入库
          </div>
        </button>
      </div>
      <p className="up-path-shared-note">
        两条路径共享相同的 AI 提取 → 人工校正 → 入库/审核分流 模型
      </p>

      {/* 命名规范与保密分级 */}
      <UploadNamingCard naming={flow.naming} confirmConfidence={flow.confirmConfidence} />

      {/* 路径 A：企微微盘待确认任务 */}
      {activePath === "a" && <UploadStepA flow={flow} />}

      {/* 路径 B：本地上传流程 */}
      {activePath === "b" && <UploadStepB flow={flow} />}

      {/* 共享确认区 */}
      {(confirmReady || confirmSubmitted) && <UploadConfirmPanel flow={flow} />}

      {/* Path B placeholder when not yet ready */}
      {activePath === "b" && !confirmReady && !confirmSubmitted && (
        <section className="upload-section">
          <h3>AI 生成预览</h3>
          <div className="up-preview-placeholder">
            <div className="up-preview-placeholder-title">
              {flowState === "processing" ? "AI 正在提取中…" : "待生成"}
            </div>
            <p>
              {flowState === "processing"
                ? "文件已上传至平台受控存储，worker 正在异步抽取文本并调用外部 LLM 生成建议，请稍候…"
                : "选择文件并启动资产化后，平台将异步抽取文本并由外部 LLM 生成标题、摘要、标签等结构化建议（LLM 不可用时降级为确定性建议）"}
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
