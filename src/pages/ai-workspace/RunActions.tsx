import { Check, Circle, Clock3, ShieldCheck, X } from "lucide-react";
import type { WorkspaceAction, WorkspacePendingAction } from "../../api/aiWorkspace";
import { Link, useSearchParams } from "react-router-dom";
import { MAINTENANCE_AGENT_PATH } from "../../navigation/agentRoutes";

const labels: Record<WorkspaceAction["status"], string> = {
  planned: "准备执行",
  awaiting_confirmation: "等待确认",
  approved: "已确认",
  completed: "已执行",
  rejected: "已拒绝",
  waiting: "等待结果",
};

const fieldLabels: Record<string, string> = {
  title: "资料",
  problem: "问题",
  message: "说明",
  recommendation: "处理建议",
  target_count: "目标资料",
  completed_count: "已检查",
  incomplete_count: "未完成",
  skipped_count: "已跳过",
  active_issues: "未解决问题",
  total: "总数",
  version_label: "资料版本",
  version_no: "资料版本",
  coverage_complete: "完整覆盖",
  current_version_matches: "与当前版本一致",
  evidence_available: "证据可用",
  source_modified: "已修改原文",
  requires_recheck: "需要复检",
  suspected: "需人工核实",
  finished: "检查结束",
  start: "起始位置",
  end: "结束位置",
  similarity: "相似度",
  source: "所在位置",
  category: "类别",
  basis: "检查依据",
  raw_values_included: "包含敏感原值",
  locations_truncated: "位置明细有省略",
  mode: "检查方式",
  library_name: "知识库",
  asset_title: "资料",
  impact: "影响范围",
};
const valueLabels: Record<string, string> = {
  company: "公司知识库",
  full: "全面巡检",
  incremental: "增量巡检",
  body: "正文",
  summary: "摘要",
  title: "标题",
  tag: "标签",
  local_personal_information_check: "个人信息检查",
  sha256_equal: "文件内容完全一致",
  title_similarity: "标题相似",
  phone: "电话",
  mobile: "手机号码",
  email: "邮箱",
  id_card: "身份证号",
  bank_card: "银行卡号",
  address: "地址",
  name: "姓名",
  personal_name: "姓名",
  passport: "护照",
  account: "账户",
  identity: "身份信息",
  contact: "联系方式",
  personal_information: "个人信息",
  integrity: "信息完整性",
  availability: "可用性",
  maintenance: "维护状态",
  duplicates: "重复与版本关系",
  quality: "内容质量",
  privacy: "敏感个人信息",
  active: "待处理",
  acknowledged: "处理中",
  resolved: "复检通过",
  false_positive: "已确认误报",
  snoozed: "暂缓处理",
  not_applicable: "不适用",
  running: "进行中",
  queued: "等待开始",
  completed: "已完成",
  failed: "未完成",
  waiting: "等待结果",
  not_executed: "未执行",
  error: "未能执行",
};
const objectValue = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === "object" && !Array.isArray(value));

/** Only business facts are rendered; identifiers, raw tool arguments and unknown payloads stay out of the UI. */
function Evidence({ value, depth = 0 }: { value: Record<string, unknown>; depth?: number }) {
  const [params] = useSearchParams();
  const rows = Object.entries(value).filter(
    ([key, item]) => fieldLabels[key] && ["string", "number", "boolean"].includes(typeof item),
  );
  const items = Array.isArray(value.items) ? value.items.filter(objectValue) : [];
  const locations = Array.isArray(value.locations) ? value.locations.filter(objectValue) : [];
  const counts = objectValue(value.counts)
    ? Object.entries(value.counts).filter(
        ([key, count]) => valueLabels[key] && typeof count === "number",
      )
    : [];
  let href: string | undefined;
  if (typeof value.url === "string" && value.url.startsWith(`${MAINTENANCE_AGENT_PATH}?`)) {
    const url = new URL(value.url, window.location.origin);
    if (url.origin === window.location.origin && url.pathname === MAINTENANCE_AGENT_PATH) {
      if (params.get("session")) url.searchParams.set("session", params.get("session")!);
      href = `${url.pathname}${url.search}`;
    }
  }
  const status = typeof value.status === "string" ? valueLabels[value.status] : undefined;
  return (
    <div className="aw-evidence-facts">
      {(rows.length > 0 || status || counts.length > 0) && (
        <dl>
          {status && (
            <div>
              <dt>状态</dt>
              <dd>{status}</dd>
            </div>
          )}
          {rows.map(([key, item]) => (
            <div key={key}>
              <dt>{fieldLabels[key]}</dt>
              <dd>
                {typeof item === "boolean"
                  ? item
                    ? "是"
                    : "否"
                  : (valueLabels[String(item)] ?? String(item))}
              </dd>
            </div>
          ))}
          {counts.map(([key, count]) => (
            <div key={key}>
              <dt>{valueLabels[key]}</dt>
              <dd>{String(count)} 处</dd>
            </div>
          ))}
        </dl>
      )}
      {depth < 3 && objectValue(value.evidence) && (
        <Evidence value={value.evidence} depth={depth + 1} />
      )}
      {depth < 3 && objectValue(value.scope) && <Evidence value={value.scope} depth={depth + 1} />}
      {depth < 3 && [...items, ...locations].length > 0 && (
        <ul>
          {[...items, ...locations].map((item, index) => (
            <li key={index}>
              <Evidence value={item} depth={depth + 1} />
            </li>
          ))}
        </ul>
      )}
      {value.has_more === true && <p>还有更多结果，可继续让 Agent 查看。</p>}
      {href && <Link to={href}>查看对应维护问题</Link>}
      {!rows.length &&
        !status &&
        !counts.length &&
        !items.length &&
        !locations.length &&
        !objectValue(value.evidence) &&
        !objectValue(value.scope) &&
        !href && <p>执行结果已保存，可继续询问 Agent 或查看生成的报告。</p>}
    </div>
  );
}

export function ToolReceipts({ actions }: { actions: WorkspaceAction[] }) {
  if (!actions.length) return null;
  return (
    <ol className="aw-tool-receipts" aria-label="工具执行回执">
      {actions.map((action) => {
        const hasError =
          typeof action.observation.error === "string"
            ? Boolean(action.observation.error.trim())
            : Boolean(action.observation.error);
        const notExecuted =
          hasError ||
          ["not_executed", "error", "failed"].includes(String(action.observation.status));
        const summary =
          typeof action.observation.receipt_summary === "string"
            ? action.observation.receipt_summary
            : typeof action.observation.message === "string"
              ? action.observation.message
              : action.summary;
        return (
          <li key={action.id}>
            {notExecuted ? (
              <X />
            ) : action.status === "completed" ? (
              <Check />
            ) : action.status === "rejected" ? (
              <X />
            ) : action.status === "waiting" ? (
              <Clock3 />
            ) : (
              <Circle />
            )}
            <div>
              <div className="aw-receipt-heading">
                <strong>{action.label}</strong>
                <span>
                  {hasError
                    ? "未能执行"
                    : notExecuted
                      ? valueLabels[String(action.observation.status)]
                      : labels[action.status]}
                </span>
              </div>
              {summary && <p>{summary}</p>}
              {Object.keys(action.observation).length > 0 && (
                <details className="aw-receipt-evidence">
                  <summary>查看执行依据与结果</summary>
                  <Evidence value={action.observation} />
                </details>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function ActionConfirmation({
  action,
  busy,
  onDecision,
}: {
  action: WorkspacePendingAction;
  busy: boolean;
  onDecision: (decision: "approve" | "reject") => void;
}) {
  return (
    <section className="aw-action-confirmation" aria-label="确认本次操作">
      <div className="aw-confirmation-title">
        <ShieldCheck />
        <strong>{action.label}</strong>
        <span>需要你确认</span>
      </div>
      <p>{action.summary}</p>
      {Object.keys(action.arguments).some((key) => fieldLabels[key]) && (
        <details className="aw-receipt-evidence">
          <summary>核对本次操作的具体内容</summary>
          <Evidence value={action.arguments} />
        </details>
      )}
      <div className="aw-confirmation-buttons">
        <button type="button" disabled={busy} onClick={() => onDecision("approve")}>
          确认执行
        </button>
        <button type="button" disabled={busy} onClick={() => onDecision("reject")}>
          拒绝本次操作
        </button>
      </div>
      <small>确认仅适用于上面这项操作。拒绝后，Agent 会根据结果继续调整。</small>
    </section>
  );
}
