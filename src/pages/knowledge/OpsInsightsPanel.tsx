import { Link } from "react-router-dom";
import { Radar } from "lucide-react";
import type { KnowledgeOpsInsightsDTO } from "../../types/insights";

// 右侧运营洞察面板。真实后端安全聚合；颜色按 severity 派生，仅 UI 渲染，
// 非业务事实来源。纯 admin 视图标题隐藏由后端 title_visible 控制。
interface OpsInsightsPanelProps {
  insights: KnowledgeOpsInsightsDTO | null;
  insightsErr: boolean;
}

export default function OpsInsightsPanel({ insights, insightsErr }: OpsInsightsPanelProps) {
  return (
    <aside className="intel">
      <h4 className="intel-title">
        <Radar size={13} /> 运营洞察
      </h4>
      {insightsErr ? (
        <p className="intel-note">
          运营洞察加载失败（请确认后端已启动）。知识可见性与权限说明见{" "}
          <Link to="/help#knowledge" className="page-help-link">
            使用说明 →
          </Link>
        </p>
      ) : !insights ? (
        <p className="intel-note">加载运营洞察中…</p>
      ) : (
        <>
          {insights.cards.length === 0 && insights.recommendations.length === 0 ? (
            <p className="intel-note">暂无需要处理的运营项。</p>
          ) : (
            <>
              {insights.cards.length > 0 && (
                <div className="intel-cards">
                  {insights.cards.map((c) => (
                    <div key={c.key} className={`intel-card sev-${c.severity}`}>
                      <span className="intel-count">{c.count}</span>
                      <span className="intel-label">{c.label}</span>
                      {c.action_hint && <span className="intel-hint">{c.action_hint}</span>}
                    </div>
                  ))}
                </div>
              )}
              {insights.recommendations.length > 0 && (
                <ul className="intel-recos">
                  {insights.recommendations.map((r) => (
                    <li key={r.key} className={`intel-reco sev-${r.severity}`}>
                      {r.target ? <Link to={r.target}>{r.message}</Link> : <span>{r.message}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {insights.recent_items.length > 0 && (
            <div className="intel-block">
              <div className="intel-block-title">最近索引失败</div>
              <ul>
                {insights.recent_items.map((it) => (
                  <li key={it.asset_id} className="intel-item">
                    {insights.title_visible && it.title ? (
                      <Link to={`/knowledge/${it.asset_id}`}>{it.title}</Link>
                    ) : (
                      <span className="intel-hidden">（业务标题已隐藏）</span>
                    )}
                    {it.message && <span className="intel-item-msg">{it.message}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {insights.indexing.recent_jobs.length > 0 && (
            <div className="intel-block">
              <div className="intel-block-title">最近运维作业</div>
              <ul>
                {insights.indexing.recent_jobs.map((j) => (
                  <li key={j.job_id} className="intel-item">
                    <span>
                      {j.operation_type === "reparse" ? "重新解析" : "批量重试"} · {j.status}
                    </span>
                    <span className="intel-item-msg">
                      共 {j.total_count} / 成 {j.success_count} / 败 {j.failed_count}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="intel-foot">
            统计基于近 {insights.window_days} 天平台记录
            {!insights.title_visible && "·系统运维视图（业务标题隐藏）"}。说明见{" "}
            <Link to="/help#knowledge" className="page-help-link">
              使用说明 →
            </Link>
          </p>
        </>
      )}
    </aside>
  );
}
