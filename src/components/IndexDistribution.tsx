import type { OpsIndexingCountsDTO } from "../types/ops";

// 知识底座索引状态分布：把 OpsIndexing 的安全计数渲染成现有 `.kl-kpi` 计数块串，
// 与 AdminIngestPage 手写的索引运维 KPI 行视觉一致。纯展示，仅安全计数，不含任何
// 业务原文 / 标题 / 内部 id。
interface IndexDistributionProps {
  counts: OpsIndexingCountsDTO;
  className?: string;
}

export default function IndexDistribution({ counts, className = "kl-kpis" }: IndexDistributionProps) {
  return (
    <div className={className}>
      <div className="kl-kpi"><div className="kl-kpi-value kl-kpi-warning">{counts.index_failed}</div><div className="kl-kpi-label">索引失败</div></div>
      <div className="kl-kpi"><div className="kl-kpi-value">{counts.indexing}</div><div className="kl-kpi-label">索引中</div></div>
      <div className="kl-kpi"><div className="kl-kpi-value">{counts.not_indexed}</div><div className="kl-kpi-label">待索引</div></div>
      <div className="kl-kpi"><div className="kl-kpi-value">{counts.skipped}</div><div className="kl-kpi-label">已跳过</div></div>
      <div className="kl-kpi"><div className="kl-kpi-value">{counts.parse_pending + counts.parse_processing}</div><div className="kl-kpi-label">解析滞留</div></div>
      <div className="kl-kpi"><div className="kl-kpi-value kl-kpi-warning">{counts.kb_init_failed}</div><div className="kl-kpi-label">KB 初始化失败</div></div>
    </div>
  );
}
