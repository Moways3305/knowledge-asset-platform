import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  Cpu,
  Inbox,
  RefreshCw,
  ScanLine,
  ScrollText,
  ShieldAlert,
  Users,
} from "lucide-react";
import {
  fetchAudit,
  fetchOpsIndexing,
  fetchWecomScanConfigs,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
} from "../api/admin";
import { fetchAdminIngest } from "../api/ingest";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import { EmptyState, PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type { AuditListResponseDTO } from "../types/audit";
import type { AdminIngestListResponseDTO } from "../types/ingest";
import type { OpsIndexingDTO } from "../types/ops";
import type { WecomScanConfigsResponseDTO } from "../types/wecom";
import type { KbConfigDTO, ModelDTO } from "../types/weknoraAdmin";
import { auditActionLabel, auditTargetTypeLabel } from "../utils/auditDisplay";
import { formatBeijingTime } from "../utils/time";
import { ADMIN_OVERVIEW_INVALIDATED_EVENT } from "../admin/adminOverviewEvents";
import "./AdminOverviewPage.css";

interface AdminSnapshot {
  ingest?: AdminIngestListResponseDTO;
  indexing?: OpsIndexingDTO;
  scans?: WecomScanConfigsResponseDTO;
  models?: ModelDTO[];
  kbConfigs?: KbConfigDTO[];
  audit?: AuditListResponseDTO;
}

type SnapshotKey = keyof AdminSnapshot;
type AttentionTone = "danger" | "warning";

interface AttentionItem {
  key: string;
  label: string;
  detail: string;
  count: number;
  route: string;
  tone: AttentionTone;
}

interface RuntimeItem {
  key: string;
  label: string;
  detail: string;
  route: string;
  tone: "success" | "warning" | "danger" | "neutral";
  status: string;
  icon: ReactNode;
}

const GOVERNANCE_ACTION_PREFIXES = ["config.", "project.member_", "naming.", "directory."];

function isGovernanceChange(action: string): boolean {
  return GOVERNANCE_ACTION_PREFIXES.some((prefix) => action.startsWith(prefix));
}

export default function AdminOverviewPage() {
  const { capabilities } = useAuth();
  const [snapshot, setSnapshot] = useState<AdminSnapshot>({});
  const [failedSources, setFailedSources] = useState<SnapshotKey[]>([]);
  const [loading, setLoading] = useState(true);
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    const tasks: Array<{ key: SnapshotKey; request: Promise<Partial<AdminSnapshot>> }> = [];

    if (can.viewIngestAdmin(capabilities)) {
      tasks.push({ key: "ingest", request: fetchAdminIngest().then((ingest) => ({ ingest })) });
      tasks.push({
        key: "indexing",
        request: fetchOpsIndexing().then((indexing) => ({ indexing })),
      });
    }
    if (can.viewWecomScan(capabilities)) {
      tasks.push({
        key: "scans",
        request: fetchWecomScanConfigs().then((scans) => ({ scans })),
      });
    }
    if (can.viewModels(capabilities)) {
      tasks.push({
        key: "models",
        request: fetchWeknoraModels().then((models) => ({ models })),
      });
      tasks.push({
        key: "kbConfigs",
        request: fetchWeknoraKbConfigs().then((kbConfigs) => ({ kbConfigs })),
      });
    }
    if (can.viewAudit(capabilities)) {
      tasks.push({
        key: "audit",
        request: fetchAudit({ pageSize: 80 }).then((audit) => ({ audit })),
      });
    }

    const results = await Promise.allSettled(tasks.map((task) => task.request));
    if (requestId !== requestRef.current) return;

    const next: AdminSnapshot = {};
    const failed: SnapshotKey[] = [];
    results.forEach((result, index) => {
      if (result.status === "fulfilled") Object.assign(next, result.value);
      else failed.push(tasks[index].key);
    });
    setSnapshot(next);
    setFailedSources(failed);
    setLoading(false);
  }, [capabilities]);

  useEffect(() => {
    void load();
    const onInvalidated = () => void load();
    window.addEventListener(ADMIN_OVERVIEW_INVALIDATED_EVENT, onInvalidated);
    return () => {
      requestRef.current += 1;
      window.removeEventListener(ADMIN_OVERVIEW_INVALIDATED_EVENT, onInvalidated);
    };
  }, [load]);

  const attentionItems = useMemo<AttentionItem[]>(() => {
    const items: AttentionItem[] = [];
    const failedIngest =
      snapshot.ingest?.items.filter((item) => item.status === "failed").length ?? 0;
    const incompleteSuggestions =
      snapshot.ingest?.items.filter(
        (item) => item.status !== "failed" && item.suggestion_generation_status !== "generated",
      ).length ?? 0;
    if (failedIngest > 0)
      items.push({
        key: "ingest-failed",
        label: "入库失败",
        detail: "查看安全错误原因并进入入库工作区恢复。",
        count: failedIngest,
        route: "/admin/ingest",
        tone: "danger",
      });
    if (incompleteSuggestions > 0)
      items.push({
        key: "ingest-review",
        label: "入库建议待补全",
        detail: "内容建议缺项，需要业务确认后才能继续。",
        count: incompleteSuggestions,
        route: "/admin/ingest",
        tone: "warning",
      });

    const indexFailures = snapshot.indexing
      ? snapshot.indexing.counts.index_failed +
        snapshot.indexing.counts.parse_failed +
        snapshot.indexing.counts.kb_init_failed
      : 0;
    if (indexFailures > 0)
      items.push({
        key: "index-failed",
        label: "索引或知识库连接失败",
        detail: "先核查配置与影响范围，再执行定向恢复。",
        count: indexFailures,
        route: "/admin/ingest",
        tone: "danger",
      });
    const stalled = snapshot.indexing?.counts.parse_stalled ?? 0;
    if (stalled > 0)
      items.push({
        key: "parse-stalled",
        label: "解析处理超时",
        detail: "任务已超过安全等待窗口，需要确认执行状态。",
        count: stalled,
        route: "/admin/ingest",
        tone: "warning",
      });

    const scanIssues =
      snapshot.scans?.items.filter(
        (item) =>
          item.enabled &&
          (item.scan_space_status !== "ready" || item.manager_access_status !== "ready"),
      ).length ?? 0;
    if (scanIssues > 0)
      items.push({
        key: "scan-unavailable",
        label: "微盘扫描不可用",
        detail: "扫描空间或管理身份需要修复。",
        count: scanIssues,
        route: "/admin/wecom-scan",
        tone: "warning",
      });

    const missingCredentials =
      snapshot.models?.filter((model) => model.enabled && model.credential_status === "missing")
        .length ?? 0;
    if (missingCredentials > 0)
      items.push({
        key: "model-credential",
        label: "模型凭据缺失",
        detail: "已启用模型尚不能提供服务。",
        count: missingCredentials,
        route: "/admin/weknora-models",
        tone: "danger",
      });

    const recentAuditIssues =
      snapshot.audit?.items.filter((event) => event.log_type === "exception" && !event.is_processed)
        .length ?? 0;
    if (recentAuditIssues > 0)
      items.push({
        key: "audit-unprocessed",
        label: "近期异常待核查",
        detail: "进入审计日志确认影响并记录处置结果。",
        count: recentAuditIssues,
        route: "/admin/audit",
        tone: "warning",
      });

    return items.sort((left, right) => {
      if (left.tone !== right.tone) return left.tone === "danger" ? -1 : 1;
      return right.count - left.count;
    });
  }, [snapshot]);

  const runtimeItems = useMemo<RuntimeItem[]>(() => {
    const items: RuntimeItem[] = [];
    if (snapshot.ingest) {
      const failures = snapshot.ingest.items.filter((item) => item.status === "failed").length;
      items.push({
        key: "ingest",
        label: "入库处理",
        detail: failures > 0 ? `${failures} 项失败需要恢复` : "当前未发现入库失败",
        route: "/admin/ingest",
        tone: failures > 0 ? "danger" : "success",
        status: failures > 0 ? "需处理" : "可用",
        icon: <Inbox size={18} />,
      });
    }
    if (snapshot.indexing) {
      const failures =
        snapshot.indexing.counts.index_failed +
        snapshot.indexing.counts.parse_failed +
        snapshot.indexing.counts.kb_init_failed;
      const processing =
        snapshot.indexing.counts.indexing + snapshot.indexing.counts.parse_processing;
      items.push({
        key: "indexing",
        label: "解析与索引",
        detail:
          failures > 0
            ? `${failures} 项失败，${processing} 项处理中`
            : processing > 0
              ? `${processing} 项正在处理`
              : "当前未发现失败或积压",
        route: "/admin/ingest",
        tone: failures > 0 ? "danger" : processing > 0 ? "warning" : "success",
        status: failures > 0 ? "需处理" : processing > 0 ? "处理中" : "可用",
        icon: <Activity size={18} />,
      });
    }
    if (snapshot.scans) {
      const enabled = snapshot.scans.items.filter((item) => item.enabled);
      const unavailable = enabled.filter(
        (item) => item.scan_space_status !== "ready" || item.manager_access_status !== "ready",
      ).length;
      items.push({
        key: "scan",
        label: "微盘扫描",
        detail:
          unavailable > 0
            ? `${unavailable} 个启用配置不可用`
            : enabled.length > 0
              ? `${enabled.length} 个配置可执行扫描`
              : "当前没有启用的扫描配置",
        route: "/admin/wecom-scan",
        tone: unavailable > 0 ? "warning" : enabled.length > 0 ? "success" : "neutral",
        status: unavailable > 0 ? "需修复" : enabled.length > 0 ? "可用" : "未启用",
        icon: <ScanLine size={18} />,
      });
    }
    if (snapshot.models || snapshot.kbConfigs) {
      const missing =
        snapshot.models?.filter((model) => model.enabled && model.credential_status === "missing")
          .length ?? 0;
      const kbFailures =
        snapshot.kbConfigs?.filter(
          (config) =>
            config.mapping_status === "init_failed" || (config.migration?.failed_count ?? 0) > 0,
        ).length ?? 0;
      items.push({
        key: "models",
        label: "模型与知识库连接",
        detail:
          missing + kbFailures > 0
            ? `${missing} 个模型缺少凭据，${kbFailures} 个知识库连接异常`
            : "当前模型凭据与知识库连接未发现异常",
        route: "/admin/weknora-models",
        tone: missing + kbFailures > 0 ? "danger" : "success",
        status: missing + kbFailures > 0 ? "需修复" : "可用",
        icon: <Cpu size={18} />,
      });
    }
    return items;
  }, [snapshot]);

  const governanceEvents = useMemo(
    () =>
      (snapshot.audit?.items ?? []).filter((event) => isGovernanceChange(event.action)).slice(0, 5),
    [snapshot.audit],
  );

  const quickLinks = [
    can.viewIngestAdmin(capabilities) && {
      route: "/admin/ingest",
      label: "处理入库与索引",
      description: "恢复失败任务并确认最终状态",
      icon: <Inbox size={18} />,
    },
    can.viewModels(capabilities) && {
      route: "/admin/weknora-models",
      label: "维护模型连接",
      description: "核查凭据、默认模型与知识库迁移",
      icon: <Cpu size={18} />,
    },
    can.viewAudit(capabilities) && {
      route: "/admin/audit",
      label: "核查审计风险",
      description: "定位异常并记录处置结果",
      icon: <ScrollText size={18} />,
    },
    can.viewPeople(capabilities) && {
      route: "/admin/people",
      label: "维护人员权限",
      description: "调整角色、项目成员关系与账号状态",
      icon: <Users size={18} />,
    },
  ].filter(Boolean) as Array<{
    route: string;
    label: string;
    description: string;
    icon: ReactNode;
  }>;

  return (
    <ProductPage className="admin-overview-page">
      <PageHeader
        eyebrow="管理后台"
        title="运营中枢"
        description="先识别需要处理的风险，再进入对应工作区完成治理并确认恢复。"
        scope="仅汇总当前身份已获授权的管理工作区"
        status={
          <StatusBadge
            label={
              loading ? "正在读取" : failedSources.length > 0 ? "部分状态不可用" : "状态已更新"
            }
            tone={loading ? "info" : failedSources.length > 0 ? "warning" : "success"}
          />
        }
        actions={
          <button
            type="button"
            className="btn-primary"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={15} className={loading ? "is-spinning" : ""} aria-hidden="true" />
            {loading ? "读取中" : "刷新运行状态"}
          </button>
        }
      />

      {failedSources.length > 0 && (
        <div className="admin-overview-notice" role="status">
          部分工作区暂时无法读取；已显示的状态均来自成功返回的数据，可进入对应页面重试。
        </div>
      )}

      <div className="admin-overview-grid">
        <PageSection
          title="需要处理"
          description="只显示失败、超时、配置缺失或待确认等可行动事项，并按风险排序。"
          className="admin-overview-attention"
        >
          {loading && Object.keys(snapshot).length === 0 ? (
            <div className="admin-overview-loading">正在读取已授权工作区…</div>
          ) : attentionItems.length > 0 ? (
            <div className="admin-attention-list">
              {attentionItems.map((item) => (
                <Link
                  key={item.key}
                  to={item.route}
                  className={`admin-attention-item is-${item.tone}`}
                >
                  <span className="admin-attention-count">{item.count}</span>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.detail}</small>
                  </span>
                  <ArrowRight size={17} aria-hidden="true" />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<BookOpenCheck size={21} />}
              title="当前没有需要管理员处理的事项"
              description="继续查看系统运行状态，确认关键连接保持可用。"
              action={<a href="#system-runtime">查看运行状态</a>}
            />
          )}
        </PageSection>

        <PageSection
          title="系统运行"
          description="来自入库、索引、扫描、模型与知识库连接的实时读取结果。"
          className="admin-overview-runtime"
        >
          <div className="admin-runtime-list" id="system-runtime">
            {runtimeItems.map((item) => (
              <Link key={item.key} to={item.route} className="admin-runtime-item">
                <span className="admin-runtime-icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="admin-runtime-copy">
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </span>
                <StatusBadge label={item.status} tone={item.tone} />
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            ))}
            {!loading && runtimeItems.length === 0 && (
              <EmptyState
                icon={<ShieldAlert size={21} />}
                title="运行状态暂不可用"
                description="当前身份没有可读取的运行工作区，或状态请求暂时失败。"
              />
            )}
          </div>
        </PageSection>

        <PageSection
          title="治理变更"
          description="最近的规则、权限、目录与人员变更；详细历史仍在审计日志中。"
          className="admin-overview-governance"
          actions={
            can.viewAudit(capabilities) ? (
              <Link to="/admin/audit">查看全部审计记录</Link>
            ) : undefined
          }
        >
          {governanceEvents.length > 0 ? (
            <div className="admin-change-list">
              {governanceEvents.map((event) => (
                <Link key={event.id} to="/admin/audit" className="admin-change-item">
                  <span>
                    <strong>{auditActionLabel(event.action)}</strong>
                    <small>
                      {auditTargetTypeLabel(event.target_type)} · {event.actor_name ?? "系统操作"} ·{" "}
                      {formatBeijingTime(event.created_at)}
                    </small>
                  </span>
                  <StatusBadge
                    label={event.log_type === "exception" ? "需核查" : "已完成"}
                    tone={event.log_type === "exception" ? "warning" : "success"}
                  />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              title="近期没有可展示的治理变更"
              description="变更历史不会在此重复铺开，可前往审计日志按条件查看。"
            />
          )}
        </PageSection>

        <PageSection
          title="快捷进入"
          description="仅保留当前身份最常用的管理工作区。"
          className="admin-overview-quick"
        >
          <div className="admin-quick-list">
            {quickLinks.map((item) => (
              <Link key={item.route} to={item.route} className="admin-quick-item">
                <span aria-hidden="true">{item.icon}</span>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            ))}
          </div>
        </PageSection>
      </div>
    </ProductPage>
  );
}
