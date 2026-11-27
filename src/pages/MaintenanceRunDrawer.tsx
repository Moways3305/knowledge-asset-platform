import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { fetchAgentRun, type ScanRunDetail, type ScanScope } from "../api/maintenanceAgent";
import { ApiError } from "../api/http";
import Button from "../components/Button";
import DetailDrawer from "../components/DetailDrawer";
import PagePagination from "../components/PagePagination";
import { formatBeijingTime } from "../utils/time";

const exclusions: Record<string, string> = {
  archived: "已归档",
  deprecated: "已停用",
  processing: "入库尚未完成",
  inactive: "当前状态不适用",
};
const itemStates: Record<string, string> = {
  pending: "等待检查",
  completed: "检查完成",
  incomplete: "部分未完成",
  skipped: "已跳过",
};

function ScopeSummary({ scope, current = false }: { scope: ScanScope; current?: boolean }) {
  return (
    <section className="agent-report-scope">
      <h3>{current ? "当前范围核对" : "本轮扫描范围"}</h3>
      <p>
        可管理资料 <strong>{scope.visible_count}</strong> 份，可巡检{" "}
        <strong>{scope.target_count}</strong> 份。
      </p>
      {Object.entries(scope.excluded_counts).map(([code, count]) => (
        <p key={code}>
          {exclusions[code] || "不适用"}：{count} 份
        </p>
      ))}
      {scope.target_count === 0 && (
        <p className="agent-report-warning">
          没有符合条件的资料，不代表知识库没有问题。请核对所选知识库及资料的入库、归档状态。
        </p>
      )}
      <small>
        {current ? "实时核对，不能用于还原历史扫描范围。" : "按提交时的范围保存。"}{" "}
        {formatBeijingTime(scope.assessed_at)}
      </small>
    </section>
  );
}

export default function MaintenanceRunDrawer({
  library,
  embedded = false,
  id,
  onClose,
  reasons,
  categories,
  rules,
}: {
  library: string;
  embedded?: boolean;
  id: string;
  onClose: () => void;
  reasons: Record<string, string>;
  categories: Record<string, string>;
  rules: Record<string, string>;
}) {
  const [storedData, setData] = useState<ScanRunDetail | null>(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loadedScope, setLoadedScope] = useState("");
  const scope = JSON.stringify([library, id, page, status]);
  const data = loadedScope === scope ? storedData : null;
  const [fetching, setFetching] = useState(false);
  useEffect(() => {
    let live = true;
    setError("");
    setFetching(true);
    void fetchAgentRun(library, id, page, status)
      .then((value) => {
        if (live) {
          setData(value);
          setLoadedScope(scope);
        }
      })
      .catch((e: unknown) => {
        if (live) {
          setError(e instanceof ApiError ? e.message : "巡检详情更新失败，保留上次结果，请重试。");
          if (e instanceof ApiError && [401, 403, 404].includes(e.status)) setData(null);
        }
      })
      .finally(() => {
        if (live) setFetching(false);
      });
    return () => {
      live = false;
    };
  }, [library, id, page, status, scope, refresh]);
  useEffect(() => {
    if (fetching || !data || !["queued", "running"].includes(data.status)) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") setRefresh((n) => n + 1);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [data, fetching]);
  const waiting = data && ["queued", "running"].includes(data.status);
  return (
    <DetailDrawer
      open
      title="巡检详情"
      description="查看本轮范围、逐项检查结果与未完成原因"
      onClose={onClose}
      portal
      className={`agent-run-drawer${embedded ? " is-workspace-detail" : ""}`}
    >
      <div className="agent-report-toolbar">
        <span>仅所选知识库 · 不包含个人知识库</span>
        <Button
          size="small"
          icon={<RefreshCw size={14} />}
          disabled={fetching}
          onClick={() => setRefresh((n) => n + 1)}
        >
          刷新详情
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!data ? (
        !error && <p role="status">正在加载巡检详情…</p>
      ) : (
        <>
          <p className="agent-note">
            提交：{formatBeijingTime(data.started_at)}
            <br />
            {data.finished_at
              ? `结束：${formatBeijingTime(data.finished_at)}`
              : `最近进展：${formatBeijingTime(data.last_progress_at || data.started_at)}`}
          </p>
          {waiting && (
            <p className="agent-report-warning">
              {data.status === "queued"
                ? "正在等待后台任务领取，尚未开始检查。"
                : "后台正在检查，详情每 15 秒更新。"}{" "}
              长时间没有进展时，请检查后台巡检任务与调度服务，重复提交不会加速。
            </p>
          )}
          {!data.historical_details_available && (
            <p className="agent-report-warning">
              这是一条旧版巡检记录，未保存逐项详情，无法补出当时的检查过程。下方提供当前范围核对；新版巡检将保存完整记录。
            </p>
          )}
          {data.scope_snapshot && <ScopeSummary scope={data.scope_snapshot} />}
          {data.target_count === 0 && !data.scope_snapshot && (
            <p className="agent-report-warning">
              本轮目标资产为 0，没有检查任何资料，不能作为“无问题”的结论。
            </p>
          )}
          <details open={!data.historical_details_available}>
            <summary>核对当前知识库范围</summary>
            <ScopeSummary scope={data.current_scope} current />
          </details>
          {data.settings && (
            <p className="agent-note">
              本轮正文授权：
              {data.content_authorized
                ? "已授权（仍按资料权限检查）"
                : "未授权，正文相关检查不会执行"}
              。分析模型：
              {data.settings.model_ref === "system_default"
                ? "提交时选择平台默认模型"
                : "提交时指定的分析模型"}
              。
            </p>
          )}
          {Object.keys(data.reasons).length > 0 && (
            <section>
              <h3>本轮需要关注</h3>
              <ul>
                {Object.entries(data.reasons).map(([code, count]) => (
                  <li key={code}>
                    {reasons[code] || "检查未完成"}：{count}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {data.historical_details_available && (
            <section>
              <div className="agent-report-toolbar">
                <h3>逐项检查结果</h3>
                <label>
                  结果筛选{" "}
                  <select
                    aria-label="检查结果筛选"
                    value={status}
                    onChange={(e) => {
                      setStatus(e.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">全部结果</option>
                    {Object.entries(itemStates).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="agent-note">
                仅展示目前仍可管理的本库资料。已删除、移库或权限变更的资料可能不再显示；发现的问题数与完成检查数是两回事。
              </p>
              <div className="agent-run-items">
                {data.items.map((item) => (
                  <article key={item.asset_id}>
                    <header>
                      <Link
                        to={`/knowledge/${item.asset_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="在 KAP 新标签页查看知识资料"
                      >
                        {item.title}
                        <span className="agent-reference-hint" aria-hidden="true">
                          {" "}
                          · KAP ↗
                        </span>
                      </Link>
                      <span className={`agent-status agent-status-${item.status}`}>
                        {itemStates[item.status]}
                      </span>
                    </header>
                    {item.checked_at && (
                      <small>
                        {formatBeijingTime(item.checked_at)}
                        {item.version_id &&
                          !item.current_version_matches &&
                          " · 当前版本已变化，本轮结果对应旧版本"}
                      </small>
                    )}
                    {item.progress && Object.keys(item.progress).length > 0 && (
                      <div className="agent-item-progress">
                        {typeof item.progress.body_total === "number" && (
                          <div>
                            正文进度：{(item.progress.body_checked || 0).toLocaleString()} /{" "}
                            {item.progress.body_total.toLocaleString()} 字 · 已检查{" "}
                            {item.progress.segments_checked || 0} 个片段
                          </div>
                        )}
                        {typeof item.progress.comparison_total === "number" && (
                          <div>
                            同库比较：{(item.progress.comparison_checked || 0).toLocaleString()} /{" "}
                            {item.progress.comparison_total.toLocaleString()} 份
                          </div>
                        )}
                        {!!item.progress.retry_attempt && item.status === "pending" && (
                          <div>当前片段正在重试，已尝试 {item.progress.retry_attempt} 次。</div>
                        )}
                      </div>
                    )}
                    {Object.keys(item.coverage).length > 0 && (
                      <dl>
                        {Object.entries(categories).map(([code, label]) => (
                          <div key={code}>
                            <dt>{label}</dt>
                            <dd>
                              {item.coverage[code] === "complete"
                                ? "已检查"
                                : item.coverage[code] === "unchanged"
                                  ? "未变化，沿用上次检查"
                                  : reasons[item.coverage[code]] || "未完成"}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    )}
                    {item.reasons.length > 0 && (
                      <p className="agent-report-warning">
                        {item.reasons.map((code) => reasons[code] || "未完成").join("；")}
                      </p>
                    )}
                    {Object.keys(item.findings).length ? (
                      <ul>
                        {Object.entries(item.findings).map(([code, count]) => (
                          <li key={code}>
                            {rules[code] || "发现待复核问题"}
                            {count > 1 ? `（${count}）` : ""}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      item.status !== "pending" && (
                        <p className="agent-note">
                          {Object.keys(item.coverage).length
                            ? "已执行的检查未产生问题记录；未完成的类别仍需补查。"
                            : "本项尚未取得检查结果，请按原因补查。"}
                        </p>
                      )
                    )}
                  </article>
                ))}
              </div>
              {!data.items.length && <p className="agent-note">当前筛选下没有可展示的检查项。</p>}
              <PagePagination
                ariaLabel="巡检明细分页"
                page={page}
                totalPages={Math.max(1, Math.ceil(data.total / data.page_size))}
                onPageChange={setPage}
                summary={`共 ${data.total} 项`}
              />
            </section>
          )}
        </>
      )}
    </DetailDrawer>
  );
}
