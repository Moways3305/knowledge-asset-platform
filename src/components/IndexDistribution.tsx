import type { OpsIndexingCountsDTO } from "../types/ops";

interface IndexDistributionProps {
  counts: OpsIndexingCountsDTO;
  className?: string;
}

export default function IndexDistribution({
  counts,
  className = "ao84-index-grid",
}: IndexDistributionProps) {
  const metrics = [
    { label: "索引失败", value: counts.index_failed, tone: "danger" },
    { label: "索引处理中", value: counts.indexing, tone: "blue" },
    { label: "未索引", value: counts.not_indexed, tone: "gold" },
    { label: "已跳过", value: counts.skipped, tone: "neutral" },
    { label: "解析处理中", value: counts.parse_pending + counts.parse_processing, tone: "violet" },
    { label: "知识库初始化失败", value: counts.kb_init_failed, tone: "danger" },
  ];

  return (
    <div className={className} aria-label="索引状态分布">
      {metrics.map((metric) => (
        <div key={metric.label} className={`ao84-index-metric is-${metric.tone}`}>
          <strong>{metric.value}</strong>
          <span>{metric.label}</span>
        </div>
      ))}
    </div>
  );
}
