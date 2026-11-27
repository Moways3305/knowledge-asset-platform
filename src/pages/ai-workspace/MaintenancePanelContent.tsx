import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, CalendarClock, ClipboardCheck, Cpu, RefreshCw } from "lucide-react";
import { ApiError } from "../../api/http";
import {
  actOnAgentIssue,
  fetchAgentIssue,
  fetchAgentIssues,
  fetchAgentPolicies,
  fetchAgentModels,
  fetchAgentRuns,
  saveAgentPolicy,
  startAgentRun,
  type AgentPolicy,
  type AgentModelOptions,
  type IssueAction,
  type IssueDetail,
  type IssuePage,
  type ScanRun,
} from "../../api/maintenanceAgent";
import Button from "../../components/Button";
import { useAuth } from "../../auth/AuthContext";
import { can } from "../../auth/permissions";
import DetailDrawer from "../../components/DetailDrawer";
import FormField from "../../components/FormField";
import PagePagination from "../../components/PagePagination";
import { formatBeijingTime } from "../../utils/time";
import "./MaintenancePanelContent.css";
import { WorkspaceIconButton } from "./WorkspaceTooltip";
import MaintenanceRunDrawer from "../MaintenanceRunDrawer";
import MaintenanceRunList from "../MaintenanceRunList";

const categories: Record<string, string> = {
  integrity: "信息完整性",
  availability: "可用性",
  maintenance: "维护状态",
  duplicates: "重复与版本关系",
  quality: "内容质量",
  privacy: "敏感个人信息",
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
  empty: "没有可巡检资产",
};
const rules: Record<string, string> = {
  personal_information: "疑似包含敏感个人信息",
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
  privacy_check_failed: "个人信息检查未完成，请重新检查",
  content_not_authorized: "正文未授权或当前权限不足",
  current_version_unavailable: "当前版本不可用",
  body_unavailable: "正文尚不可用",
  body_incomplete: "部分正文分块不可用",
  body_limit: "旧版正文检查未完成，可重试分段检查",
  summary_limit: "旧版摘要检查未完成，可重试分段检查",
  candidate_limit: "旧版同库比较未完成，可重试分批比较",
  file_limit: "文件数量超出检查范围",
  processing_pending: "解析或索引仍在处理",
  model_unavailable: "模型调用失败，请重试或检查模型连接",
  model_configuration_error: "尚未配置可用模型，请在巡检设置选择模型",
  model_authentication_error: "模型认证失败，请管理员检查凭据",
  model_request_error: "模型拒绝请求，请检查模型配置",
  model_connection_error: "模型连接失败，自动重试后仍未完成",
  model_timeout: "模型响应超时，自动重试后仍未完成",
  model_rate_limited: "模型限流，自动重试后仍未完成",
  model_server_error: "模型服务异常，自动重试后仍未完成",
  model_model_unavailable: "所选模型不可用，请检查模型名称及访问权限",
  model_response_error: "模型响应无法读取，请重试",
  user_cancelled: "用户已取消巡检",
  in_progress: "分批检查中",
  model_response_incomplete: "模型未完成检查",
  model_evidence_invalid: "模型依据未通过核对",
  authorization_expired: "授权身份已失效，请重新保存配置",
  authorization_changed: "授权或配置已变更",
  policy_changed: "巡检配置已变更",
  asset_changed_during_check: "检查期间资料发生变更",
  asset_out_of_scope: "资料已移出本次范围",
  check_incomplete: "检查未完成",
  no_eligible_assets: "所选知识库没有符合巡检条件的资料",
  ...rules,
};
const message = (error: unknown) =>
  error instanceof ApiError ? error.message : "操作未完成，请稍后重试。";

const personalTypes: Record<string, string> = {
  email: "邮箱",
  phone: "电话",
  landline: "固定电话",
  id_card: "身份证号",
  bank_card: "银行卡号",
  account: "个人账号",
  contact: "姓名或联系人",
  address: "住址或位置",
  health: "健康信息",
  biometric: "生物识别信息",
  personal_id: "个人证件或标识",
  personal_finance: "个人财务信息",
};
const personalSources: Record<string, string> = {
  body: "正文",
  summary: "摘要",
  title: "标题",
  tag: "标签",
};
const summarySources: Record<string, string> = {
  one_liner: "短摘要",
  key_points: "摘要要点",
  detailed: "完整摘要",
  detailed_summary: "完整摘要",
  summary: "摘要",
  redacted_one_liner: "脱敏短摘要",
  redacted_summary: "脱敏完整摘要",
  safe_summary: "安全摘要",
};

export interface MaintenancePolicyDraft {
  enabled: boolean;
  authorized: boolean;
  settings: AgentPolicy["settings"];
  tags: string;
  sections: string;
  expectedRevision: number;
  savedDraft: string;
}

export default function MaintenancePanelContent({
  onNavigate,
  onDirtyChange,
  draftCache,
}: {
  onNavigate: (changes: Record<string, string | null>) => void;
  onDirtyChange?: (dirty: boolean) => void;
  draftCache?: Map<string, MaintenancePolicyDraft>;
}) {
  const [params] = useSearchParams();
  const digestId = params.get("target_id") || params.get("digest_id") || "";
  const inbox = Boolean(digestId) || params.get("view") === "mine";
  const key = params.get("library") || (inbox ? "" : "company");
  const requestedPanel = params.get("panel") || params.get("tab");
  const tab =
    inbox || Boolean(params.get("asset_id"))
      ? "issues"
      : ["issues", "runs", "settings"].includes(requestedPanel || "")
        ? requestedPanel!
        : "issues";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const status = params.get("status") || "active";
  const category = params.get("category") || "";
  const mine = inbox || params.get("mine") === "true";
  const priority =
    !digestId && params.get("priority") === "suggestion" ? "suggestion" : "actionable";
  const assetId = params.get("asset_id") || "";
  const [policies, setPolicies] = useState<AgentPolicy[]>([]);
  const [storedData, setData] = useState<IssuePage | null>(null);
  const [storedRuns, setRuns] = useState<ScanRun[]>([]);
  const [loadedScope, setLoadedScope] = useState("");
  const scope = JSON.stringify([
    key,
    status,
    category,
    mine,
    page,
    tab,
    priority,
    assetId,
    digestId,
    inbox,
  ]);
  const data = loadedScope === scope ? storedData : null;
  const libraries = digestId
    ? policies.filter((p) => data?.digest_libraries?.includes(p.library_key))
    : policies;
  const displayLibrary = key || (libraries.length === 1 ? libraries[0].library_key : "");
  const runs = loadedScope === scope ? storedRuns : [];
  const [modelRefresh, setModelRefresh] = useState(0);
  const [editorRevision, setEditorRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [models, setModels] = useState<AgentModelOptions | null>(null);
  const [modelError, setModelError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const policy = policies.find((p) => p.library_key === key);
  const update = (name: string, value: string) => {
    onNavigate({ [name]: value || null, ...(name !== "page" ? { page: null } : {}) });
  };
  useEffect(() => {
    setSelectedRun(null);
    setSelected(null);
  }, [key, digestId, inbox]);
  useEffect(() => {
    if (inbox) return;
    let live = true;
    setModelError("");
    void fetchAgentModels()
      .then((value) => {
        if (live) setModels(value);
      })
      .catch((e: unknown) => {
        if (live) setModelError(message(e));
      });
    return () => {
      live = false;
    };
  }, [inbox, modelRefresh]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    const filters = new URLSearchParams({
      priority,
      status,
      mine: String(mine),
      page: String(page),
    });
    if (key) filters.set("library_key", key);
    if (digestId) filters.set("digest_id", digestId);
    if (category) filters.set("category", category);
    if (assetId) filters.set("asset_id", assetId);
    void Promise.all([fetchAgentPolicies(), fetchAgentIssues(filters)])
      .then(async ([list, items]) => {
        const current = list.find((p) => p.library_key === key);
        const history =
          !inbox && current?.can_configure
            ? await fetchAgentRuns(key, tab === "runs" ? page : 1)
            : [];
        if (live) {
          setPolicies(list);
          setData(items);
          setRuns(history);
          setLoadedScope(scope);
        }
      })
      .catch((e: unknown) => {
        if (live) {
          setError(message(e));
          if (e instanceof ApiError && [401, 403, 404].includes(e.status)) {
            setData(null);
            setRuns([]);
            setPolicies([]);
            setSelected(null);
            setSelectedRun(null);
          }
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [key, status, category, mine, page, tab, priority, assetId, digestId, inbox, scope, refresh]);
  const hasRunning = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!hasRunning || loading) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") setRefresh((n) => n + 1);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [hasRunning, loading, refresh]);
  const runNow = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await startAgentRun(key);
      setNotice(
        result.status === "empty"
          ? "本知识库没有符合巡检条件的资料，请查看详情核对范围。"
          : "巡检已加入后台队列，可在巡检记录中查看进度。",
      );
      setSelectedRun(result.id);
      update("panel", "runs");
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="aw-maintenance-content maintenance-panel-content" data-maintenance-panel={tab}>
      <div className="maintenance-panel-library">
        <FormField label={digestId ? "本次提醒的知识库" : inbox ? "待办所属知识库" : "知识库"}>
          <select
            value={displayLibrary}
            onChange={(event) => update("library", event.target.value)}
          >
            {inbox && libraries.length !== 1 && <option value="">全部相关知识库</option>}
            {libraries.map((item) => (
              <option key={item.library_key} value={item.library_key}>
                {item.name}
              </option>
            ))}
            {!inbox && !libraries.length && <option value="company">公司知识库</option>}
          </select>
        </FormField>
        <WorkspaceIconButton
          label="刷新"
          tooltip="刷新当前面板"
          disabled={busy || loading}
          onClick={() => {
            setRefresh((value) => value + 1);
            setModelRefresh((value) => value + 1);
          }}
        >
          <RefreshCw size={15} />
        </WorkspaceIconButton>
      </div>
      {inbox && displayLibrary && (
        <Button
          variant="ghost"
          size="small"
          onClick={() =>
            onNavigate({
              library: displayLibrary,
              panel: "issues",
              tab: null,
              target_id: null,
              digest_id: null,
              view: null,
              mine: null,
              page: null,
            })
          }
        >
          查看该知识库全部待办
        </Button>
      )}
      {error && (
        <p role="alert" className="agent-error">
          {error}{" "}
          <Button size="small" onClick={() => setRefresh((n) => n + 1)}>
            重试
          </Button>
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {policy?.last_error && (
        <p role="alert" className="agent-error">
          {reasons[policy.last_error] || "巡检配置需要检查"}
        </p>
      )}
      {!data && !error && <p role="status">正在加载巡检信息…</p>}
      {tab === "issues" && data && (
        <section aria-label="巡检问题" className="agent-panel">
          {!digestId && (
            <div className="agent-priority" role="group" aria-label="维护优先级">
              {(
                [
                  ["actionable", "需要处理"],
                  ["suggestion", "完善建议"],
                ] as const
              ).map(([value, label]) => (
                <Button
                  key={value}
                  variant={priority === value ? "primary" : "secondary"}
                  aria-pressed={priority === value}
                  onClick={() => update("priority", value)}
                >
                  {label} {data.counts?.[value] ?? ""}
                </Button>
              ))}
            </div>
          )}
          <p className="agent-note">
            {digestId
              ? "本次巡检提醒中由你负责的问题"
              : priority === "suggestion"
                ? "摘要、分类、标签等完善建议按需处理，不重复发送待办提醒。"
                : "显示影响使用、内容可靠性或已经到期的维护事项。"}
          </p>
          {assetId && (
            <p>
              仅显示当前资料的巡检问题。
              <Button variant="ghost" onClick={() => update("asset_id", "")}>
                查看全部资料
              </Button>
            </p>
          )}
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
                      !["queued", "running", "completed", "partial", "cancelled", "open"].includes(
                        v,
                      ),
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
                disabled={inbox}
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
                    {inbox && !displayLibrary && (
                      <span>
                        {libraries.find((p) => p.library_key === issue.library_key)?.name}
                      </span>
                    )}
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
                        : issue.priority === "suggestion"
                          ? "完善建议 · 修改后自动同步"
                          : "客观检查项 · 修正后自动同步"}
                    </span>
                    <span>
                      维护人：
                      {issue.responsible.map((r) => r.name).join("、") || "等待知识库管理人认领"}
                    </span>
                    <time>{formatBeijingTime(issue.last_seen_at)}</time>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="agent-empty">
              <ClipboardCheck size={28} />
              <h3>{inbox || policy?.id ? "当前筛选下没有维护待办" : "从首次巡检开始"}</h3>
              <p>
                {inbox
                  ? "可切换处理状态查看已办结的问题。"
                  : policy?.id
                    ? "可切换条件，或在巡检记录中确认检查是否完整。"
                    : policy?.can_configure
                      ? "在配置面板选择分析模型并确认授权，再向 Agent 交代巡检目标。"
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
              <MaintenanceRunList
                key={`${key}:${page}`}
                library={key}
                runs={runs}
                onSelect={setSelectedRun}
                onChanged={(deleted) => {
                  if (selectedRun && deleted.includes(selectedRun)) setSelectedRun(null);
                  if (deleted.length >= runs.length && page > 1) update("page", String(page - 1));
                  setRefresh((n) => n + 1);
                }}
              />
              <div className="agent-run-pages">
                <Button
                  size="small"
                  disabled={page <= 1}
                  onClick={() => update("page", String(page - 1))}
                >
                  上一页
                </Button>
                <span>第 {page} 页</span>
                <Button
                  size="small"
                  disabled={runs.length < 25}
                  onClick={() => update("page", String(page + 1))}
                >
                  下一页
                </Button>
              </div>
            </>
          ) : (
            <div className="agent-empty">
              <CalendarClock size={28} />
              <h3>尚无可查看的巡检记录</h3>
              <p>向 Agent 交代巡检目标后，可在这里查看执行记录。</p>
            </div>
          )}
        </section>
      )}
      {tab === "settings" && policy && (
        <PolicyEditor
          key={`${policy.library_key}:${editorRevision}`}
          policy={policy}
          models={models}
          modelError={modelError}
          hasRunning={hasRunning}
          onReloadModels={() => setModelRefresh((n) => n + 1)}
          onDirtyChange={onDirtyChange}
          draftCache={draftCache}
          onSaved={async (saved, start) => {
            setPolicies((items) =>
              items.map((item) => (item.library_key === saved.library_key ? saved : item)),
            );
            setEditorRevision((n) => n + 1);
            setNotice("巡检设置已保存。");
            setRefresh((n) => n + 1);
            if (start) await runNow();
          }}
        />
      )}
      {selected && (
        <IssueDrawer
          id={selected}
          embedded
          onClose={() => setSelected(null)}
          onChanged={() => setRefresh((n) => n + 1)}
        />
      )}
      {selectedRun && (
        <MaintenanceRunDrawer
          key={`${key}:${selectedRun}`}
          embedded
          library={key}
          id={selectedRun}
          onClose={() => setSelectedRun(null)}
          reasons={reasons}
          categories={categories}
          rules={rules}
        />
      )}
    </div>
  );
}

function PolicyEditor({
  policy,
  models,
  modelError,
  hasRunning,
  onReloadModels,
  onSaved,
  onDirtyChange,
  draftCache,
}: {
  policy: AgentPolicy;
  models: AgentModelOptions | null;
  modelError: string;
  hasRunning: boolean;
  onReloadModels: () => void;
  onSaved: (saved: AgentPolicy, start: boolean) => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
  draftCache?: Map<string, MaintenancePolicyDraft>;
}) {
  const { capabilities } = useAuth();
  const [restored] = useState(() =>
    policy.can_configure ? draftCache?.get(policy.library_key) : undefined,
  );
  const [enabled, setEnabled] = useState(restored?.enabled ?? policy.enabled);
  const [authorized, setAuthorized] = useState(restored?.authorized ?? policy.content_authorized);
  const [settings, setSettings] = useState(restored?.settings ?? policy.settings);
  const [tags, setTags] = useState(restored?.tags ?? settings.required_tags.join("，"));
  const [sections, setSections] = useState(
    restored?.sections ?? settings.required_sections.join("，"),
  );
  const [expectedRevision] = useState(restored?.expectedRevision ?? policy.revision);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const draft = JSON.stringify({ enabled, authorized, settings, tags, sections });
  const [savedDraft, setSavedDraft] = useState(restored?.savedDraft ?? draft);
  const dirty = draft !== savedDraft;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (dirty) {
      draftCache?.set(policy.library_key, {
        enabled,
        authorized,
        settings,
        tags,
        sections,
        expectedRevision,
        savedDraft,
      });
    } else draftCache?.delete(policy.library_key);
  }, [
    dirty,
    draftCache,
    policy.library_key,
    enabled,
    authorized,
    settings,
    tags,
    sections,
    expectedRevision,
    savedDraft,
  ]);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const modelRef = settings.model_ref || "system_default";
  const model = models?.items.find((m) =>
    modelRef === "system_default" ? m.is_default : m.model_ref === modelRef,
  );
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
      const submittedDraft = draftCache?.get(policy.library_key);
      const submitter = (event.nativeEvent as SubmitEvent).submitter;
      const start = submitter instanceof HTMLButtonElement && submitter.value === "run";
      const saved = await saveAgentPolicy(policy.library_key, {
        expected_revision: expectedRevision,
        enabled,
        content_authorized: authorized,
        settings: {
          ...settings,
          model_ref: modelRef,
          required_tags: split(tags),
          required_sections: split(sections),
        },
      });
      if (draftCache?.get(policy.library_key) === submittedDraft)
        draftCache?.delete(policy.library_key);
      if (!mounted.current) return;
      setSavedDraft(draft);
      onDirtyChange?.(false);
      await onSaved(saved, start);
    } catch (e) {
      if (mounted.current) setError(message(e));
    } finally {
      if (mounted.current) setBusy(false);
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
        <section className="agent-model-settings" aria-label="分析模型配置">
          <div className="agent-section-heading">
            <Cpu size={19} />
            <div>
              <h4>分析模型</h4>
              <p>用于核对摘要与正文、识别内容缺失，并给出可复核的依据。</p>
            </div>
          </div>
          <FormField label="正文分析模型">
            <select
              value={modelRef}
              disabled={!models}
              onChange={(e) => setSettings({ ...settings, model_ref: e.target.value })}
            >
              <option value="system_default">
                跟随平台默认
                {models?.items.find((m) => m.is_default)
                  ? ` · ${models.items.find((m) => m.is_default)?.display_name}`
                  : "（尚未配置）"}
              </option>
              {models?.items.map((m) => (
                <option key={m.model_ref} value={m.model_ref}>
                  {m.display_name}
                </option>
              ))}
              {models && modelRef !== "system_default" && !model && (
                <option value={modelRef}>原选模型已不可用，请重新选择</option>
              )}
            </select>
          </FormField>
          {model ? (
            <p className="agent-model-detail">
              {model.provider} · {model.model_name}{" "}
              <span>
                {modelRef === "system_default"
                  ? "随平台默认设置更新"
                  : "仅用于本知识库的知识维护 Agent"}
              </span>
            </p>
          ) : (
            <p className="agent-note">
              {modelError ||
                (!models
                  ? "正在读取平台已接入的模型…"
                  : "当前没有可用的分析模型。规则巡检仍可执行，正文质量检查会标记为未完成。")}
            </p>
          )}
          <div className="agent-model-links">
            {can.viewModels(capabilities) ? (
              <Link
                to="/admin/weknora-models"
                target="_blank"
                rel="noopener noreferrer"
                title="在 KAP 新标签页查看平台模型配置"
              >
                查看平台模型配置（KAP ↗）
              </Link>
            ) : (
              <span>如需接入新模型，请联系平台管理员。</span>
            )}
            {modelError && (
              <Button size="small" onClick={onReloadModels}>
                重新读取模型
              </Button>
            )}
          </div>
        </section>
        <h4 className="agent-settings-heading">巡检计划与规则</h4>
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
              placeholder="留空时不检查必要标签"
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
          <p className="agent-note">
            长文档自动分段检查，同库比较分批完成；可在巡检详情查看处理进度。
          </p>
        </div>
        <div className="agent-authorization">
          <label className="agent-checkbox">
            <input
              type="checkbox"
              checked={authorized}
              onChange={(e) => setAuthorized(e.target.checked)}
            />{" "}
            授权检查可访问的原始文件，并使用所选模型分析正文
          </label>
          <p>
            仅检查当前身份与智能体渠道允许访问的资产。正文会发送给平台已配置的模型服务；未授权或权限不足的检查显示“未完成”。不会自动修改或删除资产。
          </p>
        </div>
        <p>
          六类检查全部启用；到期复核和长期未处理事项每天都会检查。首次运行全面巡检，之后每天检查新增或变更内容。重复比较限于同一知识库。
        </p>
        {error && (
          <p role="alert" className="agent-error">
            {error}
          </p>
        )}
        {hasRunning && (
          <p className="agent-note">保存新配置会取消当前巡检，之后可按新配置重新开始。</p>
        )}
        <div className="agent-settings-actions">
          <Button type="submit">{busy ? "正在保存…" : "保存巡检设置"}</Button>
          <Button
            type="submit"
            name="intent"
            value="run"
            variant="primary"
            disabled={hasRunning}
            icon={<ClipboardCheck size={16} />}
          >
            保存并开始巡检
          </Button>
        </div>
      </fieldset>
    </form>
  );
}

function IssueDrawer({
  id,
  embedded,
  onClose,
  onChanged,
}: {
  id: string;
  embedded: boolean;
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
      className={`agent-detail${embedded ? " is-workspace-detail" : ""}`}
    >
      <div className="agent-detail-content">
        {error && (
          <p role="alert">
            {error}{" "}
            <Button size="small" onClick={() => setReload((n) => n + 1)}>
              重新加载
            </Button>
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
            {issue.requires_recheck && <p>此问题已随资料换版继续跟踪，复检通过后自动关闭。</p>}
            <h3>检查依据</h3>
            {!issue.evidence_available ? (
              <p>当前无原文权限，检查依据已隐藏。请到资料详情申请访问。</p>
            ) : (
              <>
                {issue.evidence.basis === "local_personal_information_check" && (
                  <section aria-label="个人信息检查结果">
                    <p>
                      仅展示疑似信息的类型和位置，不展示原始值。请在有权访问的资料中核实并完成脱敏，再重新检查。
                    </p>
                    <ul>
                      {Object.entries(issue.evidence.counts || {}).map(([type, count]) => (
                        <li key={type}>
                          {personalTypes[type] || "个人信息"}：{count} 处
                        </li>
                      ))}
                    </ul>
                    <ol>
                      {issue.evidence.locations?.map((location, index) => (
                        <li key={index}>
                          {(location.summary_type && summarySources[location.summary_type]) ||
                            personalSources[location.source] ||
                            "资料"}
                          第 {location.start + 1}—{location.end} 字符：
                          {personalTypes[location.category] || "个人信息"}
                        </li>
                      ))}
                    </ol>
                    {issue.evidence.locations_truncated && (
                      <p>仅列出前 20 处位置，数量包含本次已检查部分的全部命中。</p>
                    )}
                    <small>位置以解析文本为准。未检出不代表已排除所有个人信息风险。</small>
                  </section>
                )}
                {issue.evidence.quote && <blockquote>{issue.evidence.quote}</blockquote>}
                {issue.evidence.related_asset_id && (
                  <p>
                    关联资料：
                    <Link
                      to={`/knowledge/${issue.evidence.related_asset_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="在 KAP 新标签页查看知识资料"
                    >
                      {issue.evidence.related_title}
                      <span className="agent-reference-hint" aria-hidden="true">
                        {" "}
                        · KAP ↗
                      </span>
                    </Link>
                  </p>
                )}
                {issue.evidence.basis === "all_segments_reviewed" && (
                  <p>
                    已检查全部正文分段后汇总，仍需人工复核。
                    {issue.evidence.missing_sections?.length
                      ? `未识别到的必需章节：${issue.evidence.missing_sections.join("、")}`
                      : "未识别到实质正文。"}
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
            <Link
              className="agent-primary"
              to={`/knowledge/${issue.asset_id}`}
              target="_blank"
              rel="noopener noreferrer"
              title="在 KAP 新标签页查看知识资料"
            >
              打开资料详情{" "}
              <span className="agent-reference-hint" aria-hidden="true">
                KAP
              </span>{" "}
              <ArrowRight size={16} />
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
                      {issue.evidence_available && !issue.requires_recheck && (
                        <option value="false_positive">标记误报</option>
                      )}
                      {issue.suspected && issue.evidence_available && !issue.requires_recheck && (
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
                  <Button type="submit" variant="primary">
                    {busy ? "正在提交…" : "提交处理"}
                  </Button>
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
                          recheck_incomplete: "复检未完成",
                          version_replaced: "资料换版，继续跟踪",
                          history_linked: "已关联旧版处理记录",
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
