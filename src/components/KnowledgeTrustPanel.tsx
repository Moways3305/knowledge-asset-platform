import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/http";
import {
  fetchTrust,
  reportCorrection,
  replaceTrust,
  reviewTrust,
  saveTrustPolicy,
  transitionCorrection,
  type TrustState,
} from "../api/knowledgeTrust";
import { formatBeijingTime } from "../utils/time";
import TaskModal from "./TaskModal";
import KnowledgeReplacementPicker, {
  type ReplacementSelection,
} from "./KnowledgeReplacementPicker";
import "./KnowledgeTrustPanel.css";

const freshnessLabels: Record<TrustState["freshness"], string> = {
  unreviewed: "尚未复核",
  verified: "已复核",
  changed: "修改后待复核",
  due: "已到复核日期",
  needs_update: "需要更新",
  archived: "已归档或停用",
};
const correctionLabels = {
  open: "待处理",
  resolved: "待验证",
  verified: "已解决",
  rejected: "不采纳",
  duplicate: "重复反馈",
  withdrawn: "已撤回",
};

interface KnowledgeTrustPanelProps {
  assetId: string;
  revision?: string;
  onChanged?: (state: TrustState) => void;
}

export default function KnowledgeTrustPanel(props: KnowledgeTrustPanelProps) {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const requestedSection = params.get("maintenance");
  const section = ["review", "corrections", "verify"].includes(requestedSection ?? "")
    ? requestedSection
    : null;
  const [open, setOpen] = useState(Boolean(section));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setOpen(Boolean(section));
  }, [props.assetId, section]);

  return (
    <>
      <button
        type="button"
        className="btn-secondary"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        知识维护
      </button>
      <TaskModal
        open={open}
        title="知识维护"
        description="处理反馈、按需安排复核或采用新版。"
        size="large"
        portal
        busy={busy}
        onClose={() => {
          setOpen(false);
          if (section)
            setParams(
              (previous) => {
                const next = new URLSearchParams(previous);
                next.delete("maintenance");
                return next;
              },
              { replace: true, state: location.state },
            );
        }}
      >
        {open && (
          <KnowledgeTrustContent {...props} initialSection={section} onBusyChange={setBusy} />
        )}
      </TaskModal>
    </>
  );
}

function KnowledgeTrustContent({
  assetId,
  onChanged,
  onBusyChange,
  initialSection,
}: KnowledgeTrustPanelProps & {
  onBusyChange: (busy: boolean) => void;
  initialSection: string | null;
}) {
  const [state, setState] = useState<TrustState | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [schedule, setSchedule] = useState("none");
  const [interval, setInterval] = useState(180);
  const [delegated, setDelegated] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const sectionRef = useRef<HTMLElement>(null);
  const focusedSection = useRef(false);
  const [candidate, setCandidate] = useState<ReplacementSelection | null>(null);
  const generation = useRef(0);
  const lock = useRef(false);

  useEffect(() => {
    const current = ++generation.current;
    setState(null);
    setError("");
    setNote("");
    setCandidate(null);
    setReasons({});
    setDue("");
    void fetchTrust(assetId)
      .then((result) => {
        if (generation.current !== current) return;
        setState(result);
        setSchedule(
          result.review_interval_days ? "interval" : result.review_due_at ? "date" : "none",
        );
        setInterval(result.review_interval_days ?? 180);
        setDelegated(result.maintenance_delegated ?? false);
        setOwner(result.maintainer_user_id ?? "");
        if (result.review_due_at) {
          const date = new Date(result.review_due_at);
          date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
          setDue(date.toISOString().slice(0, 16));
        }
      })
      .catch((e: unknown) => {
        if (generation.current === current)
          setError(e instanceof ApiError ? e.message : "复核信息加载失败，请重试。");
      });
    return () => {
      generation.current = current + 1;
    };
  }, [assetId]);

  useEffect(() => {
    if (!state || !initialSection || focusedSection.current) return;
    const target = sectionRef.current?.querySelector<HTMLElement>(
      initialSection === "review" ? "#trust-review-heading" : "#trust-corrections-heading",
    );
    target?.focus();
    target?.scrollIntoView?.({ block: "nearest" });
    focusedSection.current = true;
  }, [state, initialSection]);

  async function run(action: () => Promise<TrustState>, message: string, reasonKey?: string) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNote("");
    const current = generation.current;
    try {
      const result = await action();
      if (generation.current === current) {
        setState(result);
        setNote(message);
        if (reasonKey) setReasons((current) => ({ ...current, [reasonKey]: "" }));
        // Parent reload invalidates metadata editors opened before this governance change.
        onChanged?.(result);
      }
    } catch (e) {
      if (generation.current === current)
        setError(e instanceof ApiError ? e.message : "操作未完成，请重试。");
    } finally {
      lock.current = false;
      setBusy(false);
      onBusyChange(false);
    }
  }

  if (!state)
    return (
      <section className="knowledge-trust" aria-label="知识维护">
        <p role="status">{error || "加载复核信息…"}</p>
        {error && (
          <button type="button" onClick={() => void run(() => fetchTrust(assetId), "已刷新")}>
            重新加载复核信息
          </button>
        )}
      </section>
    );
  const body = (key: string) => ({
    expected_updated_at: state.updated_at,
    reason: reasons[key] ?? "",
  });
  const valid = (key: string) => Boolean(reasons[key]?.trim()) && !busy;
  const reasonField = (key: string, label: string) => (
    <label className="knowledge-trust-reason">
      {label}（必填）
      <textarea
        value={reasons[key] ?? ""}
        maxLength={1000}
        disabled={busy}
        onChange={(event) => setReasons((current) => ({ ...current, [key]: event.target.value }))}
      />
    </label>
  );
  const active = state.freshness !== "archived";
  const deadline = due && !Number.isNaN(Date.parse(due)) ? new Date(due).toISOString() : null;

  return (
    <section ref={sectionRef} className="knowledge-trust" aria-label="知识维护" aria-busy={busy}>
      <header>
        <h3>复核状态</h3>
        <span>{freshnessLabels[state.freshness]}</span>
      </header>
      <dl>
        <div>
          <dt>维护人</dt>
          <dd>{state.maintainer_name ?? "知识库负责人"}</dd>
        </div>
        <div>
          <dt>下次复核</dt>
          <dd>{state.review_due_at ? formatBeijingTime(state.review_due_at) : "不定期复核"}</dd>
        </div>
        <div>
          <dt>最近复核</dt>
          <dd>{state.verified_at ? formatBeijingTime(state.verified_at) : "暂无记录"}</dd>
        </div>
      </dl>
      <p>复核用于确认内容是否仍然适用，可按需设置；到期只提醒，不自动归档。</p>
      {state.replacement_asset_id && (
        <p>
          该资料已被新版替代：
          <Link to={`/knowledge/${state.replacement_asset_id}`}>查看当前新版</Link>
        </p>
      )}
      {error && (
        <div role="alert">
          {error}
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => fetchTrust(assetId), "已读取最新状态，请核对后再提交。")}
          >
            重新核对最新状态
          </button>
        </div>
      )}
      {note && <p role="status">{note}</p>}
      {active && (
        <div className="knowledge-trust-task">
          <h3>提出新的纠错</h3>
          {reasonField("report", "纠错问题")}
          <button
            type="button"
            disabled={!valid("report")}
            onClick={() =>
              void run(
                () => reportCorrection(assetId, body("report")),
                "纠错已提交，处理后需要你再次验证。",
                "report",
              )
            }
          >
            提出纠错
          </button>
        </div>
      )}
      {state.can_manage && (
        <details open={initialSection === "review" || undefined}>
          <summary>维护设置与新版替代</summary>
          <h3 id="trust-review-heading" tabIndex={-1}>
            维护安排与复核
          </h3>
          {active && (
            <>
              <div className="knowledge-trust-fields">
                <label>
                  维护人
                  <select
                    aria-label="维护人"
                    value={owner}
                    disabled={busy || !state.can_assign}
                    onChange={(e) => {
                      setOwner(e.target.value);
                      setDelegated(false);
                    }}
                  >
                    <option value="">继承知识库负责人</option>
                    {!state.can_assign && owner && (
                      <option value={owner}>{state.maintainer_name}</option>
                    )}
                    {state.maintainers.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  复核安排
                  <select
                    aria-label="复核安排"
                    value={schedule}
                    disabled={busy}
                    onChange={(e) => setSchedule(e.target.value)}
                  >
                    <option value="none">不定期复核</option>
                    <option value="date">指定日期</option>
                    <option value="interval">周期复核</option>
                  </select>
                </label>
                {schedule === "date" && (
                  <label>
                    下次复核日期
                    <input
                      type="datetime-local"
                      value={due}
                      disabled={busy}
                      onChange={(e) => setDue(e.target.value)}
                    />
                  </label>
                )}
                {schedule === "interval" && (
                  <label>
                    复核周期（天）
                    <input
                      type="number"
                      min={1}
                      max={3650}
                      value={interval}
                      disabled={busy}
                      onChange={(e) => setInterval(Number(e.target.value))}
                    />
                  </label>
                )}
              </div>
              {state.can_assign &&
                state.maintainers.find((p) => p.id === owner)?.requires_delegation === "true" && (
                  <label className="knowledge-trust-confirm">
                    <input
                      type="checkbox"
                      checked={delegated}
                      disabled={busy}
                      onChange={(e) => setDelegated(e.target.checked)}
                    />
                    授权维护这份资料，含人工原文访问；密级调整、新版发布与归档仍由知识库管理人处理。
                  </label>
                )}
              {reasonField("policy", "维护安排说明")}
              <div className="knowledge-trust-actions">
                <button
                  type="button"
                  disabled={
                    !valid("policy") ||
                    (schedule === "date" && !deadline) ||
                    (schedule === "interval" &&
                      (!Number.isInteger(interval) || interval < 1 || interval > 3650)) ||
                    (state.maintainers.find((p) => p.id === owner)?.requires_delegation ===
                      "true" &&
                      !delegated)
                  }
                  onClick={() =>
                    void run(
                      () =>
                        saveTrustPolicy(assetId, {
                          ...body("policy"),
                          maintainer_user_id: owner || null,
                          maintenance_delegated: delegated,
                          review_due_at: schedule === "date" ? deadline : null,
                          review_interval_days: schedule === "interval" ? interval : null,
                        }),
                      "维护责任和复核日期已保存。",
                      "policy",
                    )
                  }
                >
                  保存维护安排
                </button>
              </div>
              {reasonField("review", "复核结论说明")}
              <div className="knowledge-trust-actions">
                <button
                  type="button"
                  disabled={!valid("review")}
                  onClick={() =>
                    void run(
                      () =>
                        reviewTrust(assetId, {
                          ...body("review"),
                          outcome: "verified",
                          next_review_at: state.review_interval_days
                            ? null
                            : state.review_due_at && Date.parse(state.review_due_at) > Date.now()
                              ? state.review_due_at
                              : null,
                        }),
                      "复核已通过。",
                      "review",
                    )
                  }
                >
                  确认内容仍适用
                </button>
                <button
                  type="button"
                  disabled={!valid("review")}
                  onClick={() =>
                    void run(
                      () => reviewTrust(assetId, { ...body("review"), outcome: "needs_update" }),
                      "已标记需要更新，请编辑资料或关联新版。",
                      "review",
                    )
                  }
                >
                  标记需要更新
                </button>
              </div>
              {state.can_assign && (
                <>
                  <h3>关联新版与归档</h3>
                  {reasonField("replacement", "替代关系说明")}
                  <KnowledgeReplacementPicker
                    key={assetId}
                    assetId={assetId}
                    disabled={busy}
                    onChange={setCandidate}
                  />
                  <button
                    type="button"
                    disabled={!valid("replacement") || !candidate}
                    onClick={() =>
                      void run(
                        () =>
                          replaceTrust(assetId, {
                            ...body("replacement"),
                            replacement_asset_id: candidate?.asset_id,
                            expected_replacement_updated_at: candidate?.updated_at,
                            confirm_archive: true,
                          }),
                        "已关联新版并归档旧版。",
                        "replacement",
                      )
                    }
                  >
                    关联新版并归档旧版
                  </button>
                </>
              )}
            </>
          )}
          {state.can_assign && state.replacement_asset_id && (
            <div>
              {reasonField("replacement", "替代关系说明")}
              <button
                type="button"
                disabled={!valid("replacement")}
                onClick={() =>
                  void run(
                    () =>
                      replaceTrust(assetId, { ...body("replacement"), replacement_asset_id: null }),
                    "替代关系已撤销，旧版仍保持归档，需要单独确认启用。",
                    "replacement",
                  )
                }
              >
                撤销替代关系（不自动启用）
              </button>
            </div>
          )}
        </details>
      )}
      <h3 id="trust-corrections-heading" tabIndex={-1}>
        资料纠错
      </h3>
      {!state.corrections.length && <p>暂无你可查看的纠错记录。</p>}
      {state.corrections.map((item) => (
        <article key={item.id}>
          <strong>{correctionLabels[item.status]}</strong>
          <p>{item.description}</p>
          {item.resolution && <p>处理说明：{item.resolution}</p>}
          {(item.can_resolve ||
            item.can_verify ||
            item.can_close ||
            item.can_reopen ||
            item.can_withdraw) &&
            reasonField(`correction:${item.id}`, "此条反馈的处理说明")}
          <div className="knowledge-trust-actions">
            {(
              [
                [item.can_resolve, "resolve", "已更新，交给提出者验证"],
                [item.can_resolve, "reject", "不采纳"],
                [item.can_resolve, "duplicate", "标记重复反馈"],
                [item.can_verify, "verify", "验证已解决"],
                [item.can_close, "close", "管理人核实并关闭"],
                [item.can_reopen, "reopen", "仍有问题，重新处理"],
                [item.can_withdraw, "withdraw", "撤回反馈"],
              ] as const
            )
              .filter(([allowed]) => allowed)
              .map(([, action, label]) => (
                <button
                  key={action}
                  type="button"
                  disabled={!valid(`correction:${item.id}`)}
                  onClick={() =>
                    void run(
                      () =>
                        transitionCorrection(assetId, item.id, {
                          expected_updated_at: item.updated_at,
                          reason: reasons[`correction:${item.id}`] ?? "",
                          action,
                        }),
                      "反馈状态已更新。",
                      `correction:${item.id}`,
                    )
                  }
                >
                  {label}
                </button>
              ))}
          </div>
        </article>
      ))}
    </section>
  );
}
