import { fetchAgentCall, fetchAgentDecisions } from "../../api/agentCalls";
import { Link } from "react-router-dom";
import { fetchAlertNotifications } from "../../api/admin";
import { fetchAuditTrace, fetchOpsSummary } from "../../api/admin";
import { fetchKnowledgeOpsInsights } from "../../api/knowledge";
import { formatBeijingTime } from "../../utils/time";
import { auditActionLabel } from "../../utils/auditDisplay";
import { OperationPanel, ReadResult } from "./OperationPanel";

export function AlertHistoryButton() {
  return (
    <OperationPanel label="告警通知记录">
      <ReadResult load={() => fetchAlertNotifications()}>
        {(data) => (
          <>
            <p>查看告警发送结果。阅读记录不会改变告警处理状态。</p>
            {data.items.length === 0 && <p>暂无告警通知记录。</p>}
            {data.items.map((item) => (
              <article className="operation-card" key={item.id}>
                <strong>{item.title}</strong>
                <p>{item.content}</p>
                <small>
                  {item.recipient_name || "接收人不可见"} ·{" "}
                  {item.channel === "wecom"
                    ? "企业微信"
                    : item.channel === "in_app"
                      ? "站内通知"
                      : item.channel}{" "}
                  ·{" "}
                  {(
                    {
                      pending: "待发送",
                      sent: "已发送",
                      failed: "发送失败",
                      skipped: "已跳过",
                    } as Record<string, string>
                  )[item.send_status] ?? item.send_status}
                </small>
                <time>{formatBeijingTime(item.sent_at ?? item.created_at)}</time>
              </article>
            ))}
          </>
        )}
      </ReadResult>
    </OperationPanel>
  );
}

export function AuditTraceButton({ traceId }: { traceId: string }) {
  return (
    <OperationPanel label="关联审计">
      <ReadResult load={() => fetchAuditTrace(traceId)}>
        {(data) => (
          <>
            <p>同一操作链中的历史记录，仅展示当前身份获准查看的内容。</p>
            {!data.items.length && <p>没有可见的关联记录。</p>}
            {data.items.map((item) => (
              <article className="operation-card" key={item.id}>
                <strong>{auditActionLabel(item.action)}</strong>
                <small>
                  {formatBeijingTime(item.created_at)} · {item.actor_name || "操作人不可见"}
                </small>
                {item.denied_reason && <p>{item.denied_reason}</p>}
              </article>
            ))}
          </>
        )}
      </ReadResult>
    </OperationPanel>
  );
}

export function AgentCallButton({ callId }: { callId: string }) {
  return (
    <OperationPanel label="问答记录与引用权限">
      <ReadResult load={() => fetchAgentCall(callId)}>
        {(data) => (
          <>
            <small>
              {data.project_name} · {data.caller_name} · {formatBeijingTime(data.created_at)}
            </small>
            <article className="operation-card">
              <strong>问题</strong>
              <p>{data.query_text}</p>
              <strong>回答</strong>
              <p>{data.response_text || "本次未生成回答。"}</p>
              {data.denied_reason && <p>{data.denied_reason}</p>}
            </article>
            <h3>引用资料</h3>
            {!data.citations.length && <p>本次没有引用资料。</p>}
            {data.citations.map((citation, index) => (
              <article key={`${citation.asset_id}-${index}`} className="operation-card">
                <Link to={`/knowledge/${citation.asset_id}`}>
                  {citation.asset_title || "查看资料"}
                </Link>
                {citation.snippet && <p>{citation.snippet}</p>}
              </article>
            ))}
            <details>
              <summary>查看引用权限判断</summary>
              <ReadResult load={() => fetchAgentDecisions(callId)}>
                {(decisions) => (
                  <>
                    {!decisions.items.length && <p>没有可见的权限判断记录。</p>}
                    {decisions.items.map((item, index) => (
                      <article key={`${item.target_asset_id}-${index}`} className="operation-card">
                        <strong>候选资料 {index + 1}</strong>
                        <p>
                          发现：{item.discovery_allowed ? "允许" : "不允许"} · 摘要：
                          {item.summary_allowed ? "允许" : "不允许"} · 原文：
                          {item.original_allowed ? "允许" : "不允许"}
                        </p>
                        {item.denied_reason && <p>{item.denied_reason}</p>}
                        {item.discovery_allowed && (
                          <Link to={`/knowledge/${item.target_asset_id}`}>查看资料</Link>
                        )}
                      </article>
                    ))}
                  </>
                )}
              </ReadResult>
            </details>
          </>
        )}
      </ReadResult>
    </OperationPanel>
  );
}

export function OpsSummaryButton() {
  return (
    <OperationPanel label="系统运行概况">
      <ReadResult load={() => fetchOpsSummary()}>
        {(data) => (
          <dl className="operation-facts">
            {[
              ["运行版本", data.version],
              ["数据库", data.db_ready ? "就绪" : "未就绪"],
              ["缓存", data.redis_ready ? "就绪" : "未就绪"],
              ["处理中", data.ingest.processing],
              ["待确认", data.ingest.pending_confirmation],
              ["处理失败", data.ingest.failed],
              ["已完成", data.ingest.completed],
              ["企微待发送", data.notifications.pending_wecom],
              ["未处理异常", data.audit.unprocessed_exceptions],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </ReadResult>
    </OperationPanel>
  );
}

export function KnowledgeInsightsButton() {
  return (
    <OperationPanel label="知识运行概况">
      <ReadResult load={() => fetchKnowledgeOpsInsights()}>
        {(data) => (
          <>
            <p>最近 {data.window_days} 天，按当前身份可见范围汇总。</p>
            <dl className="operation-facts">
              {[
                ["索引失败", data.indexing.index_failed],
                ["等待解析", data.indexing.parse_pending],
                ["解析中", data.indexing.parse_processing],
                ["解析失败", data.indexing.parse_failed],
                ["待审批原文申请", data.access.pending_original_requests],
                ["超时原文申请", data.access.overdue_original_requests],
                ["待更新资料", data.lifecycle.needs_update],
                ["归档候选", data.lifecycle.archive_candidates],
              ].map(([label, count]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{count}</dd>
                </div>
              ))}
            </dl>
            <dl className="operation-facts">
              {data.cards.map((card) => (
                <div key={`${card.key}-${card.project_id ?? card.scope}`}>
                  <dt>
                    {card.label}
                    {card.context_label ? ` · ${card.context_label}` : ""}
                  </dt>
                  <dd>{card.count}</dd>
                  {card.action_hint && <small>{card.action_hint}</small>}
                </div>
              ))}
            </dl>
            {data.recommendations.map((item) => (
              <p key={item.key}>{item.message}</p>
            ))}
            {data.recent_items.map((item) => (
              <article className="operation-card" key={item.asset_id}>
                {data.title_visible && item.title ? (
                  <Link to={`/knowledge/${item.asset_id}`}>{item.title}</Link>
                ) : (
                  <strong>资料运行记录</strong>
                )}
                <p>{item.message || "暂无补充说明"}</p>
                <small>{formatBeijingTime(item.updated_at)}</small>
              </article>
            ))}
          </>
        )}
      </ReadResult>
    </OperationPanel>
  );
}
