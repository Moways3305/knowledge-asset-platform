import { Link } from "react-router-dom";
import type { NamingFields } from "../../types/ingest";

// 命名规范与保密分级：展示后端 ai-result 的命名解析结果（规范化标题 / 各字段 /
// 保密级别 / AI 调用级别 / 置信度），无结果时给占位说明。
interface UploadNamingCardProps {
  naming: NamingFields | null;
  confirmConfidence: string;
}

export default function UploadNamingCard({ naming, confirmConfidence }: UploadNamingCardProps) {
  return (
    <section className="upload-section">
      <h3>命名规范与保密分级</h3>
      <p className="page-help-line">
        命名格式、保密级别（L1–L5）/ AI 调用级别（A1–A4）与命名异常处理见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
      </p>

      <div className="naming-parse-card">
        <div className="naming-parse-title">当前文件命名解析结果</div>
        {naming ? (
          <>
            <div className="naming-parse-row">
              <span className="naming-parse-label">规范化标题</span>
              <span className="naming-parse-value"><code>{naming.normalized_title}</code></span>
            </div>
            <div className="naming-parse-grid">
              <div className="naming-parse-row">
                <span className="naming-parse-label">原始文件名</span>
                <span className="naming-parse-value"><code>{naming.source_file_name}</code></span>
              </div>
              <div className="naming-parse-row">
                <span className="naming-parse-label">命名状态</span>
                <span className="naming-parse-value">
                  <span className={`naming-status-badge ${naming.original_naming_compliant ? "naming-status-compliant" : "naming-status-anomaly"}`}>
                    {naming.original_naming_compliant ? "原文件名合规" : "原文件名命名异常（已自动规范化）"}
                  </span>
                </span>
              </div>
              {([
                ["primary_category", "一级类", naming.primary_category],
                ["secondary_category", "二级类", naming.secondary_category],
                ["topic", "主题", naming.topic],
                ["subject_or_client", "对象/客户", naming.subject_or_client],
                ["date", "日期", naming.date],
                ["version", "版本号", naming.version],
              ] as const).map(([key, label, value]) => (
                <div className="naming-parse-row" key={key}>
                  <span className="naming-parse-label">{label}</span>
                  <span className="naming-parse-value">
                    {value}
                    {naming.missing_fields.includes(key) ? (
                      <span className="naming-field-flag naming-field-todo">待人工校正</span>
                    ) : naming.inferred_fields.includes(key) ? (
                      <span className="naming-field-flag naming-field-inferred">AI 推断</span>
                    ) : null}
                  </span>
                </div>
              ))}
              <div className="naming-parse-row">
                <span className="naming-parse-label">保密级别</span>
                <span className="naming-parse-value"><span className={`confidentiality-badge confidentiality-${naming.confidentiality_level}`}>{naming.confidentiality_level}</span></span>
              </div>
              <div className="naming-parse-row">
                <span className="naming-parse-label">AI 调用级别</span>
                <span className="naming-parse-value"><span className={`ai-access-badge ai-access-${naming.ai_access_level}`}>{naming.ai_access_level}</span></span>
              </div>
              <div className="naming-parse-row">
                <span className="naming-parse-label">置信度</span>
                <span className="naming-parse-value">{confirmConfidence}</span>
              </div>
            </div>
            <div className="naming-parse-note">
              规范化标题由 AI 根据文件名 + 抽取正文 + 平台命名规范生成；标「AI 推断」为模型/默认推断字段，标「待人工校正」为缺乏依据的字段，请在下方人工校正区核对后提交。AI 调用级别由保密级别推导。
            </div>
          </>
        ) : (
          <div className="naming-parse-note">
            选择文件并启动资产化后，平台将异步抽取正文并由 AI 生成规范化命名解析结果（一级类 / 二级类 / 主题 / 对象/客户 / 日期 / 版本 / 保密级别 / AI 调用级别）。字段待后端返回。
          </div>
        )}
      </div>
    </section>
  );
}
