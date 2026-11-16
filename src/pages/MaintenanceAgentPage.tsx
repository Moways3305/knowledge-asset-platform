import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ArrowRight, Bot, CalendarClock, ClipboardCheck, RefreshCw } from "lucide-react";
import { ApiError } from "../api/http";
import {
  actOnAgentIssue,
  fetchAgentIssue,
  fetchAgentIssues,
  fetchAgentPolicies,
  fetchAgentRuns,
  saveAgentPolicy,
  startAgentRun,
  type AgentPolicy,
  type IssueAction,
  type IssueDetail,
  type IssuePage,
  type ScanRun,
} from "../api/maintenanceAgent";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import KnowledgeModuleFrame from "../components/KnowledgeModuleFrame";
import DetailDrawer from "../components/DetailDrawer";
import FormField from "../components/FormField";
import PagePagination from "../components/PagePagination";
import { formatBeijingTime } from "../utils/time";
import "./MaintenanceAgentPage.css";

const categories: Record<string, string> = {
  integrity: "信息完整性",
  availability: "可用性",
  maintenance: "维护状态",
  duplicates: "重复与版本关系",
  quality: "内容质量",
};
const states: Record<string, string> = {
  active: "待处理",
  all: "全部状态",
  open: "待处理",
  in_progress: "处理中",
  awaiting_recheck: "待复检",
  resolved: "已解决",
  false_positive: "已标误报",
  snoozed: "已暂缓",
  not_applicable: "已不适用",
  queued: "等待巡检",
  running: "巡检中",
  completed: "检查完成",
  partial: "部分未完成",
  cancelled: "已取消",
};
const rules: Record<string, string> = {
  missing_summary: "缺少摘要",
  missing_tags: "缺少必要标签",
  missing_directory: "缺少正式分类",
  missing_maintainer: "缺少有效维护人",
  missing_review_date: "缺少复核日期",
  file_unavailable: "原始文件不可读取",
  parse_failed: "正文解析失败",
  index_failed: "索引失败",
  review_overdue: "已到复核日期",
  correction_overdue: "纠错长期未处理",
  update_overdue: "待更新长期无进展",
  exact_duplicate: "完全重复文件",
  possible_duplicate: "疑似重复资料",
  possible_version: "版本关系待确认",
  summary_mismatch: "摘要与正文可能不符",
  cover_only: "疑似只有封面或目录",
  missing_content: "疑似缺少关键内容",
};
const reasons: Record<string, string> = {
  content_not_authorized: "正文未授权或当前权限不足",
  current_version_unavailable: "当前版本不可用",
  body_unavailable: "正文尚不可用",
  body_incomplete: "部分正文分块不可用",
  body_limit: "正文超出单次检查范围",
  summary_limit: "摘要超出单次检查范围",
  candidate_limit: "同库比较范围超出单次上限",
  file_limit: "文件数量超出检查范围",
  processing_pending: "解析或索引仍在处理",
  model_unavailable: "模型未配置或调用失败",
  model_response_incomplete: "模型未完成检查",
  model_evidence_invalid: "模型依据未通过核对",
  authorization_expired: "授权身份已失效，请重新保存配置",
  authorization_changed: "授权或配置已变更",
  policy_changed: "巡检配置已变更",
  asset_changed_during_check: "检查期间资料发生变更",
  asset_out_of_scope: "资料已移出本次范围",
  check_incomplete: "检查未完成",
  ...rules,
};
const message = (error: unknown) =>
  error instanceof ApiError ? error.message : "操作未完成，请稍后重试。";

export default function MaintenanceAgentPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const isCenter = location.pathname === "/agents";
  const key = params.get("library") || "company";
  const tab = params.get("tab") || "issues";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const status = params.get("status") || "active";
  const category = params.get("category") || "";
  const mine = params.get("mine") === "true";
  const [policies, setPolicies] = useState<AgentPolicy[]>([]);
  const [data, setData] = useState<IssuePage | null>(null);
  const [runs, setRuns] = useState<ScanRun[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const policy = policies.find((p) => p.library_key === key);
  const update = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(name, value);
    if (name !== "page") next.delete("page");
    setParams(next);
  };
  useEffect(() => {
    if (isCenter) return;
    let live = true;
    setError("");
    setData(null);
    setRuns([]);
    const filters = new URLSearchParams({
      library_key: key,
      status,
      mine: String(mine),
      page: String(page),
    });
    if (category) filters.set("category", category);
    void Promise.all([fetchAgentPolicies(), fetchAgentIssues(filters)])
      .then(async ([list, items]) => {
        const current = list.find((p) => p.library_key === key);
        const history = current?.can_configure
          ? await fetchAgentRuns(key, tab === "runs" ? page : 1)
          : [];
        if (live) {
          setPolicies(list);
          setData(items);
          setRuns(history);
        }
      })
      .catch((e: unknown) => {
        if (live) setError(message(e));
      });
    return () => {
      live = false;
    };
  }, [isCenter, key, status, category, mine, page, tab, refresh]);
  const hasRunning = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!hasRunning) return;
    const timer = window.setTimeout(() => setRefresh((n) => n + 1), 15000);
    return () => window.clearTimeout(timer);
  }, [hasRunning, refresh]);
  const runNow = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await startAgentRun(key);
      setNotice("巡检已加入后台队列，可在巡检记录中查看进度。");
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <KnowledgeModuleFrame>
      <ProductPage className="maintenance-agent-page">
        <PageHeader
          title={isCenter ? "智能体中心" : "知识维护 Agent"}
          eyebrow="平台预置智能体"
          description={
            isCenter
              ? "让日常知识维护持续运转，重要判断由你确认。"
              : "定期检查知识资产，记录问题并提醒相应维护人。"
          }
          actions={
            !isCenter && (
              <button type="button" onClick={() => setRefresh((n) => n + 1)} disabled={busy}>
                <RefreshCw size={16} /> 刷新
              </button>
            )
          }
        />
        {isCenter ? (
          <section className="agent-catalog" aria-label="预置智能体">
            <div className="agent-catalog-icon">
              <Bot size={28} />
            </div>
            <div>
              <span className="agent-kicker">知识治理</span>
              <h3>知识维护 Agent</h3>
              <p>每日检查新增和变更资产，每周全面巡检。发现问题后，汇总维护待办并发送提醒。</p>
              <div className="agent-category-line">
                {Object.values(categories).map((label) => (
                  <span key={label}>{label}</span>
                ))}
              </div>
              <Link className="agent-primary" to="/agents/knowledge-maintenance">
                进入知识维护 <ArrowRight size={17} />
              </Link>
            </div>
          </section>
        ) : (
          <>
            <div className="agent-toolbar">
              <FormField label="巡检知识库">
                <select value={key} onChange={(e) => update("library", e.target.value)}>
                  {policies.length ? (
                    policies.map((p) => (
                      <option key={p.library_key} value={p.library_key}>
                        {p.name}
                      </option>
                    ))
                  ) : (
                    <option value="company">公司知识库</option>
                  )}
                </select>
              </FormField>
              <div className="agent-scope">
                <CalendarClock size={18} />
                <span>
                  资产区 · 每日增量 / 每周全量
                  <br />
                  <small>个人知识库和素材区不参与巡检</small>
                </span>
              </div>
              <button
                className="agent-primary"
                type="button"
                disabled={busy || hasRunning || !policy?.id || !policy.can_configure}
                onClick={() => void runNow()}
              >
                {busy ? "正在提交…" : hasRunning ? "巡检进行中" : "立即全面巡检"}
              </button>
            </div>
            {error && (
              <p role="alert" className="agent-error">
                {error}{" "}
                <button type="button" onClick={() => setRefresh((n) => n + 1)}>
                  重试
                </button>
              </p>
            )}
            {notice && <p role="status">{notice}</p>}
            {policy?.last_error && (
              <p role="alert" className="agent-error">
                {reasons[policy.last_error] || "巡检配置需要检查"}
              </p>
            )}
            <nav className="agent-tabs" aria-label="知识维护视图">
              {[
                ["issues", "维护待办"],
                ["runs", "巡检记录"],
                ["settings", "巡检设置"],
              ].map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  aria-current={tab === value ? "page" : undefined}
                  onClick={() => update("tab", value)}
                >
                  {label}
                </button>
              ))}
            </nav>
            {!data && !error && <p role="status">正在加载巡检信息…</p>}
            {tab === "issues" && data && (
              <section aria-label="巡检问题" className="agent-panel">
                <div className="agent-filters">
                  <FormField label="检查类别">
                    <select value={category} onChange={(e) => update("category", e.target.value)}>
                      <option value="">全部类别</option>
                      {Object.entries(categories).map(([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </FormField>
                  <FormField label="处理状态">
                    <select value={status} onChange={(e) => update("status", e.target.value)}>
                      {Object.entries(states)
                        .filter(
                          ([v]) =>
                            ![
                              "queued",
                              "running",
                              "completed",
                              "partial",
                              "cancelled",
                              "open",
                            ].includes(v),
                        )
                        .map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                    </select>
                  </FormField>
                  <label className="agent-checkbox">
                    <input
                      type="checkbox"
                      checked={mine}
                      onChange={(e) => update("mine", String(e.target.checked))}
                    />{" "}
                    只看我负责的
                  </label>
                  <span>{data.total} 个问题</span>
                </div>
                {data.items.length ? (
                  <ul className="agent-issues">
                    {data.items.map((issue) => (
                      <li key={issue.id}>
                        <div className="agent-issue-meta">
                          <span>{categories[issue.category]}</span>
                          <span className={`agent-status agent-status-${issue.status}`}>
                            {states[issue.status]}
                          </span>
                        </div>
                        <button
                          className="agent-issue-title"
                          type="button"
                          onClick={() => setSelected(issue.id)}
                        >
                          {rules[issue.rule] || "知识资产待核查"}
                          <ArrowRight size={16} />
                        </button>
                        <div className="agent-asset-title">{issue.title}</div>
                        <div className="agent-issue-foot">
                          <span>
                            {issue.suspected
                              ? "疑似问题 · 需要人工判断"
                              : "客观检查项 · 修正后复检"}
                          </span>
                          <span>
                            维护人：
                            {issue.responsible.map((r) => r.name).join("、") ||
                              "等待知识库管理人认领"}
                          </span>
                          <time>{formatBeijingTime(issue.last_seen_at)}</time>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="agent-empty">
                    <ClipboardCheck size={28} />
                    <h3>当前筛选下没有维护待办</h3>
                    <p>
                      {policy?.id
                        ? "可切换条件，或在巡检记录中确认检查是否完整。"
                        : "请由知识库管理人先保存巡检设置，再开始检查。"}
                    </p>
                  </div>
                )}
                <PagePagination
                  ariaLabel="维护问题分页"
                  page={page}
                  totalPages={Math.max(1, Math.ceil(data.total / 25))}
                  onPageChange={(p) => update("page", String(p))}
                  summary={`共 ${data.total} 项`}
                />
              </section>
            )}
            {tab === "runs" && data && (
              <section className="agent-panel" aria-label="巡检记录">
                <p className="agent-note">
                  完成检查不代表没有问题。未完成项会保留原因，已有问题不会因此自动关闭。
                </p>
                {!policy?.can_configure ? (
                  <p>巡检记录由知识库管理人查看。</p>
                ) : runs.length ? (
                  <>
                    <div className="agent-runs">
                      {runs.map((run) => (
                        <article key={run.id}>
                          <header>
                            <h3>
                              {run.kind === "incremental"
                                ? "每日增量巡检"
                                : run.kind === "recheck"
                                  ? "指定资产复检"
                                  : "全面巡检"}
                            </h3>
                            <span className={`agent-status agent-status-${run.status}`}>
                              {states[run.status]}
                            </span>
                          </header>
                          <time>{formatBeijingTime(run.started_at)}</time>
                          <dl>
                            <div>
                              <dt>目标资产</dt>
                              <dd>{run.target_count}</dd>
                            </div>
                            <div>
                              <dt>检查完成</dt>
                              <dd>{run.completed_count}</dd>
                            </div>
                            <div>
                              <dt>未完成</dt>
                              <dd>{run.incomplete_count}</dd>
                            </div>
                            <div>
                              <dt>跳过</dt>
                              <dd>{run.skipped_count}</dd>
                            </div>
                          </dl>
                          {Object.keys(run.reasons).length > 0 && (
                            <ul>
                              {Object.entries(run.reasons).map(([code, count]) => (
                                <li key={code}>
                                  {reasons[code] || "检查需要关注"}：{count}
                                </li>
                              ))}
                            </ul>
                          )}
                        </article>
                      ))}
                    </div>
                    <div className="agent-run-pages">
                      <button
                        type="button"
                        disabled={page <= 1}
                        onClick={() => update("page", String(page - 1))}
                      >
                        上一页
                      </button>
                      <span>第 {page} 页</span>
                      <button
                        type="button"
                        disabled={runs.length < 25}
                        onClick={() => update("page", String(page + 1))}
                      >
                        下一页
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="agent-empty">
                    <CalendarClock size={28} />
                    <h3>尚无可查看的巡检记录</h3>
                    <p>保存设置后可立即执行一次全面巡检。</p>
                  </div>
                )}
              </section>
            )}
            {tab === "settings" && policy && (
              <PolicyEditor
                key={`${policy.library_key}:${policy.revision}`}
                policy={policy}
                onSaved={() => {
                  setNotice("巡检设置已保存。");
                  setRefresh((n) => n + 1);
                }}
              />
            )}
            <p className="agent-note">
              提醒方式：站内待办和通知，配合企业微信摘要。通知已读不会关闭问题。
              <Link to="/help?guide=maintenance-agent">查看使用说明</Link>
            </p>
          </>
        )}
        {selected && (
          <IssueDrawer
            id={selected}
            onClose={() => setSelected(null)}
            onChanged={() => setRefresh((n) => n + 1)}
          />
        )}
      </ProductPage>
    </KnowledgeModuleFrame>
  );
}

function PolicyEditor({ policy, onSaved }: { policy: AgentPolicy; onSaved: () => void }) {
  const [enabled, setEnabled] = useState(policy.enabled);
  const [authorized, setAuthorized] = useState(policy.content_authorized);
  const [settings, setSettings] = useState(policy.settings);
  const [tags, setTags] = useState(settings.required_tags.join("，"));
  const [sections, setSections] = useState(settings.required_sections.join("，"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const split = (s: string) =>
      s
        .split(/[,，\n]/)
        .map((x) => x.trim())
        .filter(Boolean);
    try {
      await saveAgentPolicy(policy.library_key, {
        expected_revision: policy.revision,
        enabled,
        content_authorized: authorized,
        settings: { ...settings, required_tags: split(tags), required_sections: split(sections) },
      });
      onSaved();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="agent-panel agent-settings" onSubmit={(e) => void save(e)}>
      <h3>巡检与授权</h3>
      <p>
        本知识库使用同一个预置
        Agent。保存后，以你的当前业务身份执行检查；身份或权限失效时停止相关检查。
      </p>
      {!policy.can_configure && <p>请由公司知识治理人员或该项目经理配置巡检。</p>}
      <fieldset disabled={busy || !policy.can_configure}>
        <label className="agent-checkbox">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />{" "}
          开启定期巡检
        </label>
        <div className="agent-settings-grid">
          <FormField label="每日增量巡检（北京时间）">
            <select
              value={settings.daily_hour}
              onChange={(e) => setSettings({ ...settings, daily_hour: Number(e.target.value) })}
            >
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i}>
                  {String(i).padStart(2, "0")}:00
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="每周全面巡检">
            <select
              value={settings.weekly_day}
              onChange={(e) => setSettings({ ...settings, weekly_day: Number(e.target.value) })}
            >
              {["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="摘要提醒（北京时间）">
            <select
              value={settings.digest_hour}
              onChange={(e) => setSettings({ ...settings, digest_hour: Number(e.target.value) })}
            >
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i}>
                  {String(i).padStart(2, "0")}:00
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="长期未处理阈值（天）">
            <input
              type="number"
              min={1}
              max={365}
              required
              value={settings.overdue_days}
              onChange={(e) => setSettings({ ...settings, overdue_days: Number(e.target.value) })}
            />
          </FormField>
          <FormField label="必要标签（逗号分隔）">
            <input
              value={tags}
              maxLength={2000}
              onChange={(e) => setTags(e.target.value)}
              placeholder="留空时检查是否至少有一个标签"
            />
          </FormField>
          <FormField label="必要内容章节（逗号分隔）">
            <input
              value={sections}
              maxLength={2000}
              onChange={(e) => setSections(e.target.value)}
              placeholder="例如：适用范围、操作步骤"
            />
          </FormField>
          <FormField label="相似标题提示阈值">
            <input
              type="number"
              min={0.5}
              max={1}
              step={0.05}
              value={settings.similarity_threshold}
              onChange={(e) =>
                setSettings({ ...settings, similarity_threshold: Number(e.target.value) })
              }
            />
          </FormField>
          <FormField label="单份正文检查上限（字）">
            <input
              type="number"
              min={1000}
              max={60000}
              step={1000}
              value={settings.max_body_chars}
              onChange={(e) => setSettings({ ...settings, max_body_chars: Number(e.target.value) })}
            />
          </FormField>
        </div>
        <div className="agent-authorization">
          <label className="agent-checkbox">
            <input
              type="checkbox"
              checked={authorized}
              onChange={(e) => setAuthorized(e.target.checked)}
            />{" "}
            授权检查可访问的原始文件，并使用平台默认模型分析正文
          </label>
          <p>
            仅检查当前身份与智能体渠道允许访问的资产。正文会发送给平台已配置的模型服务；未授权或权限不足的检查显示“未完成”。不会自动修改或删除资产。
          </p>
        </div>
        <p>
          五类检查全部启用；到期复核和长期未处理事项每天都会检查。首次运行全面巡检，之后每天检查新增或变更内容。重复比较限于同一知识库。
        </p>
        {error && (
          <p role="alert" className="agent-error">
            {error}
          </p>
        )}
        <button type="submit" className="agent-primary">
          {busy ? "正在保存…" : "保存巡检设置"}
        </button>
      </fieldset>
    </form>
  );
}

function IssueDrawer({
  id,
  onClose,
  onChanged,
}: {
  id: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [issue, setIssue] = useState<IssueDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState("");
  const [action, setAction] = useState<IssueAction["action"]>("in_progress");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setIssue(null);
    setError("");
    void fetchAgentIssue(id)
      .then((x) => {
        if (live) setIssue(x);
      })
      .catch((e: unknown) => {
        if (live) setError(message(e));
      });
    return () => {
      live = false;
    };
  }, [id, reload]);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!issue) return;
    setBusy(true);
    setError("");
    try {
      const updated = await actOnAgentIssue(id, {
        action,
        expected_updated_at: issue.updated_at,
        reason,
        ...(action === "snoozed" ? { snooze_until: `${date}T23:59:00+08:00` } : {}),
      });
      setIssue(updated);
      setReason("");
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <DetailDrawer
      open
      title={issue ? rules[issue.rule] || "问题详情" : "问题详情"}
      description={issue?.title}
      onClose={onClose}
      busy={busy}
      portal
      className="agent-detail"
    >
      <div className="agent-detail-content">
        {error && (
          <p role="alert">
            {error}{" "}
            <button type="button" onClick={() => setReload((n) => n + 1)}>
              重新加载
            </button>
          </p>
        )}
        {!issue && !error && <p role="status">正在加载问题详情…</p>}
        {issue && (
          <>
            <div className="agent-issue-meta">
              <span className="agent-status">{states[issue.status]}</span>
              <span>{issue.suspected ? "疑似问题，需人工复核" : "客观检查项"}</span>
            </div>
            <p>维护人：{issue.responsible.map((r) => r.name).join("、") || "等待管理人认领"}</p>
            <p>首次发现：{formatBeijingTime(issue.first_seen_at)}</p>
            {!issue.current_version_matches && <p role="status">资料版本已变化，请重新检查。</p>}
            <h3>检查依据</h3>
            {!issue.evidence_available ? (
              <p>当前无原文权限，检查依据已隐藏。请到资料详情申请访问。</p>
            ) : (
              <>
                {issue.evidence.quote && <blockquote>{issue.evidence.quote}</blockquote>}
                {issue.evidence.related_asset_id && (
                  <p>
                    关联资料：
                    <Link to={`/knowledge/${issue.evidence.related_asset_id}`}>
                      {issue.evidence.related_title}
                    </Link>
                  </p>
                )}
                {issue.evidence.basis === "sha256_equal" && (
                  <p>两份文件的内容校验值一致，请人工确认是否保留或关联。</p>
                )}
                {issue.evidence.similarity !== undefined && (
                  <p>
                    标题相似度：{Math.round(issue.evidence.similarity * 100)}
                    %。请结合正文确认重复或版本关系。
                  </p>
                )}
                {issue.evidence.missing_tags?.length ? (
                  <p>缺少标签：{issue.evidence.missing_tags.join("、")}</p>
                ) : null}
                {issue.evidence.due_at && (
                  <p>应复核日期：{formatBeijingTime(issue.evidence.due_at)}</p>
                )}
                {!Object.keys(issue.evidence).length && (
                  <p>{rules[issue.rule]}。请进入资料详情核对并处理。</p>
                )}
              </>
            )}
            <Link className="agent-primary" to={`/knowledge/${issue.asset_id}`}>
              打开资料详情 <ArrowRight size={16} />
            </Link>
            {issue.can_act && (
              <form onSubmit={(e) => void submit(e)}>
                <h3>处理问题</h3>
                <fieldset disabled={busy}>
                  <FormField label="处理方式">
                    <select
                      value={action}
                      onChange={(e) => setAction(e.target.value as IssueAction["action"])}
                    >
                      <option value="in_progress">标记处理中</option>
                      <option value="recheck">修正后重新检查</option>
                      <option value="snoozed">暂缓处理</option>
                      {issue.evidence_available && <option value="false_positive">标记误报</option>}
                      {issue.suspected && issue.evidence_available && (
                        <option value="resolved">人工确认已解决</option>
                      )}
                    </select>
                  </FormField>
                  <FormField label="处理原因">
                    <textarea
                      value={reason}
                      maxLength={1000}
                      required={["resolved", "false_positive", "snoozed"].includes(action)}
                      onChange={(e) => setReason(e.target.value)}
                      rows={3}
                    />
                  </FormField>
                  {action === "snoozed" && (
                    <FormField label="暂缓至（北京时间）">
                      <input
                        type="date"
                        required
                        value={date}
                        onChange={(e) => setDate(e.target.value)}
                      />
                    </FormField>
                  )}
                  <button type="submit" className="agent-primary">
                    {busy ? "正在提交…" : "提交处理"}
                  </button>
                </fieldset>
              </form>
            )}
            <h3>处理记录</h3>
            <ol className="agent-history">
              {issue.history.map((event, i) => (
                <li key={`${event.created_at}:${i}`}>
                  <strong>
                    {states[event.action] ||
                      (
                        {
                          detected: "发现问题",
                          reopened: "重新发现",
                          recheck_passed: "复检通过",
                        } as Record<string, string>
                      )[event.action] ||
                      "状态更新"}
                  </strong>
                  <time>{formatBeijingTime(event.created_at)}</time>
                  {event.reason && <p>{event.reason}</p>}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </DetailDrawer>
  );
}
